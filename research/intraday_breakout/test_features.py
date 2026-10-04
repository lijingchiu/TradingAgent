"""Research feature validation: future data must not change earlier signals."""

import json
from pathlib import Path
import unittest

import numpy as np

from research.intraday_breakout.features import common_features, candidate_signals


class CausalityChecks(unittest.TestCase):
    def test_future_prices_do_not_change_prefix_signals(self):
        rng = np.random.default_rng(76213)
        close = 1.1 + np.cumsum(rng.normal(0, 0.0005, 1200))
        opening = close + rng.normal(0, 0.0003, 1200)
        high = np.maximum(opening, close) + rng.uniform(0.0001, 0.001, 1200)
        low = np.minimum(opening, close) - rng.uniform(0.0001, 0.001, 1200)
        root = Path(__file__).resolve().parents[2]
        configs = json.loads((root / "artifacts/intraday/breakout/preregistration.json").read_text())["candidates"]
        original = common_features(opening, high, low, close)
        altered = [array.copy() for array in (opening, high, low, close)]
        for array in altered:
            array[800:] *= 1.2
        changed = common_features(*altered)
        prefix = common_features(opening[:800], high[:800], low[:800], close[:800])
        for config in configs:
            signals = candidate_signals(original, config)
            np.testing.assert_array_equal(signals[:800], candidate_signals(changed, config)[:800])
            np.testing.assert_array_equal(signals[:800], candidate_signals(prefix, config))
            self.assertFalse(np.any(signals[:576]))


if __name__ == "__main__":
    unittest.main()
