"""Synthetic randomized reference checks, not profitability evidence."""

from dataclasses import asdict, replace
from datetime import datetime, timezone
import unittest

import numpy as np

from research.intraday_engine import run_intraday_backtest, njit
from trading_agent.execution import Bar, evaluate_long, force_close, liquidation_pnl, open_long
from trading_agent.risk import CostModel, size_position


def reference(times, opens, highs, lows, closes, entries, stops, targets,
              costs=CostModel(), exits=None, allowed=None, max_bars=None,
              max_days=5, initial=100_000, first=0, last=None, unit_step=1):
    """Use the production Decimal sizer and execution dataclasses as oracle."""
    n = len(times)
    last = n if last is None else last
    exits = np.zeros(n, dtype=bool) if exits is None else exits
    allowed = np.ones(n, dtype=bool) if allowed is None else allowed
    equity = initial
    position = None
    entry_index = None
    trades = []
    curve = []
    for i in range(first, last):
        stamp = datetime.fromtimestamp(int(times[i]), timezone.utc)
        bar = Bar(stamp, opens[i], highs[i], lows[i], closes[i])
        existed = position is not None
        if position is None and i > 0 and entries[i - 1] and allowed[i]:
            try:
                plan = size_position(equity, opens[i], stops[i - 1], max_days=max_days, costs=costs)
                if unit_step != 1:
                    quantity = plan.units // unit_step * unit_step
                    if quantity <= 0:
                        raise ValueError("insufficient fully paid lot capacity")
                    notional = quantity * plan.entry_fill
                    commission = costs.commission(notional)
                    plan = replace(plan, units=quantity, notional=notional,
                                   entry_commission=commission,
                                   worst_case_loss=notional + commission + costs.minimum_commission)
                position = open_long(plan, stamp, opens[i] + targets[i - 1],
                                     datetime.fromtimestamp(int(times[i - 1]), timezone.utc))
                entry_index = i
            except ValueError:
                pass
        trade = None
        if position is not None:
            mandatory_open_exit = (
                bar.open <= position.stop_price or bar.open >= position.target_price
                or (bar.time - position.entry_time).total_seconds() >= max_days * 86400)
            if mandatory_open_exit:
                trade = evaluate_long(position, bar)
            elif max_bars is not None and i - entry_index >= max_bars:
                trade = force_close(position, stamp, bar.open, "holding_bars")
            elif existed and i > 0 and exits[i - 1]:
                trade = force_close(position, stamp, bar.open, "signal_exit")
            else:
                trade = evaluate_long(position, bar)
        if trade is not None:
            trades.append({**asdict(trade), "entry_index": entry_index, "exit_index": i})
            equity += trade.net_pnl
            position = None
        curve.append(equity + (liquidation_pnl(position, stamp, bar.close) if position else 0))
    if position is not None:
        i = last - 1
        trade = force_close(position, datetime.fromtimestamp(int(times[i]), timezone.utc), closes[i], "sample_end")
        trades.append({**asdict(trade), "entry_index": entry_index, "exit_index": i})
        equity += trade.net_pnl
        curve[-1] = equity
    return trades, curve, equity


def randomized(seed, n=1800):
    generator = np.random.default_rng(seed)
    times = 1_609_459_200 + np.arange(n, dtype=np.int64) * 900
    # Include sporadic opening gaps that stop assumptions cannot conceal.
    closes = 1.12 + np.cumsum(generator.normal(0, .0005, n))
    opens = np.r_[closes[0], closes[:-1]] + generator.normal(0, .00015, n)
    opens[::127] += generator.choice([-.005, .005], len(opens[::127]))
    highs = np.maximum(opens, closes) + generator.uniform(.00005, .001, n)
    lows = np.minimum(opens, closes) - generator.uniform(.00005, .001, n)
    entries = generator.random(n) < .20
    exits = generator.random(n) < .05
    allowed = generator.random(n) > .1
    stops = generator.uniform(.0005, .0025, n)
    targets = generator.uniform(.0005, .0035, n)
    return times, opens, highs, lows, closes, entries, stops, targets, exits, allowed


class IntradayReferenceTests(unittest.TestCase):
    def compare(self, values, costs=CostModel(), max_bars=None, max_days=5,
                first=0, last=None, use_jit=False, unit_step=1, initial=100_000):
        times, op, hi, lo, cl, entries, stops, targets, exits, allowed = values
        actual = run_intraday_backtest(
            times, op, hi, lo, cl, entries, stops, targets, exit_signals=exits,
            entry_allowed=allowed, costs=costs, max_holding_bars=max_bars,
            max_holding_days=max_days, start_index=first, end_index=last,
            include_equity_curve=True, use_jit=use_jit,
            unit_step=unit_step, initial_equity=initial)
        expected, curve, equity = reference(*values[:8], costs=costs, exits=exits,
                                          allowed=allowed, max_bars=max_bars,
                                          max_days=max_days, first=first, last=last,
                                          unit_step=unit_step, initial=initial)
        self.assertEqual(len(actual["trades"]), len(expected))
        self.assertGreater(len(expected), 20)
        for a, e in zip(actual["trades"], expected):
            self.assertEqual(a["units"], e["units"])
            for name in ("entry_index", "exit_index", "reason", "risk_breach"):
                self.assertEqual(a[name], e[name], name)
            for name in ("entry_mid", "entry_fill", "exit_mid", "exit_fill",
                         "entry_commission", "exit_commission", "gross_pnl", "net_pnl",
                         "max_adverse_excursion", "max_drawdown", "entry_equity",
                         "risk_limit", "worst_case_loss"):
                self.assertAlmostEqual(a[name], e[name], delta=1e-7, msg=name)
            self.assertEqual(a["entry_time"], int(e["entry_time"].timestamp()))
            self.assertEqual(a["exit_time"], int(e["exit_time"].timestamp()))
            self.assertGreaterEqual(a["cash_after_entry"], 0)
            self.assertLessEqual(a["entry_notional"], a["entry_equity"] * .008 + 1e-9)
            self.assertAlmostEqual(a["cash_after_entry"],
                                   a["entry_equity"] - a["entry_notional"] - a["entry_commission"], delta=1e-7)
            self.assertAlmostEqual(a["cash_after_exit"] - a["entry_equity"], a["net_pnl"], delta=1e-7)
        np.testing.assert_allclose([p["equity"] for p in actual["equity_curve"]], curve, atol=1e-7, rtol=1e-12)
        self.assertAlmostEqual(actual["summary"]["ending_equity"], equity, delta=1e-7)
        self.assertEqual(actual["summary"]["risk_breaches"], 0)
        return actual

    def test_seeded_random_paths_match_production_execution(self):
        for seed in (7, 19, 2026):
            with self.subTest(seed=seed):
                self.compare(randomized(seed))

    def test_cost_and_horizon_variations_match_production(self):
        for costs in (CostModel(spread_pips=4, slippage_pips=.4, minimum_commission=.2),
                      CostModel(commission_bps=15, minimum_commission=0),
                      CostModel(minimum_commission=250)):
            with self.subTest(costs=costs):
                self.compare(randomized(78), costs=costs, max_bars=7,
                             max_days=2, first=30, last=1400)

    @unittest.skipUnless(njit is not None, "Numba optional acceleration is not installed")
    def test_jit_matches_python_and_production_on_seeded_paths(self):
        self.compare(randomized(45), max_bars=8, use_jit=True)
        a = run_intraday_backtest(*randomized(45)[:8], use_jit=False)
        b = run_intraday_backtest(*randomized(45)[:8], use_jit=True)
        self.assertEqual(a["trades"], b["trades"])


class IntradaySemanticsTests(unittest.TestCase):
    def run_small(self, op, hi, lo, cl, entries, stops=.002, targets=.003, **kwargs):
        return run_intraday_backtest(
            1_609_459_200 + np.arange(len(op)) * 900,
            op, hi, lo, cl, entries, stops, targets, use_jit=False, **kwargs)

    def test_next_bar_entry_and_stop_priority(self):
        result = self.run_small([1.1, 1.1], [1.101, 1.105], [1.099, 1.097],
                                [1.1, 1.101], [True, False])
        trade = result["trades"][0]
        self.assertEqual(trade["entry_index"], 1)
        self.assertEqual(trade["exit_index"], 1)
        self.assertEqual(trade["reason"], "stop")
        self.assertAlmostEqual(trade["exit_mid"], 1.098)
        self.assertLess(trade["net_pnl"], 0)

    def test_stop_gap_keeps_loss_instead_of_clipping(self):
        result = self.run_small([1.1, 1.1, 0], [1.101, 1.101, 0],
                                [1.099, 1.099, 0], [1.1, 1.1, 0], [True, False, False])
        trade = result["trades"][0]
        self.assertEqual(trade["reason"], "stop_gap")
        self.assertEqual(trade["exit_mid"], 0)
        self.assertEqual(trade["exit_fill"], 0)
        self.assertAlmostEqual(-trade["net_pnl"], trade["worst_case_loss"])
        self.assertLessEqual(-trade["net_pnl"], 1000)
        self.assertGreater(-trade["net_pnl"], 790)

    def test_discretionary_exit_executes_at_next_open(self):
        result = self.run_small([1.1, 1.1, 1.1005], [1.101, 1.101, 1.104],
                                [1.099, 1.099, 1.096], [1.1, 1.1, 1.101],
                                [True, False, False], exit_signals=[False, True, False])
        trade = result["trades"][0]
        self.assertEqual(trade["exit_index"], 2)
        self.assertEqual(trade["reason"], "signal_exit")
        self.assertEqual(trade["exit_mid"], 1.1005)

    def test_session_mask_applies_at_execution_and_no_same_bar_reentry(self):
        result = self.run_small([1.1] * 5, [1.104] * 5, [1.099] * 5,
                                [1.1] * 5, [True] * 5,
                                entry_allowed=[True, False, True, False, True])
        self.assertEqual([t["entry_index"] for t in result["trades"]], [2, 4])

    def test_bar_horizon_uses_next_open_and_terminal_exit_is_separate(self):
        result = self.run_small([1.1] * 5, [1.101] * 5, [1.099] * 5,
                                [1.1] * 5, [True, False, True, False, False],
                                max_holding_bars=1)
        self.assertEqual([t["reason"] for t in result["trades"]], ["holding_bars", "holding_bars"])
        terminal = self.run_small([1.1, 1.1], [1.101, 1.101], [1.099, 1.099],
                                  [1.1, 1.1], [True, False])
        self.assertEqual(terminal["summary"]["terminal_liquidations"], 1)
        self.assertEqual(terminal["summary"]["eligible_trades"], 0)
        self.assertEqual(terminal["trades"][0]["reason"], "sample_end")

    def test_fee_ledger_and_expected_roundtrip_cost(self):
        result = self.run_small([1.1, 1.1], [1.101, 1.101], [1.099, 1.099],
                                [1.1, 1.1], [True, False])
        trade = result["trades"][0]
        expected_loss = trade["units"] * .00024 + .20
        self.assertAlmostEqual(trade["net_pnl"], -expected_loss)
        self.assertAlmostEqual(result["summary"]["net_profit"], -expected_loss)
        self.assertAlmostEqual(result["summary"]["total_commission"], .2)
        self.assertAlmostEqual(result["summary"]["modeled_spread_slippage_cost"], trade["units"] * .00024)

    def test_bid_candles_fill_at_assumed_ask_then_bid_with_slippage(self):
        bid = 1.1
        costs = CostModel()
        result = self.run_small([bid, bid], [bid + .001] * 2,
                                [bid - .001] * 2, [bid, bid], [True, False],
                                quote_kind="bid", costs=costs)
        trade = result["trades"][0]
        expected_buy = bid + costs.spread_pips * costs.pip_size + costs.slippage_pips * costs.pip_size
        expected_sell = bid - costs.slippage_pips * costs.pip_size
        self.assertAlmostEqual(trade["entry_fill"], expected_buy)
        self.assertAlmostEqual(trade["exit_fill"], expected_sell)
        self.assertAlmostEqual(trade["entry_mid"], bid + .0001)
        self.assertAlmostEqual(trade["entry_quote"], bid)
        self.assertAlmostEqual(trade["exit_quote"], bid)
        entry_fee = costs.commission(trade["units"] * expected_buy)
        exit_fee = costs.commission(trade["units"] * expected_sell)
        expected_net = trade["units"] * (expected_sell - expected_buy) - entry_fee - exit_fee
        self.assertAlmostEqual(trade["net_pnl"], expected_net)
        self.assertAlmostEqual(trade["cash_after_entry"],
                               100_000 - trade["units"] * expected_buy - entry_fee)
        self.assertAlmostEqual(trade["cash_after_exit"], 100_000 + expected_net)
        self.assertEqual(result["summary"]["quote_kind"], "bid")
        self.assertEqual(result["summary"]["mid_model"], "bid_plus_assumed_fixed_half_spread")

    def test_bid_spread_stress_recomputes_mid_offset_and_full_ask_cost(self):
        costs = CostModel(spread_pips=4, slippage_pips=.4,
                          commission_bps=.7, minimum_commission=.2)
        bid = 1.1
        result = self.run_small([bid, bid], [bid + .001] * 2,
                                [bid - .001] * 2, [bid, bid], [True, False],
                                quote_kind="bid", costs=costs)
        trade = result["trades"][0]
        self.assertAlmostEqual(trade["entry_mid"], bid + .0002)
        self.assertAlmostEqual(trade["entry_fill"], bid + .00044)
        self.assertAlmostEqual(trade["exit_fill"], bid - .00004)
        manual = trade["units"] * (-.00048) - costs.commission(trade["units"] * (bid + .00044)) - costs.commission(trade["units"] * (bid - .00004))
        self.assertAlmostEqual(trade["net_pnl"], manual)
        # Compare to the existing production mid-price execution reference.
        plan = size_position(100_000, bid + .0002, .002, costs=costs)
        position = open_long(plan, datetime.fromtimestamp(900, timezone.utc), bid + .0002 + .003)
        expected = force_close(position, position.entry_time, bid + .0002, "sample_end")
        self.assertEqual(trade["units"], plan.units)
        self.assertAlmostEqual(trade["net_pnl"], expected.net_pnl)

    def test_future_signal_changes_do_not_change_completed_trades(self):
        values = list(randomized(88, 250))
        baseline = run_intraday_backtest(*values[:8], use_jit=False)
        values[5] = values[5].copy()
        values[5][150:] = ~values[5][150:]
        revised = run_intraday_backtest(*values[:8], use_jit=False)
        earlier_a = [t for t in baseline["trades"] if t["exit_index"] < 150]
        earlier_b = [t for t in revised["trades"] if t["exit_index"] < 150]
        self.assertEqual(earlier_a, earlier_b)

    def test_invalid_arrays_and_hard_limit_changes_rejected(self):
        args = ([0, 900], [1.1, 1.1], [1.101, 1.101], [1.099, 1.099],
                [1.1, 1.1], [True, False], .002, .003)
        for kwargs in ({"max_holding_days": 6}, {"max_holding_bars": 0},
                       {"costs": CostModel(carry_per_1000_per_day=.1)},
                       {"initial_equity": float("nan")}, {"end_index": 3},
                       {"quote_kind": "ask"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                run_intraday_backtest(*args, **kwargs)
        for index, replacement in ((0, [0, 0]), (1, [1.1]), (2, [1.101, float("nan")]),
                                   (5, [float("nan"), False])):
            modified = list(args)
            modified[index] = replacement
            with self.subTest(index=index), self.assertRaises(ValueError):
                run_intraday_backtest(*modified)

    def test_warmup_distance_nan_rejects_entry_and_empty_sample_is_flat(self):
        result = self.run_small([1.1, 1.1], [1.101, 1.101], [1.099, 1.099],
                                [1.1, 1.1], [True, False], stops=[np.nan, .002])
        self.assertEqual(result["summary"]["rejected_entries"], 1)
        self.assertEqual(result["summary"]["closed_trades"], 0)
        empty = run_intraday_backtest([], [], [], [], [], [], [], [], use_jit=False)
        self.assertEqual(empty["summary"]["ending_equity"], 100_000)
        self.assertEqual(empty["trades"], [])


class ObservedBookTests(unittest.TestCase):
    """BID/ASK fixtures are synthetic and never represent recorded profits."""

    def small(self, asks, **kwargs):
        n = len(asks)
        return run_intraday_backtest(
            np.arange(n) * 900, [1.1] * n, [1.1005] * n,
            [1.0995] * n, [1.1] * n, [True] + [False] * (n - 1),
            .002, .003, quote_kind="bid", ask_opens=asks,
            max_holding_bars=1, use_jit=False, **kwargs)

    def test_observed_ask_purchase_bid_sale_and_cash_reconcile(self):
        result = self.small([1.1001, 1.1007, 1.105], book_source="synthetic synchronized quotes")
        trade = result["trades"][0]
        costs = CostModel()
        buy, sell = 1.10072, 1.09998
        self.assertAlmostEqual(trade["entry_fill"], buy)
        self.assertAlmostEqual(trade["exit_fill"], sell)
        self.assertAlmostEqual(trade["entry_bid"], 1.1)
        self.assertAlmostEqual(trade["entry_ask"], 1.1007)
        self.assertAlmostEqual(trade["exit_bid"], 1.1)
        self.assertAlmostEqual(trade["spread_at_entry"], .0007)
        self.assertEqual(trade["stop_price"], 1.098)
        self.assertIsNone(trade["entry_mid"])
        self.assertIsNone(trade["exit_mid"])
        fee = costs.commission(trade["units"] * buy) + costs.commission(trade["units"] * sell)
        net = trade["units"] * (sell - buy) - fee
        self.assertAlmostEqual(trade["net_pnl"], net)
        self.assertAlmostEqual(trade["cash_after_entry"], 100_000 - trade["units"] * buy - trade["entry_commission"])
        self.assertAlmostEqual(trade["cash_after_exit"], 100_000 + net)
        summary = result["summary"]
        self.assertEqual(summary["quote_model"], "observed_bid_ask_opens")
        self.assertEqual(summary["observed_book_source"], "synthetic synchronized quotes")
        self.assertAlmostEqual(summary["total_spread_cost"], trade["units"] * .0007)
        self.assertAlmostEqual(summary["total_slippage_cost"], trade["units"] * .00004)
        self.assertAlmostEqual(summary["bid_baseline_gross_profit"] - summary["total_spread_cost"] - summary["total_slippage_cost"] - summary["total_commission"], summary["net_profit"])

    def test_future_ask_spike_is_not_used_for_exit_or_previous_entry(self):
        baseline = self.small([1.1001, 1.1002, 1.1003])
        future_spike = self.small([1.1001, 1.1002, 100.0])
        self.assertEqual(baseline["trades"], future_spike["trades"])
        self.assertEqual(baseline["summary"]["net_profit"], future_spike["summary"]["net_profit"])

    def test_wide_observed_entry_spread_and_adverse_bid_gap_keep_actual_loss(self):
        result = run_intraday_backtest(
            [0, 900, 1800], [1.1, 1.1, 1.05], [1.101, 1.101, 1.052],
            [1.099, 1.099, 1.048], [1.1, 1.1, 1.05], [True, False, False],
            .002, .003, quote_kind="bid", ask_opens=[1.1001, 1.103, 1.15],
            use_jit=False)
        trade = result["trades"][0]
        self.assertEqual(trade["reason"], "stop_gap")
        self.assertAlmostEqual(trade["entry_fill"], 1.10302)
        self.assertAlmostEqual(trade["exit_fill"], 1.04998)
        self.assertAlmostEqual(trade["spread_at_entry"], .003)
        manual = trade["units"] * (1.04998 - 1.10302) - .2
        self.assertAlmostEqual(trade["net_pnl"], manual)
        self.assertLess(trade["net_pnl"], -30)
        self.assertFalse(trade["risk_breach"])

    def test_spread_stress_scales_actual_entry_book_and_preserves_bid_levels(self):
        base = self.small([1.1001, 1.1004, 1.1002])
        stressed = self.small([1.1001, 1.1004, 1.1002], observed_spread_multiplier=2)
        a, b = base["trades"][0], stressed["trades"][0]
        self.assertAlmostEqual(b["entry_ask"], 1.1004)
        self.assertAlmostEqual(b["spread_at_entry"], .0004)
        self.assertAlmostEqual(b["modeled_spread_at_entry"], .0008)
        self.assertAlmostEqual(b["entry_fill"], 1.10082)
        self.assertEqual(b["stop_price"], a["stop_price"])
        self.assertEqual(b["target_price"], a["target_price"])
        self.assertEqual(b["exit_fill"], a["exit_fill"])
        self.assertLess(b["net_pnl"], a["net_pnl"])
        self.assertEqual(stressed["summary"]["observed_spread_multiplier"], 2)

    def test_variable_spread_random_paths_match_production_cash_oracle(self):
        values = randomized(169, 900)
        times, op, hi, lo, cl, entries, stops, targets = values[:8]
        generator = np.random.default_rng(119)
        spread = generator.uniform(.00002, .0012, len(times))
        asks = op + spread
        actual = run_intraday_backtest(*values[:8], quote_kind="bid", ask_opens=asks,
                                      max_holding_bars=9, include_equity_curve=True,
                                      use_jit=False)
        equity = 100_000
        position = None
        entry_index = None
        half_spread = 0
        expected = []
        for i in range(len(times)):
            stamp = datetime.fromtimestamp(int(times[i]), timezone.utc)
            existed = position is not None
            if not existed and i > 0 and entries[i - 1]:
                # A per-position constant midpoint translation lets the
                # existing reference execute the exact observed entry ask
                # and later observed BID exits, without reading future asks.
                half_spread = spread[i] / 2
                costs = CostModel(spread_pips=spread[i] / .0001)
                plan = size_position(equity, op[i] + half_spread, stops[i - 1], costs=costs)
                position = open_long(plan, stamp, op[i] + half_spread + targets[i - 1])
                entry_index = i
            if position is not None:
                bar = Bar(stamp, op[i] + half_spread, hi[i] + half_spread,
                          lo[i] + half_spread, cl[i] + half_spread)
                gap = bar.open <= position.stop_price or bar.open >= position.target_price
                if not gap and i - entry_index >= 9:
                    trade = force_close(position, stamp, bar.open, "holding_bars")
                else:
                    trade = evaluate_long(position, bar)
                if trade is not None:
                    expected.append(trade)
                    equity += trade.net_pnl
                    position = None
        if position is not None:
            trade = force_close(position, stamp, cl[-1] + half_spread, "sample_end")
            expected.append(trade)
            equity += trade.net_pnl
        self.assertGreater(len(expected), 30)
        self.assertEqual(len(actual["trades"]), len(expected))
        for a, e in zip(actual["trades"], expected):
            self.assertEqual(a["units"], e.units)
            self.assertEqual(a["reason"], e.reason)
            for name in ("entry_fill", "exit_fill", "net_pnl", "entry_commission",
                         "exit_commission", "max_adverse_excursion", "max_drawdown"):
                self.assertAlmostEqual(a[name], getattr(e, name), delta=1e-7)
        self.assertAlmostEqual(actual["summary"]["ending_equity"], equity, delta=1e-7)
        if njit is not None:
            accelerated = run_intraday_backtest(*values[:8], quote_kind="bid", ask_opens=asks,
                                               max_holding_bars=9, use_jit=True)
            self.assertEqual(actual["trades"], accelerated["trades"])

    def test_invalid_ask_book_or_stress_inputs_rejected(self):
        for asks in ([1.1001], [1.1001, np.nan, 1.1002], [1.1001, 1.0999, 1.1002]):
            with self.subTest(asks=asks), self.assertRaises(ValueError):
                self.small(asks) if len(asks) != 1 else run_intraday_backtest(
                    [0, 900], [1.1] * 2, [1.101] * 2, [1.099] * 2,
                    [1.1] * 2, [True, False], .002, .003,
                    quote_kind="bid", ask_opens=asks)
        with self.assertRaises(ValueError):
            self.small([1.1001, 1.1002, 1.1003], observed_spread_multiplier=.5)
        with self.assertRaises(ValueError):
            run_intraday_backtest([0, 900], [1.1] * 2, [1.101] * 2,
                                  [1.099] * 2, [1.1] * 2, [True, False], .002, .003,
                                  ask_opens=[1.1001, 1.1002])


class NumericLotSizingTests(unittest.TestCase):
    """Synthetic contract-multiplier arithmetic; no futures risk proof."""

    def sample(self, price=7000.0, **kwargs):
        costs = kwargs.pop("costs", CostModel(pip_size=.25, spread_pips=2,
                                              slippage_pips=1))
        return run_intraday_backtest(
            [0, 900], [price] * 2, [price + 1] * 2, [price - 1] * 2,
            [price] * 2, [True, False], 10, 20, costs=costs,
            initial_equity=kwargs.pop("initial_equity", 5_000_000),
            unit_step=kwargs.pop("unit_step", 5), use_jit=False, **kwargs)

    def test_whole_five_unit_lot_manual_cash_and_pnl_oracle(self):
        result = self.sample()
        trade = result["trades"][0]
        self.assertEqual(trade["units"], 5)
        self.assertEqual(trade["trading_lots"], 1)
        self.assertAlmostEqual(trade["entry_fill"], 7000.5)
        self.assertAlmostEqual(trade["exit_fill"], 6999.5)
        buy_value, sale_value = 35002.5, 34997.5
        buy_fee, sale_fee = buy_value * .000035, sale_value * .000035
        self.assertAlmostEqual(trade["entry_notional"], buy_value)
        self.assertAlmostEqual(trade["cash_after_entry"], 5_000_000 - buy_value - buy_fee)
        self.assertAlmostEqual(trade["cash_after_exit"], 5_000_000 - buy_value - buy_fee + sale_value - sale_fee)
        self.assertAlmostEqual(trade["gross_pnl"], -5)
        self.assertAlmostEqual(trade["net_pnl"], -7.45)
        self.assertAlmostEqual(trade["worst_case_loss"], buy_value + buy_fee + .1)
        self.assertEqual(result["summary"]["unit_step"], 5)
        self.assertFalse(result["summary"]["derivative_variation_margin_bound_established"])

    def test_larger_lot_or_fill_over_cap_is_rejected(self):
        for kwargs in ({"unit_step": 10}, {"price": 7999.75}):
            with self.subTest(kwargs=kwargs):
                result = self.sample(**kwargs)
                self.assertEqual(result["summary"]["closed_trades"], 0)
                self.assertEqual(result["summary"]["rejected_entries"], 1)
                self.assertEqual(result["summary"]["ending_equity"], 5_000_000)
        # Exactly 40,000 of paid exposure is allowed; half-point fill costs
        # must be included before quantity is rounded to a whole lot.
        allowed = self.sample(price=7999.5)
        self.assertEqual(allowed["trades"][0]["units"], 5)
        self.assertEqual(allowed["trades"][0]["entry_notional"], 40_000)

    def test_reserved_transaction_fees_can_remove_whole_lot_capacity(self):
        costs = CostModel(pip_size=.25, spread_pips=2, slippage_pips=1,
                          minimum_commission=5000)
        result = self.sample(initial_equity=4_500_000, costs=costs)
        # Purchase alone fits the 36,000 notional cap, but full purchase loss
        # plus both minimum fees would exceed the 45,000 loss budget.
        self.assertEqual(result["summary"]["closed_trades"], 0)
        self.assertEqual(result["summary"]["rejected_entries"], 1)

    def test_invalid_lot_step_rejected(self):
        for value in (0, -5, 1.5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.sample(unit_step=value)

    def test_quantity_steps_match_production_oracle_and_jit(self):
        values = list(randomized(197, 600))
        for index in (1, 2, 3, 4, 6, 7):
            values[index] = values[index] * (7000 / 1.12)
        costs = CostModel(pip_size=.25, spread_pips=2, slippage_pips=1)
        checker = IntradayReferenceTests()
        python = checker.compare(values, costs=costs, max_bars=7,
                                 unit_step=5, initial=5_000_000)
        self.assertTrue(all(t["units"] % 5 == 0 for t in python["trades"]))
        if njit is not None:
            accelerated = checker.compare(values, costs=costs, max_bars=7,
                                          unit_step=5, initial=5_000_000, use_jit=True)
            self.assertEqual(python["trades"], accelerated["trades"])


if __name__ == "__main__":
    unittest.main()
