import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone

from trading_agent.execution import Bar
from trading_agent.backtest import run_backtest
from trading_agent.strategy import StrategyConfig, candidate_configs, compute_features, entry_signal, trade_levels


class StrategyTests(unittest.TestCase):
    def bars(self, count=650):
        start = datetime(2020, 1, 1, tzinfo=timezone.utc)
        return [Bar(start + timedelta(hours=i), 1.1 + i * .00001,
                    1.101 + i * .00001, 1.099 + i * .00001, 1.1 + i * .00001)
                for i in range(count)]

    def test_features_never_change_when_future_bars_are_added(self):
        bars = self.bars()
        config = StrategyConfig()
        before = compute_features(bars[:625], config)
        bars[-1] = replace(bars[-1], open=100.0, high=101.0, low=99.0, close=100.0)
        after = compute_features(bars, config)
        self.assertEqual(before, after[:625])

    def test_warmup_and_oversold_trend_are_required(self):
        config = StrategyConfig()
        feature = {"ready": True, "close": 1.11, "ema": 1.1, "rsi": 4.0, "atr": .001}
        self.assertTrue(entry_signal(feature, config))
        for changed in ({"ready": False}, {"close": 1.09}, {"rsi": 6.0}, {"atr": .0001}):
            self.assertFalse(entry_signal({**feature, **changed}, config))

    def test_stop_and_target_depend_only_on_completed_atr(self):
        self.assertEqual(trade_levels({"atr": .001}, StrategyConfig()), (.002, .001))
        with self.assertRaises(ValueError):
            trade_levels({"atr": None}, StrategyConfig())

    def test_fixed_candidate_family_is_unique_and_roundtrips(self):
        configs = candidate_configs()
        self.assertEqual(len(configs), 24)
        self.assertEqual(len({config.name for config in configs}), 24)
        for config in configs:
            self.assertEqual(config, StrategyConfig.from_dict(config.to_dict()))

    def test_signal_enters_next_open_and_terminal_close_is_not_a_win(self):
        time = datetime(2020, 1, 1, tzinfo=timezone.utc)
        bars = [Bar(time, 1.1, 1.11, 1.09, 1.1),
                Bar(time + timedelta(hours=1), 1.12, 1.121, 1.119, 1.12),
                Bar(time + timedelta(hours=2), 1.12, 1.13, 1.119, 1.129)]
        config = StrategyConfig(stop_atr=2.0, target_atr=20.0)
        signal = {"ready": True, "close": 1.1, "ema": 1.09, "rsi": 1.0, "atr": .01}
        quiet = {**signal, "rsi": 99.0}
        result = run_backtest(bars, config, features=[signal, quiet, quiet])
        self.assertEqual(len(result["trades"]), 1)
        self.assertEqual(result["trades"][0]["entry_time"], bars[1].time.isoformat())
        self.assertEqual(result["trades"][0]["entry_mid"], 1.12)
        self.assertEqual(result["trades"][0]["reason"], "sample_end")
        self.assertGreater(result["summary"]["net_profit"], 0)
        self.assertEqual(result["summary"]["eligible_trades"], 0)
        self.assertEqual(result["summary"]["win_rate"], 0)


if __name__ == "__main__":
    unittest.main()
