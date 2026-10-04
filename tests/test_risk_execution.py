"""Synthetic fixtures test fill/risk semantics; they are not market evidence."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
import unittest

from trading_agent.execution import Bar, evaluate_long, force_close, open_long
from trading_agent.risk import CostModel, RiskConfig, size_position


BASE_TIME = datetime(2026, 1, 5, 9, tzinfo=timezone.utc)


class FundingRiskTests(unittest.TestCase):
    def test_catastrophic_zero_value_and_outage_remain_funded(self):
        plan = size_position(100_000, 1.10, 0.01)
        position = open_long(plan, BASE_TIME, 1.12)
        # A stop cannot guarantee its price through a gap. Complete asset loss
        # even 500 days later is still inside the *entry-equity* funding budget.
        bar = Bar(BASE_TIME + timedelta(days=500), 0, 0, 0, 0)
        trade = evaluate_long(position, bar)
        self.assertEqual(trade.reason, "stop_gap")
        self.assertEqual(trade.exit_fill, 0)
        self.assertAlmostEqual(-trade.net_pnl, plan.worst_case_loss)
        self.assertLessEqual(-trade.net_pnl, 1000)
        self.assertFalse(trade.risk_breach)

    def test_all_prices_and_equity_scales_keep_hard_cap(self):
        for equity in (50, 100, 1000, 100_000, 12_345_678):
            for price in (0.001, 0.3, 1.1, 150):
                with self.subTest(equity=equity, price=price):
                    try:
                        plan = size_position(equity, price, price / 10)
                    except ValueError:
                        self.assertTrue(
                            equity * 0.008 < price + 0.00012
                            or equity * .01 < price + 0.00012 + .20
                        )
                        continue
                    self.assertIsInstance(plan.units, int)
                    self.assertLessEqual(plan.notional, equity * 0.008 + 1e-8)
                    self.assertLessEqual(plan.worst_case_loss, equity * 0.01 + 1e-8)
                    self.assertLessEqual(plan.notional + plan.entry_commission, equity)

    def test_hard_limits_cannot_be_increased(self):
        for kwargs in ({"max_loss_fraction": 0.010001},
                       {"max_notional_fraction": 0.008001},
                       {"max_holding_days": 6}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                RiskConfig(**kwargs)

    def test_invalid_inputs_and_unfundable_fees_rejected(self):
        for args in ((0, 1, .1), (1000, 0, .1), (1000, 1, 1),
                     (float("nan"), 1, .1), (1000, 1, -.1)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                size_position(*args)
        with self.assertRaises(ValueError):
            size_position(100, 1.1, .01, costs=CostModel(minimum_commission=5))
        with self.assertRaises(ValueError):
            CostModel(commission_bps=10_000)

    def test_tampered_funding_plan_is_rejected(self):
        plan = size_position(100_000, 1.1, .01)
        for tampered in (replace(plan, units=100_000),
                         replace(plan, entry_commission=0),
                         replace(plan, risk_budget=100_000)):
            with self.subTest(plan=tampered), self.assertRaises(ValueError):
                open_long(tampered, BASE_TIME, 1.12)

    def test_nonzero_carry_stress_sizing_cannot_enable_trading(self):
        plan = size_position(100_000, 1.1, .01,
                             costs=CostModel(carry_per_1000_per_day=.1))
        self.assertGreater(plan.reserved_carry, 0)
        self.assertLessEqual(plan.worst_case_loss, 1000)
        with self.assertRaisesRegex(ValueError, "zero ongoing carry"):
            open_long(plan, BASE_TIME, 1.12)


class PaperFillTests(unittest.TestCase):
    def position(self, stop_distance=.01, target=1.12):
        plan = size_position(100_000, 1.1, stop_distance)
        return open_long(plan, BASE_TIME, target,
                         signal_time=BASE_TIME - timedelta(hours=1))

    def test_entry_must_follow_signal_bar(self):
        plan = size_position(100_000, 1.1, .01)
        with self.assertRaisesRegex(ValueError, "after"):
            open_long(plan, BASE_TIME, 1.12, signal_time=BASE_TIME)
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            open_long(plan, BASE_TIME.replace(tzinfo=None), 1.12)

    def test_same_bar_stop_and_target_resolves_to_stop(self):
        position = self.position()
        trade = evaluate_long(position, Bar(BASE_TIME, 1.1, 1.13, 1.08, 1.11))
        self.assertEqual(trade.reason, "stop")
        self.assertAlmostEqual(trade.exit_mid, 1.09)
        self.assertLess(trade.net_pnl, 0)
        # Lows below the assumed stop fill occurred after exit in this path.
        self.assertAlmostEqual(trade.max_adverse_excursion, -trade.net_pnl)

    def test_stop_gap_fills_observed_open_not_stop(self):
        position = self.position()
        bar = Bar(BASE_TIME + timedelta(hours=1), 1.05, 1.08, 1.04, 1.07)
        trade = evaluate_long(position, bar)
        self.assertEqual(trade.reason, "stop_gap")
        self.assertEqual(trade.exit_mid, 1.05)
        self.assertLess(trade.exit_mid, position.stop_price)

    def test_fee_accounting_does_not_charge_spread_twice(self):
        position = self.position()
        trade = force_close(position, BASE_TIME, 1.1)
        self.assertAlmostEqual(trade.entry_fill, 1.10012)
        self.assertAlmostEqual(trade.exit_fill, 1.09988)
        expected = -position.units * .00024 - .20
        self.assertAlmostEqual(trade.net_pnl, expected)
        self.assertAlmostEqual(trade.gross_pnl - trade.total_fees, trade.net_pnl)
        self.assertEqual(trade.carry, 0)

    def test_expiry_uses_first_available_real_quote(self):
        position = self.position()
        time = BASE_TIME + timedelta(days=7)
        trade = evaluate_long(position, Bar(time, 1.105, 1.115, 1.1, 1.11))
        self.assertEqual(trade.reason, "expiry")
        self.assertEqual(trade.exit_time, time)
        self.assertEqual(trade.exit_mid, 1.105)
        self.assertEqual(trade.carry, 0)

    def test_duplicate_bar_and_double_close_are_rejected(self):
        position = self.position()
        bar = Bar(BASE_TIME, 1.1, 1.11, 1.095, 1.105)
        self.assertIsNone(evaluate_long(position, bar))
        with self.assertRaisesRegex(ValueError, "strictly"):
            evaluate_long(position, bar)
        force_close(position, BASE_TIME, 1.105)
        with self.assertRaisesRegex(ValueError, "already closed"):
            force_close(position, BASE_TIME, 1.105)

    def test_mae_includes_open_costs_and_intrabar_low(self):
        position = self.position()
        self.assertGreater(position.max_adverse_excursion, .2)
        bar = Bar(BASE_TIME, 1.1, 1.115, 1.095, 1.11)
        self.assertIsNone(evaluate_long(position, bar))
        trade = force_close(position, BASE_TIME, 1.11)
        self.assertGreater(trade.net_pnl, 0)
        self.assertGreater(trade.max_adverse_excursion, 3)
        self.assertGreater(trade.max_drawdown, trade.max_adverse_excursion)

    def test_drawdown_from_gains_is_distinct_from_entry_loss_budget(self):
        # A synthetic extreme demonstrates why a funding limit is not a
        # guarantee on peak-to-trough drawdown of accumulated paper gains.
        position = self.position(stop_distance=1, target=10_000)
        bar = Bar(BASE_TIME, 1.1, 100, .2, 1.1)
        self.assertIsNone(evaluate_long(position, bar))
        trade = force_close(position, BASE_TIME, 1.1)
        self.assertGreater(trade.max_drawdown, trade.risk_limit)
        self.assertLess(trade.max_adverse_excursion, trade.risk_limit)
        self.assertFalse(trade.risk_breach)

    def test_cost_changes_and_invalid_ohlc_rejected(self):
        position = self.position()
        with self.assertRaisesRegex(ValueError, "match"):
            force_close(position, BASE_TIME, 1.1, costs=CostModel(spread_pips=3))
        with self.assertRaisesRegex(ValueError, "inconsistent"):
            Bar(BASE_TIME, 1.1, 1.0, .9, 1.1)


if __name__ == "__main__":
    unittest.main()
