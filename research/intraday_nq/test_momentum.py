import unittest

import numpy as np
import pandas as pd

from .momentum import candidates, causal_signals, run_split, complete_session_masks
from .study import session_arrays, assert_daily_flat_coverage
from .study import CAPITAL, PROFILES
from research.intraday_engine import run_intraday_backtest


class NQMomentumTests(unittest.TestCase):
    def frame(self, n=340):
        closes = 25_000 + np.arange(n) * .25 + np.sin(np.arange(n) / 3)
        return pd.DataFrame({"time": pd.date_range("2026-01-21T00:00Z", periods=n, freq="5min"),
                             "close": closes, "open": closes - .25})

    def test_future_suffix_does_not_change_any_completed_feature(self):
        frame = self.frame()
        for config in candidates():
            before = causal_signals(frame, config)
            changed = frame.copy()
            changed.loc[250:, "close"] -= 1000
            after = causal_signals(changed, config)
            for key in before:
                np.testing.assert_allclose(before[key][:250], after[key][:250], equal_nan=True)

    def test_every_candidate_prefix_matches_full_history(self):
        frame = self.frame()
        for config in candidates():
            full = causal_signals(frame, config)
            prefix = causal_signals(frame.iloc[:260].copy(), config)
            for key in full:
                np.testing.assert_allclose(full[key][:260], prefix[key], equal_nan=True)

    def test_ema_slope_exact_warmup_resets_after_gap(self):
        frame = self.frame(450)
        frame.loc[230:, "time"] += pd.Timedelta(minutes=5)
        for config in candidates():
            result = causal_signals(frame, config)
            warmup = config["ema_span"] + config["return_horizon"] - 1
            self.assertTrue(np.isnan(result["ema_slope"][:warmup]).all())
            self.assertTrue(np.isnan(result["ema_slope"][230:230 + warmup]).all())
            self.assertFalse(result["entry_signals"][230:230 + warmup].any())
            self.assertTrue(np.isfinite(result["ema_slope"][230 + warmup]))

    def test_momentum_requires_positive_slope_and_above_ema(self):
        frame = self.frame(90)
        frame["close"] = 25_000 - np.arange(90) * .25
        config = candidates()[0]
        result = causal_signals(frame, config)
        self.assertFalse(result["entry_signals"].any())
        frame["close"] = 25_000 + np.arange(90) * .25
        result = causal_signals(frame, config)
        self.assertTrue(result["entry_signals"][-1])

    def test_pullback_prior_one_bar_negative_then_completed_rebound(self):
        frame = self.frame(100)
        frame["close"] = 25_000 + np.arange(100) * .25
        config = next(c for c in candidates() if c["entry_style"] == "bullish_trend_pullback")
        self.assertFalse(causal_signals(frame, config)["entry_signals"].any())
        frame.loc[97, "close"] = frame.loc[96, "close"] - .25
        result = causal_signals(frame, config)
        self.assertFalse(result["entry_signals"][97])
        self.assertTrue(result["entry_signals"][98])
        self.assertLess(result["prior_one_bar_return"][98], 0)

    def test_calendar_flat_holidays_march_and_new_york_dst(self):
        frame = pd.DataFrame({"time": pd.to_datetime([
            "2026-02-15T23:30Z", "2026-03-10T14:00Z", "2026-04-02T22:30Z",
            "2026-04-06T20:15Z", "2026-04-06T20:40Z", "2026-04-06T20:45Z",
            "2026-04-15T22:30Z"])})
        masks = session_arrays(frame, "2026-01-01", "2026-04-16")
        self.assertEqual(masks["entry_allowed"].tolist(), [False, False, False, True, False, False, False])
        self.assertTrue(masks["exit_signals"][4])

    def test_missing_daily_flat_and_final_are_blocked(self):
        frame = pd.DataFrame({"time": pd.to_datetime(["2026-01-21T21:40Z"])})
        with self.assertRaisesRegex(ValueError, "Missing mandatory daily-flat"):
            assert_daily_flat_coverage(session_arrays(frame, "2026-01-21", "2026-01-22"))
        with self.assertRaisesRegex(ValueError, "Final evaluation is not authorized"):
            run_split(pd.DataFrame(), candidates()[0], "final", "operating_fixed_5_per_side")

    def test_full_native_session_required_even_when_daily_flat_quotes_exist(self):
        frame = pd.DataFrame({"time": pd.date_range("2026-01-20T23:00Z", periods=276, freq="5min")})
        masks = complete_session_masks(frame, "2026-01-21", "2026-01-22")
        self.assertTrue(masks["valid_dates"].all())
        partial = frame.iloc[1:].reset_index(drop=True)
        masks = complete_session_masks(partial, "2026-01-21", "2026-01-22")
        self.assertFalse(masks["entry_allowed"].any())
        self.assertFalse(masks["valid_dates"].any())

    def test_april_first_is_incomplete_after_literal_march_removal(self):
        frame = pd.DataFrame({"time": pd.date_range("2026-03-31T22:00Z", periods=276, freq="5min")})
        frame = frame.loc[frame["time"].dt.month != 3].reset_index(drop=True)
        masks = complete_session_masks(frame, "2026-04-01", "2026-04-02")
        self.assertFalse(masks["entry_allowed"].any())

    def test_grid_fixed_to_twenty_four(self):
        self.assertEqual(len(candidates()), 24)
        self.assertEqual(len({c["name"] for c in candidates()}), 24)

    def test_completed_momentum_signal_enters_next_open_with_one_contract_fees(self):
        frame = self.frame(70)
        frame["close"] = 25_000 + np.arange(70) * .25
        frame["open"] = frame["close"] - .25
        signal = causal_signals(frame, candidates()[0])["entry_signals"]
        signal[54:] = False
        self.assertTrue(signal[53])
        op, cl = frame["open"].to_numpy(), frame["close"].to_numpy()
        times = (frame["time"].astype("int64") // 1_000_000_000).to_numpy()
        run = run_intraday_backtest(times, op, cl + .25, op - .25, cl,
                                   signal, 40, 40, max_holding_bars=1,
                                   initial_equity=CAPITAL, unit_step=20,
                                   costs=PROFILES["operating_fixed_5_per_side"],
                                   max_signal_age_seconds=300)
        self.assertEqual(len(run["trades"]), 1)
        trade = run["trades"][0]
        self.assertEqual(trade["entry_index"], 54)
        self.assertEqual(trade["entry_time"], times[54])
        self.assertEqual(trade["entry_fill"], op[54] + .5)
        self.assertEqual(trade["exit_index"], 55)
        self.assertEqual(trade["trading_lots"], 1)
        self.assertEqual(trade["total_fees"], 10)


if __name__ == "__main__":
    unittest.main()
