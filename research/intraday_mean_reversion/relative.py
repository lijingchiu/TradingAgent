"""Pre-final cross-currency mean reversion with observed USD-flow confirmation.

The ratio of two contemporaneous USD-quoted currencies represents a currency
cross. Buy a lagging currency only after its own rebound and positive recent
movement in the other currency. This tests a different premise from an
oversold single-price indicator; it does not assert that the cross is stationary.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from research.intraday_engine import run_intraday_backtest
from trading_agent.risk import DEFAULT_COSTS
from .develop import block_bootstrap, load_development
from .signals import MeanReversionConfig, common_features


@dataclass(frozen=True)
class RelativeConfig:
    name: str
    window: int
    threshold: float
    confirmation: str
    other_momentum_bars: int
    other_momentum_pips: float
    stop_pips: float
    target_pips: float
    timeframe_minutes: int = 15
    pip_size: float = .0001
    max_holding_days: int = 5

    def to_dict(self):
        return asdict(self)


def candidate_configs():
    return [RelativeConfig(
        f"cross{window}_z{threshold:g}_{confirmation}_other{momentum_bars}_{momentum_pips:g}_stop{stop:g}_target{target:g}",
        window, threshold, confirmation, momentum_bars, momentum_pips, stop, target,
    ) for window in (96, 384)
      for threshold in (1.5, 2.0)
      for confirmation in ("extreme_with_own_rebound", "cross_reenters_band")
      for momentum_bars, momentum_pips in ((4, 3.0), (16, 10.0))
      for stop, target in ((20.0, 10.0), (30.0, 20.0))]


def relative_features(frame, window):
    config = MeanReversionConfig("common_regime", window=window)
    base = common_features(frame, config)
    cross = np.log(frame["close"]) - np.log(frame["other_close"])
    cross_mean = cross.rolling(window, min_periods=window).mean()
    cross_std = cross.rolling(window, min_periods=window).std(ddof=0)
    base["cross_zscore"] = (cross - cross_mean) / cross_std.where(cross_std > 0)
    base["conditional_gap"] = frame["close"] * (np.exp(cross_mean - cross) - 1.0)
    base["other_close"] = frame["other_close"]
    return base


def build_signals(features, config):
    zscore = features["cross_zscore"]
    own_rebound = features["close"] > features["close"].shift(1)
    if config.confirmation == "extreme_with_own_rebound":
        extreme = zscore <= -config.threshold
    else:
        extreme = (zscore.shift(1) <= -config.threshold) & (zscore > -config.threshold)
    other_momentum = features["other_close"] - features["other_close"].shift(config.other_momentum_bars)
    regime = ((features["atr_fast"] <= 2 * features["atr_slow"])
              & (features["atr_fast"] >= .0001)
              & features["macro_slope_atr"].between(-2.0, 4.0))
    targets = np.full(len(features), config.target_pips * config.pip_size)
    entries = (features["ready"] & extreme & own_rebound & regime
               & (other_momentum >= config.other_momentum_pips * config.pip_size)
               & (features["conditional_gap"] >= targets)).fillna(False)
    return entries.to_numpy(np.bool_), np.full(len(features), config.stop_pips * config.pip_size), targets


def develop(symbol: str):
    other = "GBPUSD" if symbol == "EURUSD" else "EURUSD"
    paths = {pair: Path(f"data/intraday/mirror_{pair.lower()}_m15.csv") for pair in (symbol, other)}
    family = candidate_configs()
    output = Path(f"artifacts/intraday/mean_reversion/relative/{symbol.lower()}")
    output.mkdir(parents=True, exist_ok=True)
    plan = {"symbol": symbol, "other_symbol": other, "candidate_count": len(family),
            "global_relative_family_count": len(family) * 2, "prior_new_BB_trials": 48,
            "legacy_trials": 608, "source_sha256": {pair: hashlib.sha256(path.read_bytes()).hexdigest() for pair, path in paths.items()},
            "family": [config.to_dict() for config in family],
            "development_end_exclusive": "2018-01-01", "validation_end_exclusive": "2022-01-01",
            "minimum_development_trades": 500, "minimum_validation_trades": 800,
            "minimum_win_rate": .5, "both_split_net_profits_positive": True,
            "bootstrap_positive_lower_95_required": True, "bootstrap_blocks": [20, 80],
            "bootstrap_repetitions": 2000, "initial_equity": 100000.0,
            "costs": asdict(DEFAULT_COSTS), "quote_kind": "unknown source; assumed mid",
            "max_signal_age_seconds": 900,
            "independent_final": "NOT LOADED", "family_must_not_change_after_final": True,
            "source_clock_assumption": "Both mirrors' supplied broker clocks assumed consistent for same-timestamp alignment; timezone not independently verified",
            "no_named_sessions": True, "no_forward_fill": True,
            "hypothesis": "A lagging currency may catch up to contemporaneous positive USD-quoted peer momentum after its own observed rebound; FX cross stationarity is a test, not an assumption"}
    (output / "preregistration.json").write_text(json.dumps(plan, indent=2) + "\n")
    own, peer = load_development(paths[symbol]), load_development(paths[other])
    frame = own.merge(peer[["time", "close"]].rename(columns={"close": "other_close"}), on="time", how="inner")
    if frame["time"].duplicated().any() or not frame["time"].is_monotonic_increasing:
        raise ValueError("Aligned observations must remain strictly ordered and unique")
    frame = frame.reset_index(drop=True)
    split = int(frame["time"].searchsorted(pd.Timestamp("2018-01-01", tz="UTC")))
    times = (frame["time"].astype("int64") // 1_000_000_000).to_numpy(np.int64)
    inputs = [times] + [frame[column].to_numpy(float) for column in ("open", "high", "low", "close")]
    cache, rows = {}, []
    for config in family:
        if config.window not in cache:
            cache[config.window] = relative_features(frame, config.window)
        arrays = build_signals(cache[config.window], config)
        dev_result = run_intraday_backtest(*inputs, *arrays, end_index=split, quote_kind="mid",
                                          max_signal_age_seconds=900)
        val_result = run_intraday_backtest(*inputs, *arrays, start_index=split, quote_kind="mid",
                                          max_signal_age_seconds=900)
        dev, val = dev_result["summary"], val_result["summary"]
        eligible = (dev["eligible_trades"] >= 500 and val["eligible_trades"] >= 800
                    and dev["win_rate"] >= .5 and val["win_rate"] >= .5
                    and dev["net_profit"] > 0 and val["net_profit"] > 0
                    and dev["risk_breaches"] == val["risk_breaches"] == 0)
        bootstrap = {}
        if eligible:
            for name, result in (("development", dev_result), ("validation", val_result)):
                pnl = [trade["net_pnl"] for trade in result["trades"] if trade["reason"] != "sample_end"]
                bootstrap[name] = [block_bootstrap(pnl, length) for length in (20, 80)]
            eligible = all(record["lower_95"] is not None and record["lower_95"] > 0
                           for records in bootstrap.values() for record in records)
        rows.append({"config": config.to_dict(), "development": dev, "validation": val,
                     "bootstrap": bootstrap, "selection_eligible": bool(eligible),
                     "selection_score": min(dev["natural_net_profit_per_trade"], val["natural_net_profit_per_trade"])})
        print(json.dumps({"symbol": symbol, "candidate": config.name,
                          "dev_n": dev["eligible_trades"], "val_n": val["eligible_trades"],
                          "dev_net": round(dev["net_profit"], 4), "val_net": round(val["net_profit"], 4),
                          "dev_win": dev["win_rate"], "val_win": val["win_rate"], "viable": bool(eligible)}), flush=True)
    viable = [row for row in rows if row["selection_eligible"]]
    frequency_pool = [row for row in rows if row["development"]["eligible_trades"] >= 500
                      and row["validation"]["eligible_trades"] >= 800]
    selected = max(viable or frequency_pool or rows, key=lambda row: row["selection_score"])
    report = {"protocol": plan, "candidate_results": rows,
              "provisional_viable_count": len(viable), "selected_diagnostic": selected,
              "independent_final": "UNTOUCHED", "paper_approved": False,
              "aligned_development_rows": len(frame)}
    (output / "development_report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", choices=("EURUSD", "GBPUSD"), default="EURUSD")
    args = parser.parse_args()
    result = develop(args.symbol)
    print(json.dumps({"symbol": args.symbol, "viable_count": result["provisional_viable_count"],
                      "selected": result["selected_diagnostic"]["config"], "final": "UNTOUCHED"}, indent=2))
