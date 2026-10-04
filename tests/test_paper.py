"""Synthetic QA fixtures only; no fixture is a real trade or market result."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from trading_agent.execution import Bar
from trading_agent.market import (MarketSnapshot, aggregate_bars, forex_is_open,
                                  next_weekly_open, parse_chart)
from trading_agent.paper import atomic_json, new_account, tick, update_account
from trading_agent.strategy import StrategyConfig


UTC = timezone.utc
NOW = datetime(2026, 1, 5, 9, 2, tzinfo=UTC)  # Synthetic Monday quotation.


def approved_fixture():
    """A synthetic gate result to isolate execution, never published evidence."""
    return {"paper_approved": True, "selection_eligible": True,
            "final_summary": {"eligible_trades": 30, "win_rate": .5,
                              "net_profit": 1, "risk_breaches": 0},
            "config": StrategyConfig().to_dict()}


def market_fixture(now=NOW, mid=1.1, quote_time=None, excluded_invalid=0):
    hour = now.replace(minute=0, second=0, microsecond=0)
    bars = [Bar(hour - timedelta(hours=1), 1.1, 1.101, 1.099, 1.1)]
    return MarketSnapshot(bars, mid, quote_time or now, now,
                          "https://synthetic.invalid/qa", excluded_invalid=excluded_invalid)


def signal_patches():
    return patch("trading_agent.paper.compute_features",
                 return_value=[{"atr": .01}]), patch("trading_agent.paper.entry_signal", return_value=True)


def open_fixture():
    features, signal = signal_patches()
    with features, signal:
        return update_account(new_account(NOW), approved_fixture(), market_fixture(), NOW)


class PaperLedgerTests(unittest.TestCase):
    def test_entry_and_exit_reconcile_all_cash_costs(self):
        account = open_fixture()
        plan = account["position"]["plan"]
        self.assertAlmostEqual(account["cash"], 100_000 - plan["notional"] - plan["entry_commission"])
        self.assertLessEqual(plan["worst_case_loss"], plan["entry_equity"] * .01)
        self.assertLess(account["equity"], 100_000)  # Immediate liquidation costs.
        later = NOW + timedelta(hours=1)
        account = update_account(account, approved_fixture(), market_fixture(later, mid=1.13), later)
        self.assertIsNone(account["position"])
        self.assertEqual(len(account["trades"]), 1)
        self.assertEqual(len(account["orders"]), 2)
        self.assertAlmostEqual(account["cash"], 100_000 + account["realized_pnl"])
        self.assertAlmostEqual(account["equity"], account["cash"])
        self.assertAlmostEqual(account["realized_pnl"], account["trades"][0]["net_pnl"])
        self.assertEqual(account["unrealized_pnl"], 0)
        self.assertTrue(all(order["mode"] == "paper" for order in account["orders"]))

    def test_one_position_and_repeated_tick_cannot_duplicate_order(self):
        account = open_fixture()
        cash = account["cash"]
        for now in (NOW, NOW + timedelta(minutes=1), NOW + timedelta(hours=1)):
            features, signal = signal_patches()
            with features, signal:
                update_account(account, approved_fixture(), market_fixture(now), now)
        self.assertEqual(len(account["orders"]), 1)
        self.assertEqual(len(account["trades"]), 0)
        self.assertEqual(account["cash"], cash)
        self.assertIsNotNone(account["position"])

    def test_stale_quote_neither_opens_nor_closes_position(self):
        stale = market_fixture(quote_time=NOW - timedelta(minutes=11))
        features, signal = signal_patches()
        with features, signal:
            empty = update_account(new_account(NOW), approved_fixture(), stale, NOW)
        self.assertEqual(empty["status"]["code"], "stale_market")
        self.assertEqual(empty["orders"], [])
        account = open_fixture()
        cash = account["cash"]
        later = NOW + timedelta(hours=1)
        stale = market_fixture(later, mid=.5, quote_time=later - timedelta(minutes=11))
        update_account(account, approved_fixture(), stale, later)
        self.assertIsNotNone(account["position"])
        self.assertEqual(account["cash"], cash)
        self.assertEqual(len(account["orders"]), 1)

    def test_independent_gate_rejects_each_missing_requirement(self):
        changes = [{"eligible_trades": 29}, {"win_rate": .4999},
                   {"net_profit": 0}, {"net_profit": -1}, {"risk_breaches": 1}]
        for changed in changes:
            with self.subTest(changed=changed):
                selected = approved_fixture()
                selected["final_summary"].update(changed)
                features, signal = signal_patches()
                with features, signal:
                    account = update_account(new_account(NOW), selected, market_fixture(), NOW)
                self.assertEqual(account["status"]["code"], "validation_failed")
                self.assertEqual(account["orders"], [])
        for field in ("selection_eligible", "paper_approved"):
            selected = approved_fixture()
            selected[field] = False
            features, signal = signal_patches()
            with features, signal:
                account = update_account(new_account(NOW), selected, market_fixture(), NOW)
            self.assertEqual(account["orders"], [])

    def test_invalid_historical_prices_block_new_positions(self):
        features, signal = signal_patches()
        with features, signal:
            account = update_account(new_account(NOW), approved_fixture(),
                                     market_fixture(excluded_invalid=1), NOW)
        self.assertEqual(account["status"]["code"], "invalid_market")
        self.assertEqual(account["orders"], [])

    def test_no_late_entry_and_no_same_bar_reentry_after_exit(self):
        late = NOW.replace(minute=11)
        features, signal = signal_patches()
        with features, signal:
            empty = update_account(new_account(late), approved_fixture(), market_fixture(late), late)
        self.assertEqual(empty["orders"], [])
        account = open_fixture()
        later = NOW + timedelta(hours=1)
        features, signal = signal_patches()
        with features, signal:
            update_account(account, approved_fixture(), market_fixture(later, mid=1.13), later)
            update_account(account, approved_fixture(), market_fixture(later, mid=1.13), later)
        self.assertIsNone(account["position"])
        self.assertEqual(len(account["orders"]), 2)

    def test_strategy_change_halts_new_orders(self):
        selected = approved_fixture()
        account = update_account(new_account(NOW), selected, market_fixture(), NOW)
        selected["config"]["rsi_entry"] = 10
        features, signal = signal_patches()
        with features, signal:
            account = update_account(account, selected, market_fixture(), NOW)
        self.assertEqual(account["status"]["code"], "risk_halted")
        self.assertEqual(account["orders"], [])

    def test_api_failure_preserves_existing_ledger_and_propagates(self):
        with TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            selected_path = Path(temporary) / "selected.json"
            selected_path.write_text(json.dumps(approved_fixture()))
            account = open_fixture()
            atomic_json(state / "account.json", account)

            def fail(_):
                raise OSError("synthetic QA network failure")

            with self.assertRaisesRegex(OSError, "synthetic QA"):
                tick(state, selected_path, fail, NOW)
            persisted = json.loads((state / "account.json").read_text())
            self.assertEqual(persisted["status"]["code"], "data_error")
            for field in ("cash", "position", "trades", "orders", "realized_pnl"):
                self.assertEqual(persisted[field], account[field])

    def test_exception_after_close_rolls_back_entire_financial_transition(self):
        # An invalid selected config raises after a valid exit has been evaluated.
        # Persisting only half of that transition would permit a duplicate sell.
        with TemporaryDirectory() as temporary:
            state = Path(temporary) / "state"
            selected_path = Path(temporary) / "selected.json"
            selected = approved_fixture()
            selected["config"]["synthetic_unknown_parameter"] = True
            selected_path.write_text(json.dumps(selected))
            account = open_fixture()
            before = deepcopy(account)
            atomic_json(state / "account.json", account)
            later = NOW + timedelta(hours=1)
            with self.assertRaises(TypeError):
                tick(state, selected_path, lambda _: market_fixture(later, mid=1.13), later)
            persisted = json.loads((state / "account.json").read_text())
            self.assertEqual(persisted["status"]["code"], "data_error")
            for field in ("cash", "equity", "position", "trades", "orders", "realized_pnl"):
                self.assertEqual(persisted[field], before[field], field)


class MarketContractTests(unittest.TestCase):
    def payload(self, stamps=None):
        hour = NOW.replace(minute=0, second=0, microsecond=0)
        stamps = stamps or [hour - timedelta(hours=1), hour]
        return {"chart": {"error": None, "result": [{
            "meta": {"dataGranularity": "1h", "symbol": "EURUSD=X",
                     "regularMarketTime": int(NOW.timestamp()), "regularMarketPrice": 1.1},
            "timestamp": [int(value.timestamp()) for value in stamps],
            "indicators": {"quote": [{"open": [1.1] * len(stamps), "high": [1.101] * len(stamps),
                                      "low": [1.099] * len(stamps), "close": [1.1] * len(stamps)}]}}]}}

    def test_completed_hourly_bars_only(self):
        snapshot = parse_chart(self.payload(), NOW, "https://synthetic.invalid/qa")
        self.assertEqual(len(snapshot.bars), 1)
        self.assertLessEqual(snapshot.bars[-1].time + timedelta(hours=1), NOW)

    def test_wrong_interval_symbol_and_future_quote_fail_closed(self):
        for field, value in (("dataGranularity", "1d"), ("symbol", "GBPUSD=X"),
                             ("regularMarketTime", int((NOW + timedelta(minutes=2)).timestamp()))):
            payload = self.payload()
            payload["chart"]["result"][0]["meta"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                parse_chart(payload, NOW, "https://synthetic.invalid/qa")

    def test_null_invalid_and_duplicate_bars_do_not_enter_features(self):
        stamps = [NOW.replace(minute=0) - timedelta(hours=i) for i in (3, 2, 1)]
        payload = self.payload(stamps)
        prices = payload["chart"]["result"][0]["indicators"]["quote"][0]
        prices["open"][0] = None
        prices["high"][1] = 1.0
        snapshot = parse_chart(payload, NOW, "https://synthetic.invalid/qa")
        self.assertEqual(len(snapshot.bars), 1)
        self.assertEqual(snapshot.excluded_null, 1)
        self.assertEqual(snapshot.excluded_invalid, 1)
        with self.assertRaises(ValueError):
            parse_chart(self.payload([stamps[0], stamps[0]]), NOW, "https://synthetic.invalid/qa")
        with self.assertRaises(ValueError):
            parse_chart(self.payload(list(reversed(stamps))), NOW, "https://synthetic.invalid/qa")

    def test_four_hour_aggregation_requires_all_consecutive_hours(self):
        start = NOW.replace(hour=4, minute=0)
        bars = [Bar(start + timedelta(hours=i), 1.1, 1.101, 1.099, 1.1) for i in range(4)]
        self.assertEqual(len(aggregate_bars(bars, 4)), 1)
        self.assertEqual(aggregate_bars(bars[:2] + bars[3:], 4), [])

    def test_forex_session_tracks_new_york_dst(self):
        winter_open = datetime(2026, 1, 4, 22, tzinfo=UTC)
        summer_open = datetime(2026, 7, 5, 21, tzinfo=UTC)
        for opening in (winter_open, summer_open):
            self.assertFalse(forex_is_open(opening - timedelta(seconds=1)))
            self.assertTrue(forex_is_open(opening))
            self.assertEqual(next_weekly_open(opening - timedelta(seconds=1)), opening)
        self.assertFalse(forex_is_open(datetime(2026, 1, 9, 22, tzinfo=UTC)))


if __name__ == "__main__":
    unittest.main()
