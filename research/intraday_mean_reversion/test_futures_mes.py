import unittest

import numpy as np
import pandas as pd

from .futures_mes import causal_signals, session_arrays, assert_scheduled_close_coverage, run_split


class FuturesResearchCausalityTests(unittest.TestCase):
    def test_future_suffix_does_not_change_signals(self):
        n = 180
        values = 7000 + np.sin(np.arange(n) / 3) * 5
        frame = pd.DataFrame({"open": values - .25, "close": values})
        config = {"window": 6, "z_threshold": 1., "regime": "above_ema96",
                  "stop_points": 4., "target_points": 4.}
        original = causal_signals(frame, config)
        changed = frame.copy()
        changed.loc[140:, ["open", "close"]] += 2000
        shifted = causal_signals(changed, config)
        for key in original:
            np.testing.assert_allclose(original[key][:140], shifted[key][:140], equal_nan=True)

    def test_globex_date_and_no_entry_near_daily_flat(self):
        times = pd.to_datetime(["2026-01-21T21:35Z", "2026-01-21T21:45Z",
                                "2026-01-21T21:50Z", "2026-01-21T23:05Z"])
        masks = session_arrays(pd.DataFrame({"time": times}), "2026-01-21", "2026-01-23")
        self.assertEqual(masks["entry_allowed"].tolist(), [True, False, False, True])
        self.assertEqual(masks["exit_signals"].tolist(), [False, True, False, False])
        self.assertEqual(masks["session_dates"].iloc[-1], pd.Timestamp("2026-01-22"))

    def test_known_short_holiday_and_march_excluded(self):
        times = pd.to_datetime(["2026-02-15T23:05Z", "2026-03-10T14:00Z",
                                "2026-04-02T22:05Z", "2026-04-06T22:05Z"])
        masks = session_arrays(pd.DataFrame({"time": times}), "2026-01-01", "2026-05-01")
        self.assertEqual(masks["entry_allowed"].tolist(), [False, False, False, True])

    def test_missing_daily_flat_quote_blocks_study(self):
        frame = pd.DataFrame({"time": pd.to_datetime(["2026-01-21T14:00Z"] )})
        masks = session_arrays(frame, "2026-01-21", "2026-01-22")
        with self.assertRaisesRegex(ValueError, "Missing scheduled daily-flat"):
            assert_scheduled_close_coverage(frame, masks)

    def test_missing_completed_exit_signal_blocks_present_close_quote(self):
        frame = pd.DataFrame({"time": pd.to_datetime(["2026-01-21T21:40Z", "2026-01-21T21:50Z"])})
        masks = session_arrays(frame, "2026-01-21", "2026-01-22")
        with self.assertRaisesRegex(ValueError, "Missing scheduled daily-flat"):
            assert_scheduled_close_coverage(frame, masks)

    def test_adjacent_completed_signal_and_execution_quote_pass(self):
        frame = pd.DataFrame({"time": pd.to_datetime(["2026-01-21T21:45Z", "2026-01-21T21:50Z"])})
        masks = session_arrays(frame, "2026-01-21", "2026-01-22")
        assert_scheduled_close_coverage(frame, masks)

    def test_development_entrypoint_refuses_final_evaluation(self):
        with self.assertRaisesRegex(ValueError, "does not evaluate final"):
            run_split(pd.DataFrame(), {}, "final")


if __name__ == "__main__":
    unittest.main()
