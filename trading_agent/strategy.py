"""Causal, shared signals for research and the paper account.

All features use completed bars only.  A signal at index i can first be traded
at the open of index i + 1.  This module has no broker or order side effects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class StrategyConfig:
    name: str = "rsi2_ema200_atr2_target1"
    bar_hours: int = 1
    rsi_period: int = 2
    rsi_entry: float = 5.0
    ema_period: int = 200
    trend_filter: str = "above"
    atr_period: int = 14
    stop_atr: float = 2.0
    target_atr: float = 1.0
    max_days: int = 5
    minimum_atr_pips: float = 3.0
    pip_size: float = 0.0001

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "StrategyConfig":
        return cls(**value)


def candidate_configs() -> list[StrategyConfig]:
    """The first fixed 24-candidate family, recorded even when it fails."""
    return [
        StrategyConfig(
            name=f"rsi{threshold:g}_ema{ema}_stop{stop:g}_target{target:g}",
            rsi_entry=threshold,
            ema_period=ema,
            stop_atr=stop,
            target_atr=target,
        )
        for threshold in (5.0, 10.0, 15.0)
        for ema in (100, 200)
        for stop in (2.0, 3.0)
        for target in (1.0, 1.5)
    ]


def cost_aware_candidate_configs() -> list[StrategyConfig]:
    """120 trials across three documented, pre-holdout research stages.

    The first 24 failed after costs. Larger moves and volatility floors were
    then designed using development/validation only. Reusing validation for
    this diagnosis is selection bias; the untouched final gate is essential.
    """
    return candidate_configs() + [
        StrategyConfig(
            name=f"v2_rsi{threshold:g}_ema{ema}_stop{stop:g}_target{target:g}_minatr{minimum:g}",
            rsi_entry=threshold, ema_period=ema, stop_atr=stop, target_atr=target,
            minimum_atr_pips=minimum,
        )
        for threshold in (5.0, 15.0, 25.0)
        for ema in (100, 400)
        for stop in (4.0, 6.0)
        for target in (2.0, 3.0)
        for minimum in (5.0, 10.0)
    ] + [
        StrategyConfig(
            name=f"v3_rsi{threshold:g}_ema{ema}_stop{stop:g}_target{target:g}_minatr{minimum:g}",
            rsi_entry=threshold, ema_period=ema, stop_atr=stop, target_atr=target,
            minimum_atr_pips=minimum,
        )
        for threshold in (5.0, 10.0, 20.0)
        for ema in (100, 200)
        for stop in (2.0, 3.0)
        for target in (2.0, 3.0)
        for minimum in (5.0, 10.0)
    ]


def mean_reversion_candidate_configs() -> list[StrategyConfig]:
    """The 48 pre-holdout four-hour trend-free/reversed-trend trials."""
    return [
        StrategyConfig(
            name=f"v{version}_h4_rsi{threshold:g}_{trend}_stop{stop:g}_target{target:g}",
            bar_hours=4, rsi_entry=threshold, trend_filter=trend, ema_period=100,
            stop_atr=stop, target_atr=target,
        )
        for version, targets in ((5, (1.0, 1.5)), (6, (2.0, 3.0)))
        for threshold in (5.0, 10.0, 20.0)
        for trend in ("none", "below")
        for stop in (2.0, 3.0)
        for target in targets
    ]


def compute_features(bars: Iterable[Any], config: StrategyConfig) -> list[dict[str, Any]]:
    """Wilder RSI/ATR and EMA, seeded without future observations.

    Bar objects need open/high/low/close attributes.  Warmup is deliberately
    longer than the EMA period, and is explicit in every output row.
    """
    result: list[dict[str, Any]] = []
    previous_close: float | None = None
    ema: float | None = None
    avg_gain: float | None = None
    avg_loss: float | None = None
    atr: float | None = None
    gains: list[float] = []
    losses: list[float] = []
    true_ranges: list[float] = []
    alpha = 2.0 / (config.ema_period + 1)
    warmup = max(config.ema_period * 3, config.atr_period * 3, config.rsi_period * 3)
    for index, bar in enumerate(bars):
        close = float(bar.close)
        ema = close if ema is None else alpha * close + (1.0 - alpha) * ema
        tr = float(bar.high) - float(bar.low)
        if previous_close is not None:
            tr = max(tr, abs(float(bar.high) - previous_close), abs(float(bar.low) - previous_close))
            change = close - previous_close
            gain, loss = max(0.0, change), max(0.0, -change)
            if avg_gain is None:
                gains.append(gain)
                losses.append(loss)
                if len(gains) == config.rsi_period:
                    avg_gain = sum(gains) / config.rsi_period
                    avg_loss = sum(losses) / config.rsi_period
            else:
                avg_gain = (avg_gain * (config.rsi_period - 1) + gain) / config.rsi_period
                avg_loss = (avg_loss * (config.rsi_period - 1) + loss) / config.rsi_period
        if atr is None:
            true_ranges.append(tr)
            if len(true_ranges) == config.atr_period:
                atr = sum(true_ranges) / config.atr_period
        else:
            atr = (atr * (config.atr_period - 1) + tr) / config.atr_period
        rsi: float | None = None
        if avg_gain is not None and avg_loss is not None:
            rsi = 50.0 if avg_gain == avg_loss == 0 else (
                100.0 if avg_loss == 0 else 100.0 - 100.0 / (1.0 + avg_gain / avg_loss)
            )
        result.append({"index": index, "close": close, "ema": ema, "atr": atr,
                       "rsi": rsi, "ready": index >= warmup})
        previous_close = close
    return result


def entry_signal(features: dict[str, Any], config: StrategyConfig) -> bool:
    """Buy completed oversold bars subject to the declared trend condition."""
    if not features.get("ready"):
        return False
    rsi, atr = features.get("rsi"), features.get("atr")
    trend = {"above": features["close"] > features["ema"],
             "below": features["close"] < features["ema"], "none": True}.get(config.trend_filter, False)
    return bool(
        rsi is not None and atr is not None
        and rsi <= config.rsi_entry
        and trend
        and atr >= config.minimum_atr_pips * config.pip_size
    )


def trade_levels(features: dict[str, Any], config: StrategyConfig) -> tuple[float, float]:
    """Distances, anchored to the next actual entry, never the signal close."""
    atr = features.get("atr")
    if atr is None or atr <= 0:
        raise ValueError("A positive ATR from a completed bar is required")
    return float(atr) * config.stop_atr, float(atr) * config.target_atr
