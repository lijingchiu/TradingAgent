import unittest

import numpy as np
import pandas as pd

from .directional import candidates, causal_signals, run_split, futures_api
from .momentum import complete_session_masks
from .study import CAPITAL, PROFILES


class NQDirectionalTests(unittest.TestCase):
    def frame(self, n=340):
        closes = 25_000 + np.sin(np.arange(n) / 10) * 15 + np.arange(n) * .1
        return pd.DataFrame({"time": pd.date_range("2026-01-21T00:00Z", periods=n, freq="5min"),
                             "close": closes, "open": closes - .25})

    def test_all_twenty_four_prefixes_match_full_history(self):
        frame = self.frame()
        for config in candidates():
            full = causal_signals(frame, config)
            prefix = causal_signals(frame.iloc[:260].copy(), config)
            for key in full:
                np.testing.assert_allclose(full[key][:260], prefix[key], equal_nan=True)

    def test_all_twenty_four_future_suffix_changes_do_not_change_history(self):
        frame = self.frame()
        changed = frame.copy()
        changed.loc[260:, "close"] += 1000
        for config in candidates():
            full, later = causal_signals(frame, config), causal_signals(changed, config)
            for key in full:
                np.testing.assert_allclose(full[key][:260], later[key][:260], equal_nan=True)

    def test_direction_rule_is_symmetric_and_not_chosen_from_future_prices(self):
        frame = self.frame()
        reflected = frame.copy()
        reflected["close"] = 50_000 - reflected["close"]
        for config in candidates():
            long_short = causal_signals(frame, config)["direction_signals"]
            opposite = causal_signals(reflected, config)["direction_signals"]
            np.testing.assert_array_equal(long_short, -opposite)
            self.assertTrue(set(long_short).issubset({-1, 0, 1}))

    def test_uptrend_momentum_long_downtrend_momentum_short(self):
        frame = self.frame(90)
        config = candidates()[0]
        frame["close"] = 25_000 + np.arange(90) * .25
        self.assertEqual(causal_signals(frame, config)["direction_signals"][-1], 1)
        frame["close"] = 25_000 - np.arange(90) * .25
        self.assertEqual(causal_signals(frame, config)["direction_signals"][-1], -1)

    def test_short_pullback_is_prior_bounce_then_completed_decline(self):
        frame = self.frame(100)
        frame["close"] = 25_000 - np.arange(100) * .25
        config = next(c for c in candidates() if c["style"] == "pullback")
        self.assertFalse(causal_signals(frame, config)["direction_signals"].any())
        frame.loc[97, "close"] = frame.loc[96, "close"] + .25
        result = causal_signals(frame, config)
        self.assertEqual(result["direction_signals"][97], 0)
        self.assertEqual(result["direction_signals"][98], -1)
        self.assertGreater(result["prior_one_bar_return"][98], 0)

    def test_segment_local_warmup_and_gap_reset(self):
        frame = self.frame(450)
        frame.loc[230:, "time"] += pd.Timedelta(minutes=5)
        for config in candidates():
            result = causal_signals(frame, config)
            warmup = config["ema_span"] + config["horizon"] - 1
            self.assertTrue(np.isnan(result["ema_slope"][:warmup]).all())
            self.assertTrue(np.isnan(result["ema_slope"][230:230 + warmup]).all())
            self.assertFalse(result["direction_signals"][230:230 + warmup].any())
            self.assertTrue(np.isfinite(result["ema_slope"][230 + warmup]))

    def test_partial_session_excluded_and_final_guard_without_loading_engine(self):
        frame = pd.DataFrame({"time": pd.date_range("2026-01-20T23:00Z", periods=276, freq="5min")})
        partial = frame.iloc[1:].reset_index(drop=True)
        self.assertFalse(complete_session_masks(partial, "2026-01-21", "2026-01-22")["entry_allowed"].any())
        with self.assertRaisesRegex(ValueError, "Final evaluation is not authorized"):
            run_split(pd.DataFrame(), candidates()[0], "final", "operating_fixed_5_per_side")

    def test_grid_is_exactly_twenty_four(self):
        self.assertEqual(len(candidates()), 24)
        self.assertEqual(len({c["name"] for c in candidates()}), 24)

    def test_short_signal_enters_next_open_raw_positive_price_directional_accounting(self):
        engine, summarize = futures_api()
        frame = self.frame(70)
        frame["close"] = 25_000 - np.arange(70) * .25
        frame["open"] = frame["close"] + .25
        signals = causal_signals(frame, candidates()[0])["direction_signals"]
        signals[54:] = 0
        self.assertEqual(signals[53], -1)
        op, cl = frame["open"].to_numpy(), frame["close"].to_numpy()
        times = (frame["time"].astype("int64") // 1_000_000_000).to_numpy()
        result = engine(times, op, op + .25, cl - .25, cl, signals, 40, 40,
                        contract_multiplier=20, initial_equity=CAPITAL,
                        costs=PROFILES["operating_fixed_5_per_side"],
                        flat_fee_per_contract_per_side=5., max_holding_bars=1,
                        max_signal_age_seconds=300)
        self.assertEqual(len(result["trades"]), 1)
        trade = result["trades"][0]
        self.assertEqual(trade["direction"], -1)
        self.assertEqual(trade["entry_index"], 54)
        self.assertEqual(trade["entry_quote"], op[54])
        self.assertGreater(trade["entry_quote"], 0)
        self.assertEqual(trade["units"], 20)
        self.assertEqual(trade["contracts"], 1)
        self.assertEqual(trade["entry_fill"], op[54] - .5)
        self.assertEqual(trade["exit_index"], 55)
        self.assertEqual(trade["exit_fill"], op[55] + .5)
        self.assertEqual(trade["total_fees"], 10)
        self.assertEqual(trade["net_pnl"], 20 * (trade["entry_fill"] - trade["exit_fill"]) - 10)
        stats = summarize(result["trades"])
        self.assertEqual(stats["net_profit"], trade["net_pnl"])
        self.assertAlmostEqual(result["summary"]["ending_equity"] - CAPITAL, trade["net_pnl"])


if __name__ == "__main__":
    unittest.main()
