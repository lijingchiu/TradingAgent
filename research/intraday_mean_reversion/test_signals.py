"""Synthetic fixtures check causality; they are never performance evidence."""

import unittest

import numpy as np
import pandas as pd

from .signals import (MeanReversionConfig, candidate_configs, common_features,
                      signals_from_features)
from .relative import (candidate_configs as relative_candidates,
                       relative_features, build_signals as relative_signals)


class SignalTests(unittest.TestCase):
    def test_future_price_shock_cannot_rewrite_completed_signals(self):
        generator = np.random.default_rng(174)
        close = 1.1 + np.cumsum(generator.normal(0, .0002, 1400))
        frame = pd.DataFrame({"open": close, "high": close + .0003,
                              "low": close - .0003, "close": close})
        config = candidate_configs()[0]
        previous = common_features(frame.iloc[:1250], config)
        frame.loc[1399, ["open", "high", "low", "close"]] = [100, 101, 99, 100]
        after = common_features(frame, config)
        pd.testing.assert_frame_equal(previous, after.iloc[:1250])
        left = signals_from_features(previous, config)
        right = signals_from_features(after, config)
        for key in left:
            np.testing.assert_array_equal(left[key], right[key][:1250])

    def test_rebound_waits_for_a_completed_reentry_candle(self):
        config = MeanReversionConfig("fixture", threshold=1.8, target_pips=10)
        features = pd.DataFrame({"close": [1.101, 1.1, 1.1002], "mean": [1.104] * 3,
                                "zscore": [-1.0, -2.1, -1.7], "atr_fast": [.0003] * 3,
                                "atr_slow": [.0003] * 3, "macro_slope_atr": [0.] * 3,
                                "ready": [True] * 3})
        signals = signals_from_features(features, config)["entry_signals"]
        self.assertEqual(signals.tolist(), [False, False, True])

    def test_target_gap_and_shock_filter_are_actual_requirements(self):
        config = MeanReversionConfig("fixture", confirmation="none", threshold=1.8)
        features = pd.DataFrame({"close": [1.1] * 3, "mean": [1.104, 1.101, 1.104],
                                "zscore": [-2.5] * 3, "atr_fast": [.0003, .0003, .002],
                                "atr_slow": [.0003] * 3, "macro_slope_atr": [0.] * 3,
                                "ready": [True] * 3})
        self.assertEqual(signals_from_features(features, config)["entry_signals"].tolist(),
                         [True, False, False])

    def test_family_is_exactly_the_predeclared_unique_24(self):
        family = candidate_configs()
        self.assertEqual(len(family), 24)
        self.assertEqual(len({config.name for config in family}), 24)
        for config in family:
            self.assertEqual(config, MeanReversionConfig.from_dict(config.to_dict()))

    def test_peer_future_shock_cannot_rewrite_relative_signals(self):
        generator = np.random.default_rng(275)
        close = 1.1 + np.cumsum(generator.normal(0, .0002, 1400))
        peer = 1.3 + np.cumsum(generator.normal(0, .0003, 1400))
        frame = pd.DataFrame({"open": close, "high": close + .0003,
                              "low": close - .0003, "close": close, "other_close": peer})
        config = relative_candidates()[0]
        previous = relative_features(frame.iloc[:1250], config.window)
        frame.loc[1399, "other_close"] = 100.
        after = relative_features(frame, config.window)
        pd.testing.assert_frame_equal(previous, after.iloc[:1250])
        left, right = relative_signals(previous, config), relative_signals(after, config)
        for before, added in zip(left, right):
            np.testing.assert_array_equal(before, added[:1250])

    def test_relative_family_is_predeclared_unique_32_per_currency(self):
        family = relative_candidates()
        self.assertEqual(len(family), 32)
        self.assertEqual(len({config.name for config in family}), 32)


if __name__ == "__main__":
    unittest.main()
