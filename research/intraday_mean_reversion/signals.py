"""Causal M15 Bollinger-band reversion hypotheses, separate from production.

These functions generate hypotheses, not approved trading instructions. Price
data through index i is allowed to signal only the open of index i + 1.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MeanReversionConfig:
    name: str
    window: int = 96
    threshold: float = 2.3
    confirmation: str = "rebound"
    stop_pips: float = 20.0
    target_pips: float = 20.0
    timeframe_minutes: int = 15
    pip_size: float = 0.0001
    max_holding_days: int = 5
    ema_period: int = 384
    atr_fast: int = 14
    atr_slow: int = 96
    max_atr_ratio: float = 2.0
    minimum_atr_pips: float = 1.0
    minimum_macro_slope_atr: float = -2.0
    maximum_macro_slope_atr: float = 4.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "MeanReversionConfig":
        return cls(**value)


def candidate_configs() -> list[MeanReversionConfig]:
    """24 declared tests, evaluated on both USD-quoted development sources."""
    return [
        MeanReversionConfig(
            name=f"bb{window}_z{threshold:g}_{confirmation}_stop{stop:g}_target{target:g}",
            window=window, threshold=threshold, confirmation=confirmation,
            stop_pips=stop, target_pips=target,
        )
        for window in (32, 96)
        for threshold in (1.8, 2.3)
        for confirmation in ("none", "rebound")
        for stop, target in ((20.0, 10.0), (20.0, 20.0), (30.0, 20.0))
    ]


def common_features(frame: pd.DataFrame, config: MeanReversionConfig) -> pd.DataFrame:
    """Compute rolling features from completed observations only.

    The old broker source has an unknown wall-clock timezone, so none of the
    hypotheses here use named trading sessions or hour-of-day assumptions.
    """
    close = frame["close"].astype(float)
    previous_close = close.shift(1)
    true_range = pd.concat([
        frame["high"] - frame["low"],
        (frame["high"] - previous_close).abs(),
        (frame["low"] - previous_close).abs(),
    ], axis=1).max(axis=1)
    atr_fast = true_range.ewm(alpha=1 / config.atr_fast, adjust=False,
                            min_periods=config.atr_fast).mean()
    atr_slow = true_range.ewm(alpha=1 / config.atr_slow, adjust=False,
                            min_periods=config.atr_slow).mean()
    ema = close.ewm(span=config.ema_period, adjust=False,
                    min_periods=config.ema_period).mean()
    slope = (ema - ema.shift(96)) / atr_slow
    mean = close.rolling(config.window, min_periods=config.window).mean()
    deviation = close.rolling(config.window, min_periods=config.window).std(ddof=0)
    zscore = (close - mean) / deviation.where(deviation > 0)
    ready = np.arange(len(frame)) >= config.ema_period * 3
    return pd.DataFrame({"close": close, "mean": mean, "deviation": deviation,
                         "zscore": zscore, "atr_fast": atr_fast,
                         "atr_slow": atr_slow, "macro_slope_atr": slope,
                         "ready": ready}, index=frame.index)


def signals_from_features(features: pd.DataFrame, config: MeanReversionConfig) -> dict[str, np.ndarray]:
    zscore = features["zscore"]
    if config.confirmation == "none":
        extreme = zscore <= -config.threshold
    elif config.confirmation == "rebound":
        # A completed candle must re-enter its band after an actual extreme.
        extreme = ((zscore.shift(1) <= -config.threshold)
                   & (zscore > -config.threshold)
                   & (features["close"] > features["close"].shift(1)))
    else:
        raise ValueError("Unknown confirmation rule")
    target_distance = config.target_pips * config.pip_size
    mean_gap = features["mean"] - features["close"]
    regime = ((features["atr_fast"] <= config.max_atr_ratio * features["atr_slow"])
              & (features["atr_fast"] >= config.minimum_atr_pips * config.pip_size)
              & features["macro_slope_atr"].between(config.minimum_macro_slope_atr,
                                                    config.maximum_macro_slope_atr))
    entry = (features["ready"] & extreme & regime & (mean_gap >= target_distance)).fillna(False)
    count = len(features)
    return {
        "entry_signals": entry.to_numpy(dtype=np.bool_),
        "stop_distances": np.full(count, config.stop_pips * config.pip_size, dtype=np.float64),
        "target_distances": np.full(count, target_distance, dtype=np.float64),
    }


def build_signals(frame: pd.DataFrame, config: MeanReversionConfig) -> dict[str, np.ndarray]:
    return signals_from_features(common_features(frame, config), config)
