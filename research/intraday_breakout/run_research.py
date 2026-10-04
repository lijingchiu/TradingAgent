#!/usr/bin/env python3
"""Run fixed breakout candidates on development/validation data only.

This runner rejects any evaluation end later than 2022-01-01. It never emits a
holdout evaluation. Root must freeze selected configuration before any final
test using the independent shared engine.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from research.intraday_engine import run_intraday_backtest
from research.intraday_breakout.features import common_features, candidate_signals


def stamp(value: str) -> int:
    return int(datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp())


def load(path: Path):
    frame = pd.read_csv(path)
    frame.columns = [column.lower() for column in frame.columns]
    date_column = next(name for name in ("timestamp", "date", "time") if name in frame.columns)
    # A mirror's naive timestamps provide ordering only, not a documented UTC session.
    times = pd.to_datetime(frame[date_column], utc=True)
    frame = frame.loc[times < pd.Timestamp("2022-01-01", tz="UTC")].copy()
    times = times.loc[frame.index]
    frame = frame.loc[times >= pd.Timestamp("2014-10-01", tz="UTC")]
    times = times.loc[frame.index]
    prices = [frame[name].to_numpy(dtype=float) for name in ("open", "high", "low", "close")]
    # Original historical mirror stores integer-like quotes times 100000.
    if np.median(prices[3]) > 100:
        prices = [values / 100000.0 for values in prices]
    return (times.astype("int64").to_numpy() // 1_000_000_000, *prices)


def months(trades: list[dict]) -> dict:
    grouped = defaultdict(list)
    for trade in trades:
        if trade["reason"] == "sample_end":
            continue
        key = datetime.fromtimestamp(trade["exit_time"], timezone.utc).strftime("%Y-%m")
        grouped[key].append(trade["net_pnl"])
    monthly = [{"month": key, "trades": len(values), "net_profit": sum(values),
                "net_win_rate": sum(v > 0 for v in values) / len(values)}
               for key, values in sorted(grouped.items())]
    return {"months_with_trades": len(monthly),
            "positive_months": sum(m["net_profit"] > 0 for m in monthly),
            "negative_months": sum(m["net_profit"] < 0 for m in monthly),
            "monthly": monthly}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--symbol", choices=("EURUSD", "GBPUSD"), required=True)
    parser.add_argument("--source", required=True, help="Mirror or direct-source provenance description")
    parser.add_argument("--quote-kind", choices=("mid", "bid"), default="mid",
                        help="Mirrors assume mid; direct Dukascopy BID must explicitly select bid")
    parser.add_argument("--output-name", default="development_validation")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    folder = root / "artifacts/intraday/breakout"
    registration_path = folder / "preregistration.json"
    registration = json.loads(registration_path.read_text())
    arrays = load(args.data)
    times, opening, high, low, close = arrays
    if not len(times) or times[-1] >= stamp("2022-01-01"):
        raise ValueError("Only development and validation bars may be evaluated")
    common = common_features(opening, high, low, close)
    candidates = []
    for config in registration["candidates"]:
        signals = candidate_signals(common, config)
        result = {"config": config}
        for split, start, end in (("development", "2015-01-01", "2020-01-01"),
                                   ("validation", "2020-01-01", "2022-01-01")):
            first, last = np.searchsorted(times, [stamp(start), stamp(end)])
            run = run_intraday_backtest(*arrays, signals,
                config["stop_pips"] * 0.0001, config["target_pips"] * 0.0001,
                max_holding_bars=config["max_holding_bars"], max_holding_days=5,
                initial_equity=100000, start_index=int(first), end_index=int(last),
                include_trades=True, include_equity_curve=False, quote_kind=args.quote_kind,
                max_signal_age_seconds=15 * 60)
            result[split] = {"summary": run["summary"], "stability": months(run["trades"])}
        candidates.append(result)
        development, validation = (result[s]["summary"] for s in ("development", "validation"))
        print(config["name"],
              "dev", development["eligible_trades"], round(development["win_rate"], 4), round(development["net_profit"], 2),
              "val", validation["eligible_trades"], round(validation["win_rate"], 4), round(validation["net_profit"], 2),
              "mean_net_pips", round(validation["mean_net_pips_per_trade"], 3), flush=True)
    eligible = [row for row in candidates
                if row["development"]["summary"]["net_profit"] >= 0
                and row["validation"]["summary"]["net_profit"] > 0
                and row["validation"]["summary"]["win_rate"] >= 0.5
                and row["validation"]["summary"]["risk_breaches"] == 0]
    ranked = sorted(eligible, key=lambda row: row["validation"]["summary"]["mean_net_pips_per_trade"], reverse=True)
    report = {"symbol": args.symbol, "source": args.source,
              "quote_kind": args.quote_kind,
              "quote_assumption": "Fixed-spread modeled midpoint from bid OHLC" if args.quote_kind == "bid" else "Midpoint assumption; source quote side must be checked separately",
              "data_path": str(args.data), "data_sha256": hashlib.sha256(args.data.read_bytes()).hexdigest(),
              "preregistration_sha256": hashlib.sha256(registration_path.read_bytes()).hexdigest(),
              "holdout_evaluated": False,
              "candidates": candidates,
              "development_validation_eligible": len(eligible),
              "best_candidate": ranked[0]["config"] if ranked else None,
              "trade_count_note": "Development and validation counts are separate; none are final untouched-test evidence"}
    out = folder / (args.symbol.lower() + "_" + args.output_name + ".json")
    out.write_text(json.dumps(report, indent=2) + "\n")
    print("Saved", out, "eligible", len(eligible))


if __name__ == "__main__":
    main()
