"""Preregistered causal trend and breakout features for independent research.

Every output at i reads OHLC at i or earlier. The shared execution engine
consumes signals at i only when executing at i + 1. There are no session rules
for mirrors whose timestamp timezone is undocumented.
"""

from __future__ import annotations

import numpy as np


def lag(values: np.ndarray, bars: int = 1) -> np.ndarray:
    result = np.full(len(values), np.nan, dtype=float)
    result[bars:] = values[:-bars]
    return result


def ema(values: np.ndarray, span: int) -> np.ndarray:
    result = np.empty(len(values), dtype=float)
    alpha = 2.0 / (span + 1)
    if not len(values):
        return result
    result[0] = values[0]
    for i in range(1, len(values)):
        result[i] = alpha * values[i] + (1.0 - alpha) * result[i - 1]
    return result


def rolling(values: np.ndarray, bars: int, operation: str) -> np.ndarray:
    result = np.full(len(values), np.nan, dtype=float)
    if len(values) >= bars:
        view = np.lib.stride_tricks.sliding_window_view(values, bars)
        function = {"max": np.max, "min": np.min, "mean": np.mean}[operation]
        result[bars - 1:] = function(view, axis=1)
    return result


def common_features(opens, highs, lows, closes) -> dict[str, np.ndarray]:
    opens, highs, lows, closes = (np.asarray(v, dtype=float) for v in
                                  (opens, highs, lows, closes))
    previous = lag(closes)
    previous[0] = closes[0]
    true_range = np.maximum(highs - lows, np.maximum(abs(highs - previous), abs(lows - previous)))
    atr = rolling(true_range, 14, "mean")
    trend = ema(closes, 192)
    regime = (closes > trend) & (trend > lag(trend, 16))
    regime[:576] = False
    height = highs - lows
    location = np.divide(closes - lows, height, out=np.zeros_like(height), where=height > 0)
    return {"open": opens, "high": highs, "low": lows, "close": closes,
            "atr": atr, "trend": trend, "regime": regime,
            "close_location": location}


def candidate_signals(common: dict[str, np.ndarray], config: dict) -> np.ndarray:
    close, high, low, opening = (common[k] for k in ("close", "high", "low", "open"))
    previous_high = lag(high)
    previous_close = lag(close)
    bullish = close > opening
    lookback = config["lookback"]
    family = config["family"]
    if family == "donchian":
        event = (close > lag(rolling(high, lookback, "max"))) & (common["close_location"] >= 0.75)
    elif family == "expansion":
        event = ((close > lag(rolling(high, lookback, "max"))) & bullish
                 & ((close - opening) >= common["atr"] * 0.8)
                 & (common["close_location"] >= 0.75))
    elif family == "ema_pullback":
        fast = ema(close, lookback)
        event = ((lag(low) <= lag(fast)) & (close > previous_high)
                 & (close > fast) & bullish)
    elif family == "pullback_reversal":
        event = ((previous_close < lag(close, lookback))
                 & (close > previous_high) & bullish
                 & (common["close_location"] >= 0.75))
    else:
        raise ValueError("Unregistered candidate family")
    atr_pips = common["atr"] / 0.0001
    return np.ascontiguousarray(
        event & common["regime"] & (atr_pips >= config["min_atr_pips"])
        & (atr_pips <= config["max_atr_pips"]), dtype=bool)
