import unittest

import numpy as np
import pandas as pd

from .futures_mes_momentum import (
    causal_signals, calendar, complete_session_source,
    execution_masks, assert_whole_contract_fees, run_split,
)


class MomentumCausalityTests(unittest.TestCase):
    def frame(self, start="2026-01-20T23:00Z", count=276):
        time = pd.date_range(start, periods=count, freq="5min")
        close = 7000 + np.arange(count) * .25 + np.sin(np.arange(count))
        return pd.DataFrame({"time": time, "open": close - .25, "close": close})

    def config(self, style="momentum"):
        return {"horizon": 6, "ema_period": 48, "style": style,
                "stop_points": 8, "target_points": 8}

    def test_future_suffix_does_not_change_prefix_features_or_signals(self):
        frame = self.frame()
        original = causal_signals(frame, self.config())
        changed = frame.copy()
        changed.loc[160:, ["open", "close"]] += 1000
        shifted = causal_signals(changed, self.config())
        for key in original:
            np.testing.assert_allclose(original[key][:160], shifted[key][:160], equal_nan=True)

    def test_gap_resets_all_warmup(self):
        frame = self.frame()
        frame.loc[120:, "time"] += pd.Timedelta(minutes=5)
        arrays = causal_signals(frame, self.config())
        self.assertTrue(np.isnan(arrays["ema"][120:167]).all())
        self.assertFalse(arrays["entry_signals"][120:173].any())

    def test_pullback_requires_prior_decline_then_recovery(self):
        frame = self.frame()
        arrays = causal_signals(frame, self.config("pullback"))
        selected = arrays["entry_signals"]
        self.assertTrue((arrays["previous_change"][selected] < 0).all())
        self.assertTrue((arrays["current_change"][selected] > 0).all())
        self.assertTrue((arrays["ema_slope"][selected] > 0).all())

    def test_complete_session_includes_previous_evening(self):
        frame = self.frame()
        complete, qa = complete_session_source(frame, "2026-01-21", "2026-01-22")
        self.assertEqual(qa["included_sessions"], 1)
        self.assertEqual(len(complete), 276)
        self.assertEqual(complete.time.iloc[0], pd.Timestamp("2026-01-20T23:00Z"))

    def test_missing_one_native_bar_excludes_session(self):
        frame = self.frame().drop(index=100).reset_index(drop=True)
        complete, qa = complete_session_source(frame, "2026-01-21", "2026-01-22")
        self.assertEqual(len(complete), 0)
        self.assertEqual(qa["incomplete_excluded"][0]["missing_expected_bars"], 1)

    def test_march_never_used_for_features(self):
        with self.assertRaisesRegex(ValueError, "March rows"):
            causal_signals(self.frame("2026-03-10T22:00Z"), self.config())

    def test_april_first_is_wholly_excluded_before_features(self):
        # Full native April1session includes March31UTC; protocol excludes the
        # complete April1session rather than permitting March warmup.
        frame = self.frame("2026-03-31T22:00Z")
        complete, qa = complete_session_source(frame, "2026-04-01", "2026-04-02")
        self.assertEqual(len(complete), 0)

    def test_flat_1640_signal_has_adjacent_1645_execution(self):
        frame = self.frame()
        masks = execution_masks(frame)
        slot = int(np.flatnonzero(masks["exit_signals"])[0])
        self.assertEqual(calendar(frame)["minutes"][slot], 16 * 60 + 40)
        self.assertEqual(calendar(frame)["minutes"][slot + 1], 16 * 60 + 45)
        broken = frame.drop(index=slot).reset_index(drop=True)
        with self.assertRaisesRegex(ValueError, "adjacent"):
            execution_masks(broken)

    def test_completed_signal_window_uses_availability_not_bar_start(self):
        time = pd.to_datetime(["2026-01-20T23:25Z", "2026-01-21T21:10Z", "2026-01-21T21:15Z"])
        cal = calendar(pd.DataFrame({"time": time}))
        self.assertEqual(cal["availability_minutes"].tolist(), [18 * 60 + 30, 16 * 60 + 15, 16 * 60 + 20])

    def test_flat_fee_requires_one_whole_contract_and_exact_two_dollars(self):
        base = {"units": 5, "trading_lots": 1, "entry_fill": 7000.5,
                "exit_fill": 7000., "entry_commission": 2, "exit_commission": 2}
        assert_whole_contract_fees([base], "flat2_operating_assumption")
        for mutated in [dict(base, units=10, trading_lots=2), dict(base, exit_commission=1.5)]:
            with self.assertRaises(ValueError):
                assert_whole_contract_fees([mutated], "flat2_operating_assumption")

    def test_final_entrypoint_refuses_outcomes(self):
        with self.assertRaisesRegex(ValueError, "never evaluates final"):
            run_split(pd.DataFrame(), {}, {}, "", {}, "final")


if __name__ == "__main__":
    unittest.main()
