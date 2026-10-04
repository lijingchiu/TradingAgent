"""Synthetic causality/market-gap fixtures; never strategy profit evidence."""

import unittest
from copy import deepcopy

import numpy as np
import pandas as pd

from research.intraday_engine import njit, run_intraday_backtest
from research.intraday_sweep.study import candidates, signals
from research.statistics import daily_realized_returns, summarize_trades
from trading_agent.risk import CostModel


class SweepCausalityTests(unittest.TestCase):
    def fixture(self, count=1600):
        frame = pd.DataFrame({"open": np.full(count, 1.1), "high": np.full(count, 1.104),
                              "low": np.full(count, 1.099), "close": np.full(count, 1.1)})
        frame.loc[1536, ["open", "high", "low", "close"]] = [1.099, 1.1005, 1.0988, 1.1003]
        return frame

    def test_future_extremes_cannot_relabel_past_sweep(self):
        frame = self.fixture()
        config = candidates()[0]
        before = signals(frame, config, 5)
        self.assertTrue(before[1536])
        future = pd.DataFrame({"open": [100.0] * 50, "high": [101.0] * 50,
                               "low": [.0001] * 50, "close": [100.5] * 50})
        extended = pd.concat([frame, future], ignore_index=True)
        after = signals(extended, config, 5)
        np.testing.assert_array_equal(before, after[:len(frame)])
        self.assertFalse(np.any(before[:1536]))

    def test_signal_close_is_never_its_entry_price(self):
        frame = self.fixture()
        config = candidates()[0]
        entries = signals(frame, config, 5)
        result = run_intraday_backtest(
            1_600_000_000 + np.arange(len(frame)) * 300,
            *(frame[key].to_numpy() for key in ("open", "high", "low", "close")),
            entries, .0015, .002, quote_kind="bid", use_jit=False,
            max_signal_age_seconds=300)
        self.assertEqual(result["trades"][0]["entry_index"], 1537)
        self.assertAlmostEqual(result["trades"][0]["entry_quote"], frame.iloc[1537]["open"])
        self.assertNotEqual(result["trades"][0]["entry_quote"], frame.iloc[1536]["close"])


class NativeIntervalGapTests(unittest.TestCase):
    def quote_fixture(self):
        # Three native 5m bars, then a two-day closure, then one native 5m bar.
        times = np.array([0, 300, 600, 173400, 173700], dtype=np.int64)
        return [times, np.full(5, 1.1), np.full(5, 1.101),
                np.full(5, 1.099), np.full(5, 1.1)]

    def test_stale_signal_after_gap_is_rejected_but_next_fresh_signal_can_enter(self):
        args = self.quote_fixture()
        for jit in (False, True) if njit is not None else (False,):
            with self.subTest(jit=jit):
                result = run_intraday_backtest(*args, [False, False, True, True, False],
                                              .01, .02, use_jit=jit)
                self.assertEqual(result["summary"]["max_signal_age_seconds"], 300)
                self.assertTrue(result["summary"]["signal_age_bound_inferred_from_native_interval"])
                self.assertEqual(result["summary"]["stale_signal_entries_rejected"], 1)
                self.assertEqual([trade["entry_index"] for trade in result["trades"]], [4])

    def test_gap_exits_on_existing_position_remain_observed_and_unclipped(self):
        args = self.quote_fixture()
        args[1][3:] = 1.05
        args[2][3:] = 1.06
        args[3][3:] = 1.04
        args[4][3:] = 1.05
        result = run_intraday_backtest(*args, [True, False, True, False, False], .01, .02,
                                      max_signal_age_seconds=300, use_jit=False)
        self.assertEqual(len(result["trades"]), 1)
        trade = result["trades"][0]
        self.assertEqual(trade["entry_index"], 1)
        self.assertEqual(trade["exit_index"], 3)
        self.assertEqual(trade["reason"], "stop_gap")
        self.assertEqual(trade["exit_mid"], 1.05)
        self.assertLess(trade["exit_mid"], trade["stop_price"])
        self.assertEqual(result["summary"]["stale_signal_entries_rejected"], 0)

    def test_age_bound_is_explicit_and_entry_mask_is_not_mutated(self):
        args = self.quote_fixture()
        allowed = np.array([True] * 5)
        result = run_intraday_backtest(*args, [False, False, True, False, False], .01, .02,
                                      entry_allowed=allowed, max_signal_age_seconds=300, use_jit=False)
        self.assertEqual(result["trades"], [])
        np.testing.assert_array_equal(allowed, [True] * 5)
        self.assertFalse(result["summary"]["signal_age_bound_inferred_from_native_interval"])
        for invalid in (0, -1, True, 300.0):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                run_intraday_backtest(*args, [False] * 5, .01, .02,
                                      max_signal_age_seconds=invalid, use_jit=False)

    def test_split_begins_flat_and_never_processes_post_split_entries(self):
        args = self.quote_fixture()
        result = run_intraday_backtest(*args, [True, True, True, True, True], .01, .02,
                                      start_index=2, end_index=3, max_signal_age_seconds=300,
                                      use_jit=False)
        self.assertEqual([trade["entry_index"] for trade in result["trades"]], [2])
        self.assertEqual(result["trades"][0]["exit_index"], 2)
        self.assertEqual(result["trades"][0]["entry_equity"], 100_000)
        self.assertEqual(result["trades"][0]["reason"], "sample_end")
        self.assertEqual(result["summary"]["eligible_trades"], 0)


class ObservedBookStatisticsTests(unittest.TestCase):
    def fixture(self, multiplier=1):
        return run_intraday_backtest(
            [1672531200, 1672531500, 1672531800], [1.1] * 3,
            [1.1005] * 3, [1.0995] * 3, [1.1] * 3, [True, False, False],
            .002, .003, quote_kind="bid", ask_opens=[1.1001, 1.1007, 1.105],
            observed_spread_multiplier=multiplier, max_holding_bars=1,
            max_signal_age_seconds=300, use_jit=False,
            book_source="synthetic QA synchronized BID/ASK")

    def test_observed_engine_statistics_preserve_bid_baseline_and_reconcile_manual_cash(self):
        result = self.fixture()
        trade = result["trades"][0]
        summary = summarize_trades(result["trades"])
        units = trade["units"]
        costs = CostModel()
        buy, sell = 1.10072, 1.09998
        expected = units * (sell - buy) - costs.commission(units * buy) - costs.commission(units * sell)
        self.assertIsNone(summary["gross_mid_profit"])
        self.assertEqual(summary["price_baseline"], "bid")
        self.assertTrue(summary["observed_book_costs_complete"])
        self.assertAlmostEqual(summary["gross_bid_profit"], 0)
        self.assertAlmostEqual(summary["observed_entry_spread_cost"], units * .0007)
        self.assertAlmostEqual(summary["modeled_slippage_cost"], units * .00004)
        self.assertAlmostEqual(summary["net_profit"], expected)
        self.assertAlmostEqual(summary["source_baseline_gross_profit"] -
                               summary["modeled_entry_spread_cost"] - summary["modeled_slippage_cost"] -
                               summary["explicit_commission_and_carry"], expected)
        self.assertAlmostEqual(trade["cash_after_exit"], 100_000 + expected)
        days = daily_realized_returns(result["trades"], 100_000, "2023-01-01", "2023-01-02")
        self.assertAlmostEqual(days[0]["realized_net_pnl"], expected)

    def test_stressed_book_keeps_observed_and_modeled_spread_cost_separate(self):
        result = self.fixture(multiplier=2)
        summary = summarize_trades(result["trades"])
        self.assertIsNone(summary["gross_mid_profit"])
        self.assertAlmostEqual(summary["modeled_entry_spread_cost"], 2 * summary["observed_entry_spread_cost"])
        self.assertAlmostEqual(summary["gross_bid_profit"] - summary["modeled_entry_spread_cost"] -
                               summary["modeled_slippage_cost"] - summary["explicit_commission_and_carry"],
                               summary["net_profit"])

    def test_incorrect_bid_gross_or_cost_partition_cannot_pass_statistics(self):
        trade = self.fixture()["trades"][0]
        for field in ("bid_gross_pnl", "spread_cost", "slippage_cost"):
            incorrect = deepcopy(trade)
            incorrect[field] += 1
            with self.subTest(field=field), self.assertRaises(ValueError):
                summarize_trades([incorrect])


if __name__ == "__main__":
    unittest.main()
