"""Pre-final research only. Never load the reserved independent final here.

python -m research.intraday_mean_reversion.develop --symbol EURUSD
"""

from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

from research.intraday_engine import run_intraday_backtest
from trading_agent.risk import DEFAULT_COSTS
from .signals import candidate_configs, common_features, signals_from_features


def load_development(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = {"timestamp", "open", "high", "low", "close"}
    if not required.issubset(frame.columns):
        raise ValueError("Missing timestamp or OHLC fields")
    # Old naive timestamps have an unknown broker timezone. UTC conversion is
    # a synthetic ordering/elapsed-time clock, never a named-session claim.
    frame["time"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.loc[frame["time"] < pd.Timestamp("2022-01-01", tz="UTC")].copy()
    if not frame["time"].is_monotonic_increasing or frame["time"].duplicated().any():
        raise ValueError("Data must be unique and sorted")
    numeric = frame[["open", "high", "low", "close"]].to_numpy(float)
    if not np.isfinite(numeric).all() or (numeric <= 0).any():
        raise ValueError("Nonpositive/nonfinite prices")
    if ((frame["low"] > frame[["open", "close"]].min(axis=1)).any()
            or (frame["high"] < frame[["open", "close"]].max(axis=1)).any()
            or (frame["low"] > frame["high"]).any()):
        raise ValueError("Invalid OHLC geometry")
    return frame.reset_index(drop=True)


def block_bootstrap(values, block_length=20, repetitions=2000, seed=20261004):
    """Circular block bootstrap of natural trade PnL, preserving local clusters."""
    values = np.asarray(values, dtype=float)
    if len(values) < max(30, block_length):
        return {"block_length": block_length, "mean": float(values.mean()) if len(values) else None,
                "lower_95": None, "upper_95": None, "status": "insufficient_sample"}
    generator = np.random.default_rng(seed)
    blocks = int(np.ceil(len(values) / block_length))
    means = np.empty(repetitions)
    offsets = np.arange(block_length)
    for repetition in range(repetitions):
        starts = generator.integers(0, len(values), size=blocks)
        indices = (starts[:, None] + offsets[None, :]).ravel()[:len(values)] % len(values)
        means[repetition] = values[indices].mean()
    return {"block_length": block_length, "repetitions": repetitions,
            "mean": float(values.mean()), "lower_95": float(np.quantile(means, .025)),
            "upper_95": float(np.quantile(means, .975)), "seed": seed,
            "status": "completed", "interpretation": "Net USD expectancy per natural trade; not adjusted for multiple selection"}


def develop(symbol: str, data_path: Path, out_dir: Path, quote_kind: str = "mid",
            source_timezone: str = "UNKNOWN broker wall-clock") -> dict:
    if symbol not in ("EURUSD", "GBPUSD"):
        raise ValueError("Only the two preregistered instruments are allowed")
    out_dir.mkdir(parents=True, exist_ok=True)
    if (out_dir / "final_evaluation_receipt.json").exists():
        raise ValueError("This independent final was already examined; development cannot replace its frozen configuration")
    family = candidate_configs()
    plan = {"symbol": symbol, "source_file": str(data_path),
            "source_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
            "family": [candidate.to_dict() for candidate in family], "candidate_count": len(family),
            "global_new_family_count": len(family) * 2, "legacy_trials": 608,
            "development_end_exclusive": "2018-01-01", "validation_end_exclusive": "2022-01-01",
            "minimum_development_trades": 500, "minimum_validation_trades": 800,
            "minimum_net_win_rate": .5, "positive_net_both_splits": True,
            "bootstrap_lower_bound_positive_required_for_provisional_selection": True,
            "bootstrap_block_lengths": [20, 80], "bootstrap_repetitions": 2000,
            "final": "NOT LOADED; only after complete pre-final selection",
            "costs": asdict(DEFAULT_COSTS), "initial_equity": 100000.0}
    plan.update(quote_kind=quote_kind, source_timezone=source_timezone, max_signal_age_seconds=900)
    (out_dir / "preregistration.json").write_text(json.dumps(plan, indent=2) + "\n")
    frame = load_development(data_path)
    split = int(frame["time"].searchsorted(pd.Timestamp("2018-01-01", tz="UTC")))
    times = (frame["time"].astype("int64") // 1_000_000_000).to_numpy(np.int64)
    inputs = [times] + [frame[column].to_numpy(np.float64) for column in ("open", "high", "low", "close")]
    feature_cache = {}
    rows = []
    for config in family:
        if config.window not in feature_cache:
            feature_cache[config.window] = common_features(frame, config)
        arrays = signals_from_features(feature_cache[config.window], config)
        signals = [arrays[key] for key in ("entry_signals", "stop_distances", "target_distances")]
        development = run_intraday_backtest(*inputs, *signals, end_index=split,
                                           initial_equity=100000.0, costs=DEFAULT_COSTS,
                                           quote_kind=quote_kind, max_signal_age_seconds=900)
        validation = run_intraday_backtest(*inputs, *signals, start_index=split,
                                          initial_equity=100000.0, costs=DEFAULT_COSTS,
                                          quote_kind=quote_kind, max_signal_age_seconds=900)
        bootstraps = {}
        for name, result in (("development", development), ("validation", validation)):
            pnl = [trade["net_pnl"] for trade in result["trades"] if trade["reason"] != "sample_end"]
            bootstraps[name] = [block_bootstrap(pnl, length) for length in (20, 80)]
        dev, val = development["summary"], validation["summary"]
        viable = (dev["eligible_trades"] >= 500 and val["eligible_trades"] >= 800
                  and dev["win_rate"] >= .5 and val["win_rate"] >= .5
                  and dev["net_profit"] > 0 and val["net_profit"] > 0
                  and dev["risk_breaches"] == val["risk_breaches"] == 0
                  and all(record["lower_95"] is not None and record["lower_95"] > 0
                          for records in bootstraps.values() for record in records))
        row = {"config": config.to_dict(), "development": dev, "validation": val,
               "bootstrap": bootstraps, "selection_eligible": bool(viable),
               "selection_score": min(dev["net_profit_per_trade"], val["net_profit_per_trade"])}
        rows.append(row)
        print(json.dumps({"symbol": symbol, "candidate": config.name,
                          "dev_n": dev["eligible_trades"], "val_n": val["eligible_trades"],
                          "dev_net": round(dev["net_profit"], 4), "val_net": round(val["net_profit"], 4),
                          "dev_win": dev["win_rate"], "val_win": val["win_rate"], "viable": bool(viable)}), flush=True)
    viable = [row for row in rows if row["selection_eligible"]]
    sample_pool = [row for row in rows if row["development"]["eligible_trades"] >= 500
                   and row["validation"]["eligible_trades"] >= 800]
    selected = max(viable or sample_pool or rows, key=lambda row: row["selection_score"])
    source_limitation = ("Authoritative Dukascopy UTC BID candles; fixed spread is assumed, not observed ASK"
                         if source_timezone == "UTC" and quote_kind == "bid"
                         else "Old mirror quote side, price provenance and broker timezone are unverified")
    report = {"protocol": plan, "candidate_results": rows, "provisional_viable_count": len(viable),
              "selected_diagnostic": selected, "independent_final": "UNTOUCHED",
              "paper_approved": False,
              "selection_limitations": [source_limitation,
                                         "Bootstrap confidence is conditional on a chosen family and is not a multiple-selection correction",
                                         "The 48 new instrument/configuration trials are separate from 608 legacy trials",
                                         "No result from this research directory activates production orders"]}
    (out_dir / "development_report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", choices=("EURUSD", "GBPUSD"), default="EURUSD")
    parser.add_argument("--data", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--quote-kind", choices=("mid", "bid"), default="mid")
    parser.add_argument("--source-timezone", default="UNKNOWN broker wall-clock")
    args = parser.parse_args()
    data = args.data or Path(f"data/intraday/mirror_{args.symbol.lower()}_m15.csv")
    out = args.out_dir or Path(f"artifacts/intraday/mean_reversion/{args.symbol.lower()}")
    report = develop(args.symbol, data, out, args.quote_kind, args.source_timezone)
    print(json.dumps({"symbol": args.symbol, "viable_count": report["provisional_viable_count"],
                      "selected": report["selected_diagnostic"]["config"],
                      "final": report["independent_final"]}, indent=2))


if __name__ == "__main__":
    main()
