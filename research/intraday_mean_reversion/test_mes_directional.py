import unittest

import numpy as np
import pandas as pd

from .futures_mes_directional import causal_direction_signals, assert_directional_trade_integrity, run_split


class DirectionalCausalityTests(unittest.TestCase):
    def frame(self, down=False):
        count = 276
        values = np.arange(count) * .25 + np.sin(np.arange(count))
        close = 7000 - values if down else 7000 + values
        return pd.DataFrame({"time": pd.date_range("2026-01-20T23:00Z", periods=count, freq="5min"),
                             "open": close, "close": close})

    def config(self, style="momentum"):
        return {"horizon": 6, "ema_period": 48, "style": style,
                "stop_points": 8, "target_points": 8}

    def test_prefix_features_and_directions_do_not_use_future(self):
        frame = self.frame()
        original = causal_direction_signals(frame, self.config())
        shifted = frame.copy()
        shifted.loc[160:, "close"] += 5000
        changed = causal_direction_signals(shifted, self.config())
        for key in original:
            np.testing.assert_allclose(original[key][:160], changed[key][:160], equal_nan=True)

    def test_same_rule_generates_both_directions_symmetrically(self):
        up = causal_direction_signals(self.frame(), self.config())
        down = causal_direction_signals(self.frame(True), self.config())
        np.testing.assert_array_equal(up["direction_signals"], -down["direction_signals"])
        self.assertTrue((up["direction_signals"] == 1).any())
        self.assertTrue((down["direction_signals"] == -1).any())

    def test_bearish_pullback_requires_prior_rise_then_decline(self):
        arrays = causal_direction_signals(self.frame(True), self.config("pullback"))
        selected = arrays["direction_signals"] == -1
        self.assertTrue(selected.any())
        self.assertTrue((arrays["previous_change"][selected] > 0).all())
        self.assertTrue((arrays["current_change"][selected] < 0).all())
        self.assertTrue((arrays["ema_slope"][selected] < 0).all())

    def test_gap_resets_both_direction_warmups(self):
        frame = self.frame(True)
        frame.loc[120:, "time"] += pd.Timedelta(minutes=5)
        arrays = causal_direction_signals(frame, self.config())
        self.assertTrue(np.isnan(arrays["ema"][120:167]).all())
        self.assertFalse(arrays["direction_signals"][120:173].any())

    def test_march_rows_cannot_warm_up(self):
        frame = self.frame()
        frame["time"] += pd.Timedelta(days=50)
        with self.assertRaisesRegex(ValueError, "March"):
            causal_direction_signals(frame, self.config())

    def test_short_preserves_actual_positive_units_and_exact_fees(self):
        trade = {"units": 5, "contracts": 1, "direction": -1,
                 "entry_fill": 6999.5, "exit_fill": 6990.5,
                 "entry_commission": 2, "exit_commission": 2}
        assert_directional_trade_integrity([trade], "flat2_operating_assumption")
        for changed in [dict(trade, units=-5), dict(trade, contracts=2), dict(trade, exit_commission=1)]:
            with self.assertRaises(ValueError):
                assert_directional_trade_integrity([changed], "flat2_operating_assumption")

    def test_final_cannot_be_evaluated_by_development_entrypoint(self):
        with self.assertRaisesRegex(ValueError, "refuses final"):
            run_split(pd.DataFrame(), {}, {}, "", {}, "final")


if __name__ == "__main__":
    unittest.main()
