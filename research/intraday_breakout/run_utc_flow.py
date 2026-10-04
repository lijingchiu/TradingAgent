#!/usr/bin/env python3
"""Exactly preregistered local-flow continuation, development/validation only.

Signal prices stop at the previous completed M15 candle. Session permission and
clock expiry are decisions at the currently observed opening timestamp. The
calendar expiry mask is shifted to the engine's prior-index API; it never reads
prices from that opening or any later candle to decide whether to exit.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.intraday_engine import run_intraday_backtest
from research.intraday_breakout.run_research import months, stamp


def read_frame(path: Path):
    frame = pd.read_csv(path)
    times = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.loc[times < pd.Timestamp("2022-01-01", tz="UTC")].copy()
    frame["epoch"] = times.loc[frame.index].astype("int64") // 1_000_000_000
    if len(frame) == 0 or frame["epoch"].duplicated().any():
        raise ValueError("Research source must have unique, nonempty ordered candles")
    return frame


def clocks(times: np.ndarray, zone: str):
    clock = ZoneInfo(zone)
    local = [datetime.fromtimestamp(int(value), timezone.utc).astimezone(clock) for value in times]
    hours = np.fromiter((d.hour for d in local), dtype=int, count=len(times))
    minutes = np.fromiter((d.minute for d in local), dtype=int, count=len(times))
    weekdays = np.fromiter((d.weekday() for d in local), dtype=int, count=len(times))
    return hours, minutes, weekdays


def decisions(times, closes, config, clock):
    hours, minutes, weekdays = clock
    allowed = (hours == 8) & (minutes == 0) & (weekdays < 5)
    lookback = config["momentum_hours"] * 4
    entries = np.ones(len(times), dtype=bool)
    if lookback:
        entries[:] = False
        entries[lookback:] = ((closes[lookback:] > closes[:-lookback])
                             & (times[lookback:] - times[:-lookback] == lookback * 900))
    # Execution-time calendar only: no OHLC from the opening being traded.
    current_expired = (hours >= 8 + config["holding_clock_hours"]) | (hours < 8)
    exits = np.zeros(len(times), dtype=bool)
    exits[:-1] = (current_expired[1:]
                 | (np.diff(times) >= config["holding_clock_hours"] * 3600))
    return entries, allowed, exits


def intervals(trades):
    natural = [row for row in trades if row["reason"] != "sample_end"]
    count = len(natural)
    wins = sum(row["net_pnl"] > 0 for row in natural)
    if not count:
        return {"win_rate_wilson_95": None, "mean_net_pips_iid_normal_95": None}
    z = 1.96
    rate = wins / count
    denominator = 1 + z * z / count
    center = (rate + z * z / (2 * count)) / denominator
    width = z * math.sqrt(rate * (1 - rate) / count + z * z / (4 * count * count)) / denominator
    pips = np.array([row["net_pnl"] / row["units"] / 0.0001 for row in natural])
    error = z * float(np.std(pips, ddof=1)) / math.sqrt(count) if count > 1 else 0.0
    return {"win_rate_wilson_95": [center - width, center + width],
            "mean_net_pips_iid_normal_95": [float(np.mean(pips)) - error, float(np.mean(pips)) + error],
            "diagnostic_only": True,
            "assumption": "Approximate IID intervals; serial dependence and selection can reduce coverage"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--ask-data", type=Path, help="Actual synchronized ASK archive candles; opening required")
    parser.add_argument("--output-name", default="utc_flow_fixed_2pip")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    folder = root / "artifacts/intraday/breakout"
    registration_path = folder / "utc_flow_preregistration.json"
    registration = json.loads(registration_path.read_text())
    frame = read_frame(args.data)
    times = frame["epoch"].to_numpy(dtype=np.int64)
    arrays = [frame[name].to_numpy(dtype=float) for name in ("open", "high", "low", "close")]
    mode = "fixed_2pip_stress"
    book_kwargs = {}
    valid_ask = np.ones(len(times), dtype=bool)
    source_quality = {}
    if args.ask_data:
        confirmation_path = folder / "utc_flow_spread_confirmation_preregistration.json"
        if not confirmation_path.is_file():
            raise ValueError("Measured spread confirmation must be preregistered first")
        ask = read_frame(args.ask_data)[["epoch", "open"]].rename(columns={"open": "ask_open"})
        aligned = frame[["epoch"]].merge(ask, on="epoch", how="left", sort=False)
        if not np.array_equal(times, aligned["epoch"].to_numpy(dtype=np.int64)):
            raise ValueError("ASK alignment changed BID observation order")
        observed = aligned["ask_open"].to_numpy(dtype=float)
        valid_ask = np.isfinite(observed) & (observed >= arrays[0])
        # Placeholder BID values are never executable: their entry mask is false.
        executable_asks = np.where(valid_ask, observed, arrays[0])
        book_kwargs = {"ask_opens": executable_asks, "book_source": "Dukascopy observed UTC ASK/BID openings"}
        spread = (observed[valid_ask] - arrays[0][valid_ask]) / 0.0001
        source_quality = {"ask_data_path": str(args.ask_data),
                          "ask_data_sha256": hashlib.sha256(args.ask_data.read_bytes()).hexdigest(),
                          "invalid_or_missing_ask_bars": int(np.count_nonzero(~valid_ask)),
                          "valid_ask_fraction": float(np.mean(valid_ask)),
                          "actual_spread_pips_quantiles": {str(q): float(np.quantile(spread, q)) for q in (0, 0.5, 0.9, 0.99, 1)},
                          "invalid_ask_policy": "Entry blocked; BID observation retained for existing position exits; nonexecuting ASK placeholder equals BID",
                          "confirmation_preregistration_sha256": hashlib.sha256(confirmation_path.read_bytes()).hexdigest()}
        mode = "measured_ask_bid_baseline"
    local_clocks = {zone: clocks(times, zone) for zone in {row["timezone"] for row in registration["candidates"]}}
    results = []
    for config in registration["candidates"]:
        entries, allowed, exits = decisions(times, arrays[3], config, local_clocks[config["timezone"]])
        allowed &= valid_ask
        row = {"config": config}
        for split, start, end in (("development", "2015-01-01", "2018-01-01"),
                                   ("validation", "2018-01-01", "2022-01-01")):
            first, last = np.searchsorted(times, [stamp(start), stamp(end)])
            run = run_intraday_backtest(times, *arrays, entries,
                stop_distances=0.008, target_distances=0.008,
                entry_allowed=allowed, exit_signals=exits,
                max_holding_days=5, initial_equity=500000,
                start_index=int(first), end_index=int(last), quote_kind="bid",
                max_signal_age_seconds=900, include_trades=True,
                **book_kwargs)
            row[split] = {"summary": run["summary"], "stability": months(run["trades"]),
                          "uncertainty_diagnostics": intervals(run["trades"])}
        d, v = [row[name]["summary"] for name in ("development", "validation")]
        row["passes_both_splits"] = all(summary["net_profit"] > 0 and summary["win_rate"] >= 0.5
                                       and summary["risk_breaches"] == 0 for summary in (d, v))
        row["combined_natural_trade_count"] = d["eligible_trades"] + v["eligible_trades"]
        results.append(row)
        print(config["name"], "dev", d["eligible_trades"], round(d["win_rate"], 4), round(d["net_profit"], 2),
              "val", v["eligible_trades"], round(v["win_rate"], 4), round(v["net_profit"], 2),
              "val_net_pips", round(v["mean_net_pips_per_trade"], 3),
              "PASS" if row["passes_both_splits"] else "reject", flush=True)
    ranked = sorted([row for row in results if row["passes_both_splits"]],
                    key=lambda row: row["validation"]["summary"]["mean_net_pips_per_trade"], reverse=True)
    report = {"mode": mode, "capital": 500000, "symbol": "EURUSD", "native_timeframe": "M15", "clock_source": "UTC",
              "preregistration_sha256": hashlib.sha256(registration_path.read_bytes()).hexdigest(),
              "data_path": str(args.data), "data_sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
              "source_quality": source_quality, "holdout_evaluated": False,
              "candidates": results, "eligible_candidates": len(ranked),
              "best_candidate": ranked[0]["config"] if ranked else None,
              "count_note": "Combined count is development plus validation, not final independent evidence",
              "fixed_spread_stress_note": "Measured-ASK baseline must disclose these fixed 2pip stress outcomes, including losses"}
    output = folder / (args.output_name + ".json")
    output.write_text(json.dumps(report, indent=2) + "\n")
    print("Saved", output, "eligible", len(ranked))


if __name__ == "__main__":
    main()
