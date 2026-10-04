"""Synthetic Decimal accounting fixtures; no actual strategy outcome data."""

from copy import deepcopy
from decimal import Decimal
import unittest

import numpy as np

from research.futures_engine import run_futures_backtest
from research.futures_statistics import summarize_trades
from trading_agent.risk import CostModel


class FuturesEngineTests(unittest.TestCase):
    def simulate(self, op, hi, lo, cl, directions, **kwargs):
        n = len(op)
        return run_futures_backtest(
            kwargs.pop("timestamps", np.arange(n) * 300), op, hi, lo, cl,
            directions, kwargs.pop("stop_distances", 2), kwargs.pop("target_distances", 3),
            contract_multiplier=kwargs.pop("contract_multiplier", 20),
            initial_equity=kwargs.pop("initial_equity", 1_000_000),
            flat_fee_per_contract_per_side=kwargs.pop("flat_fee_per_contract_per_side", 5),
            **kwargs)

    def short_gap(self, **kwargs):
        return self.simulate([100, 100, 110], [101, 101, 111],
                             [99, 99, 109], [100, 100, 110], [-1, 0, 0], **kwargs)

    def test_short_gap_independent_decimal_collateral_and_fees(self):
        result = self.short_gap(include_equity_curve=True)
        trade = result["trades"][0]
        d = Decimal
        entry, exited, multiplier, fee = d("99.5"), d("110.5"), d("20"), d("5")
        gross = -multiplier * (exited - entry)
        net = gross - 2 * fee
        reserve = d("100") * multiplier
        after_entry = d("1000000") - reserve - fee
        after_exit = after_entry + reserve + gross - fee
        self.assertEqual(trade["entry_fill"], float(entry))
        self.assertEqual(trade["exit_fill"], float(exited))
        self.assertEqual(trade["gross_pnl"], float(gross))
        self.assertEqual(trade["net_pnl"], float(net))
        self.assertEqual(trade["notional_reserve"], float(reserve))
        self.assertEqual(trade["cash_after_entry"], float(after_entry))
        self.assertEqual(trade["cash_after_exit"], float(after_exit))
        self.assertEqual(trade["reason"], "stop_gap")
        self.assertEqual(trade["direction"], -1)
        self.assertEqual(trade["units"], 20)
        self.assertEqual(trade["contracts"], 1)
        self.assertEqual(result["summary"]["ending_equity"], float(after_exit))
        self.assertEqual(trade["max_adverse_excursion"], -float(net))

    def test_long_and_short_ambiguous_bar_exit_stop_first(self):
        for direction, exit_quote in ((1, 98), (-1, 102)):
            with self.subTest(direction=direction):
                result = self.simulate([100, 100], [101, 104], [99, 96],
                                       [100, 100], [direction, 0])
                trade = result["trades"][0]
                self.assertEqual(trade["entry_index"], 1)
                self.assertEqual(trade["exit_index"], 1)
                self.assertEqual(trade["reason"], "stop")
                self.assertEqual(trade["exit_quote"], exit_quote)
                self.assertEqual(trade["net_pnl"], -70)

    def test_favorable_short_opening_gap_preserves_direction(self):
        result = self.simulate([100, 100, 90], [101, 101, 91],
                               [99, 99, 89], [100, 100, 90], [-1, 0, 0])
        trade = result["trades"][0]
        self.assertEqual(trade["reason"], "target_gap")
        self.assertEqual(trade["exit_fill"], 90.5)
        self.assertEqual(trade["net_pnl"], 170)

    def test_bps_fees_use_absolute_fill_notional_on_each_side(self):
        result = self.short_gap(flat_fee_per_contract_per_side=None)
        trade = result["trades"][0]
        d = Decimal
        entry_fee = max(d(".10"), d("99.5") * d("20") * d(".000035"))
        exit_fee = max(d(".10"), d("110.5") * d("20") * d(".000035"))
        self.assertEqual(trade["entry_commission"], float(entry_fee))
        self.assertEqual(trade["exit_commission"], float(exit_fee))
        self.assertAlmostEqual(trade["net_pnl"], float(d("-220") - entry_fee - exit_fee))
        self.assertEqual(result["summary"]["commission_profile"], "bps_with_minimum_per_side")

    def test_unbounded_short_gap_is_unclipped_and_marks_real_breach(self):
        result = self.simulate([100, 100, 100_000], [101, 101, 100_001],
                               [99, 99, 99_999], [100, 100, 100_000], [-1, 0, 0])
        trade = result["trades"][0]
        self.assertEqual(trade["exit_fill"], 100_000.5)
        self.assertLess(trade["net_pnl"], -1_000_000)
        self.assertTrue(trade["risk_breach"])
        self.assertEqual(result["summary"]["risk_breaches"], 1)
        self.assertLess(result["summary"]["ending_equity"], 0)
        self.assertFalse(result["summary"]["derivative_loss_bound_established"])
        self.assertFalse(result["summary"]["paper_activation_authorized"])

    def test_hypothetical_negative_futures_gap_is_not_price_floored(self):
        result = self.simulate([100, 100, -25], [101, 101, -24],
                               [99, 99, -26], [100, 100, -25], [1, 0, 0])
        trade = result["trades"][0]
        self.assertEqual(trade["exit_quote"], -25)
        self.assertEqual(trade["exit_fill"], -25.5)
        self.assertEqual(trade["net_pnl"], -2530)
        self.assertEqual(trade["reason"], "stop_gap")

    def test_short_mae_and_peak_drawdown_have_favorable_then_adverse_order(self):
        result = self.simulate([100, 100], [101, 109], [99, 91],
                               [100, 100], [-1, 0], stop_distances=20, target_distances=20)
        trade = result["trades"][0]
        self.assertEqual(trade["reason"], "sample_end")
        self.assertEqual(trade["max_adverse_excursion"], 210)
        self.assertEqual(trade["max_drawdown"], 360)

    def test_stop_only_bars_include_reachable_favorable_peak_both_directions(self):
        for direction, high, low in ((1, 130, 89), (-1, 111, 70)):
            with self.subTest(direction=direction):
                result = self.simulate([100, 100], [101, high], [99, low],
                                       [100, 100], [direction, 0],
                                       stop_distances=10, target_distances=40)
                trade = result["trades"][0]
                self.assertEqual(trade["reason"], "stop")
                self.assertEqual(trade["net_pnl"], -230)
                self.assertEqual(trade["max_drawdown"], 800)

    def test_target_bars_cap_favorable_then_adverse_upper_envelope(self):
        for direction, high, low in ((1, 115, 95), (-1, 105, 85)):
            with self.subTest(direction=direction):
                result = self.simulate([100, 100], [101, high], [99, low],
                                       [100, 100], [direction, 0],
                                       stop_distances=10, target_distances=10)
                trade = result["trades"][0]
                self.assertEqual(trade["reason"], "target")
                self.assertEqual(trade["net_pnl"], 170)
                self.assertEqual(trade["max_drawdown"], 300)
                self.assertEqual(trade["excursion_model"], "conservative_OHLC_pre_exit_upper_envelope")

    def test_observed_risk_breach_halts_subsequent_entries(self):
        result = self.simulate([100, 100, 700, 100, 100], [101, 101, 701, 101, 101],
                               [99, 99, 699, 99, 99], [100, 100, 700, 100, 100],
                               [-1, 0, -1, -1, 0])
        self.assertEqual(result["summary"]["closed_trades"], 1)
        self.assertTrue(result["summary"]["risk_halt_triggered"])
        self.assertGreater(result["summary"]["halted_entries_rejected"], 0)
        self.assertGreater(result["summary"]["ending_equity"], 0)

    def test_daily_exit_previous_signal_and_no_same_bar_reentry(self):
        result = self.simulate([100] * 4, [101] * 4, [99] * 4, [100] * 4,
                               [-1] * 4, daily_exit=[False, False, True, True])
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["trades"][0]["reason"], "daily_exit")
        self.assertEqual(result["trades"][0]["exit_index"], 2)
        previous = self.simulate([100] * 3, [101] * 3, [99] * 3, [100] * 3,
                                 [-1, 0, 0], exit_signals=[False, True, False])
        self.assertEqual(previous["trades"][0]["reason"], "signal_exit")
        self.assertEqual(previous["trades"][0]["exit_index"], 2)

    def test_native_age_blocks_new_entry_after_gap_but_existing_stop_exits(self):
        stale = self.short_gap(timestamps=[0, 86_400, 86_700])
        self.assertEqual(stale["summary"]["closed_trades"], 0)
        self.assertEqual(stale["summary"]["stale_signal_entries_rejected"], 1)
        holding = self.short_gap(timestamps=[0, 300, 86_400])
        self.assertEqual(holding["trades"][0]["reason"], "stop_gap")

    def test_clock_bar_horizon_and_terminal_closes_are_distinguished(self):
        held = self.simulate([100] * 4, [101] * 4, [99] * 4, [100] * 4,
                             [1, 0, 0, 0], max_holding_bars=1)
        self.assertEqual(held["trades"][0]["reason"], "holding_bars")
        clock = self.simulate([100] * 3, [101] * 3, [99] * 3, [100] * 3,
                              [1, 0, 0], timestamps=[0, 300, 5 * 86400 + 300])
        self.assertEqual(clock["trades"][0]["reason"], "expiry")
        terminal = self.simulate([100] * 2, [101] * 2, [99] * 2, [100] * 2, [1, 0])
        self.assertEqual(terminal["summary"]["eligible_trades"], 0)
        self.assertEqual(terminal["summary"]["terminal_liquidations"], 1)

    def test_notional_cap_is_initial_equity_and_uses_conservative_short_reference(self):
        result = self.simulate([401] * 2, [402] * 2, [400] * 2, [401] * 2, [-1, 0])
        # Short fill 400.5 would be 8,010 and source 401 would be 8,020;
        # neither contract can fit the fixed 8,000 initial-equity cap.
        self.assertEqual(result["summary"]["closed_trades"], 0)
        self.assertEqual(result["summary"]["rejected_entries"], 1)
        boundary = self.simulate([400.25] * 2, [401] * 2, [399] * 2, [400.25] * 2, [-1, 0])
        self.assertEqual(boundary["summary"]["closed_trades"], 0)

    def test_previous_loss_tightens_the_current_entry_equity_reserve_guard(self):
        result = self.simulate([397, 397, 400, 400], [398, 398, 401, 401],
                               [396, 394, 399, 399], [397, 397, 400, 400],
                               [1, 0, -1, 0])
        # The first long loses 70. A later short's genuine raw notional 8,000
        # fits initial capital's cap but exceeds current equity's 7,999.44 cap;
        # the discounted 7,990 short fill must not bypass either guard.
        self.assertEqual(result["summary"]["closed_trades"], 1)
        self.assertEqual(result["trades"][0]["net_pnl"], -70)
        self.assertEqual(result["summary"]["rejected_entries"], 1)
        self.assertEqual(result["summary"]["ending_equity"], 999_930)

    def test_split_starts_flat_and_uses_only_previous_completed_bar(self):
        result = self.simulate([100] * 5, [101] * 5, [99] * 5, [100] * 5,
                               [-1, 1, 0, 0, 0], start_index=2, end_index=4)
        self.assertEqual(result["trades"][0]["entry_index"], 2)
        self.assertEqual(result["trades"][0]["direction"], 1)
        self.assertEqual(result["trades"][0]["exit_index"], 3)

    def test_invalid_inputs_are_rejected(self):
        for kwargs in ({"contract_multiplier": 0}, {"max_holding_bars": 13},
                       {"max_holding_days": 6}, {"flat_fee_per_contract_per_side": -1},
                       {"max_signal_age_seconds": 0}, {"initial_equity": float("nan")}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.short_gap(**kwargs)
        with self.assertRaises(ValueError):
            self.simulate([100] * 2, [101] * 2, [99] * 2, [100] * 2, [-2, 0])


class FuturesStatisticsTests(unittest.TestCase):
    def rows(self):
        fixture = FuturesEngineTests()
        short = fixture.short_gap()["trades"][0]
        long = fixture.simulate([100, 100, 95], [101, 101, 96],
                                [99, 99, 94], [100, 100, 95], [1, 0, 0])["trades"][0]
        return [short, long]

    def test_mixed_direction_gross_and_cost_decomposition(self):
        summary = summarize_trades(self.rows())
        # Real unchanged source quotes: short 100->110 loses 200;
        # long 100->95 loses 100. Side friction costs 20/trade + fees10.
        self.assertEqual(summary["gross_source_last_trade_profit"], -300)
        self.assertEqual(summary["gross_after_price_friction_before_fees"], -340)
        self.assertEqual(summary["explicit_commission_and_carry"], 20)
        self.assertEqual(summary["net_profit"], -360)
        self.assertIsNone(summary["gross_mid_profit"])
        self.assertEqual(summary["long_trades"], 1)
        self.assertEqual(summary["short_trades"], 1)
        self.assertEqual(summary["price_baseline"], "source_last_trade_as_mid_proxy")

    def test_signed_price_fee_or_cash_tampering_is_rejected(self):
        for field, value in (("direction", 1), ("contracts", .5), ("units", -20),
                             ("source_last_trade_gross_pnl", 200), ("gross_pnl", -200),
                             ("entry_commission", -1), ("net_pnl", 0),
                             ("spread_cost", 0), ("cash_after_exit", 1_000_000),
                             ("entry_fill", 100.5)):
            rows = deepcopy(self.rows())
            rows[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                summarize_trades(rows)


if __name__ == "__main__":
    unittest.main()
