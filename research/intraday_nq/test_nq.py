import unittest

import numpy as np
import pandas as pd

from .study import (candidates, causal_signals, session_arrays,
                    assert_daily_flat_coverage, run_split)


class NQCausalityTests(unittest.TestCase):
    def frame(self, n=220):
        closes = 25_000 + np.sin(np.arange(n) / 3) * 15
        return pd.DataFrame({"time": pd.date_range("2026-01-21T00:00Z", periods=n, freq="5min"),
                             "open": closes - .25, "close": closes})

    def test_future_suffix_cannot_change_prior_features_or_signals(self):
        frame = self.frame()
        config = candidates()[0]
        original = causal_signals(frame, config)
        changed = frame.copy()
        changed.loc[150:, ["open", "close"]] += 1000
        later = causal_signals(changed, config)
        for key in original:
            np.testing.assert_allclose(original[key][:150], later[key][:150], equal_nan=True)

    def test_dip_feature_excludes_rebound_and_dip_itself(self):
        frame = self.frame()
        config = candidates()[0]
        before = causal_signals(frame, config)
        frame.loc[120, "close"] += 500
        after = causal_signals(frame, config)
        self.assertEqual(before["prior_dip_z"][120], after["prior_dip_z"][120])
        self.assertEqual(before["prior_ema96"][120], after["prior_ema96"][120])

    def test_all_features_reset_and_rewarm_after_missing_bar(self):
        frame = self.frame()
        frame.loc[110:, "time"] += pd.Timedelta(minutes=5)
        result = causal_signals(frame, candidates()[0])
        self.assertTrue(np.isnan(result["prior_ema96"][110:207]).all())
        self.assertFalse(result["entry_signals"][110:207].any())
        self.assertTrue(np.isfinite(result["prior_ema96"][207]))

    def test_confirmed_rebound_uses_prior_dip(self):
        frame = self.frame(105)
        frame.loc[:99, "close"] = 25_000 + (np.arange(100) % 2) * .25
        frame.loc[:99, "open"] = frame.loc[:99, "close"]
        frame.loc[100, ["open", "close"]] = [25_000, 24_990]
        frame.loc[101, ["open", "close"]] = [24_990, 24_995]
        result = causal_signals(frame, candidates()[0])
        self.assertFalse(result["entry_signals"][100])
        self.assertTrue(result["entry_signals"][101])

    def test_native_globex_session_date_and_daily_flat_clock(self):
        frame = pd.DataFrame({"time": pd.to_datetime([
            "2026-01-21T21:15Z", "2026-01-21T21:20Z", "2026-01-21T21:40Z",
            "2026-01-21T21:45Z", "2026-01-21T23:25Z", "2026-01-21T23:30Z"])})
        masks = session_arrays(frame, "2026-01-21", "2026-01-23")
        self.assertEqual(masks["entry_allowed"].tolist(), [True, False, False, False, False, True])
        self.assertEqual(masks["exit_signals"].tolist(), [False, False, True, False, False, False])
        self.assertEqual(masks["session_dates"].iloc[-1], pd.Timestamp("2026-01-22"))

    def test_known_holidays_march_and_final_evening_excluded(self):
        frame = pd.DataFrame({"time": pd.to_datetime([
            "2026-02-15T23:30Z", "2026-03-10T14:00Z",
            "2026-04-02T22:30Z", "2026-04-15T22:30Z"])})
        masks = session_arrays(frame, "2026-01-01", "2026-04-16")
        self.assertEqual(masks["entry_allowed"].tolist(), [False, False, False, False])

    def test_missing_daily_flat_reference_blocks_study(self):
        frame = pd.DataFrame({"time": pd.to_datetime(["2026-01-21T21:40Z"])})
        with self.assertRaisesRegex(ValueError, "Missing mandatory daily-flat"):
            assert_daily_flat_coverage(session_arrays(frame, "2026-01-21", "2026-01-22"))

    def test_final_is_explicitly_not_evaluable(self):
        with self.assertRaisesRegex(ValueError, "Final evaluation is not authorized"):
            run_split(pd.DataFrame(), candidates()[0], "final")

    def test_registered_candidate_grid_is_exactly_twenty_four(self):
        grid = candidates()
        self.assertEqual(len(grid), 24)
        self.assertEqual(len({c["name"] for c in grid}), 24)


if __name__ == "__main__":
    unittest.main()
