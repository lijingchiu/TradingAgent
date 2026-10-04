"""Predeclared causal liquidity-sweep reversal research on native M5/M15 bars.

Only 2015-2021 development/validation are allowed here. Unknown-clock mirror
data are deliberately excluded; direct UTC BID bars are required.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from research.intraday_engine import run_intraday_backtest


def candidates():
    return [dict(name=f"sweep{window}_{regime}_s{stop}_t{target}",
                 window=window, regime=regime, stop_pips=stop,
                 target_pips=target, max_holding_hours=24)
            for window, regime, (stop, target) in itertools.product(
                (24, 96, 288), ("any", "rising"),
                ((15, 20), (30, 20), (40, 30), (60, 30)))]


def register():
    plan = {"family": "price sweep below prior range followed by completed bullish recovery",
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "timeframes_minutes": [5, 15], "candidates_per_timeframe": candidates(),
            "initial_equity": 100000, "quote_kind": "bid",
            "costs": "unchanged production full spread 2pips, slippage .2pips per side, commission .35bps per side, minimum .10USD per side",
            "development": ["2015-01-01", "2018-01-01"],
            "validation": ["2018-01-01", "2022-01-01"],
            "holdout": ["2022-04-01", "2024-10-01"],
            "holdout_evaluated": False,
            "selection": "positive net development and validation, validation net wins >=50%, no risk breaches; rank by validation mean net pips",
            "mechanism": "Transient sell-side range break and completed rejection may expose reversal demand; unknown-clock source and future swing labels are excluded."}
    out = ROOT / "artifacts/intraday/sweep/preregistration.json"
    if out.exists():
        raise FileExistsError("Do not overwrite an existing preregistration")
    out.write_text(json.dumps(plan, indent=2) + "\n")


def signals(frame, config, minutes):
    close, low, high, opening = (frame[k] for k in ("close", "low", "high", "open"))
    prior_low = low.shift(1).rolling(config["window"], min_periods=config["window"]).min()
    prior_high = high.shift(1).rolling(config["window"], min_periods=config["window"]).max()
    ema_fast = close.ewm(span=128, min_periods=128, adjust=False).mean()
    ema_slow = close.ewm(span=512, min_periods=512, adjust=False).mean()
    # Require a genuine >=1pip excursion and recovery; no future swing-low labels.
    swept = ((low <= prior_low - .0001) & (close >= prior_low + .0001)
             & (close > opening) & ((close-low) >= .65*(high-low)))
    room = prior_high - close >= config["target_pips"] * .0001
    ready = np.arange(len(frame)) >= 1536
    regime = ((ema_fast >= ema_slow) & (ema_slow >= ema_slow.shift(96))) if config["regime"] == "rising" else True
    return (swept & room & regime & ready).fillna(False).to_numpy(dtype=bool)


def evaluate(path, minutes):
    reg = ROOT / "artifacts/intraday/sweep/preregistration.json"
    if not reg.exists():
        raise ValueError("Register the complete family before evaluating data")
    plan = json.loads(reg.read_text())
    if plan["candidates_per_timeframe"] != candidates():
        raise ValueError("Current candidates differ from the preregistered family")
    provenance_path = path.with_name(path.name.replace(f"_m{minutes}.csv", "_provenance.json"))
    provenance = json.loads(provenance_path.read_text())
    if provenance.get("quote_side") != "BID" or provenance.get("timezone") != "UTC":
        raise ValueError("Verified native UTC BID provenance is required")
    expected_hash = provenance["aggregate_outputs"][f"M{minutes}"]["sha256"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        raise ValueError("Source differs from its verified aggregation checksum")
    frame = pd.read_csv(path)
    if not frame.timestamp.str.endswith("Z").all():
        raise ValueError("Every source timestamp must explicitly identify UTC")
    times = pd.to_datetime(frame.timestamp, utc=True)
    if times.max() >= pd.Timestamp("2022-01-01", tz="UTC"):
        raise ValueError("This development runner rejects holdout files")
    arrays = (times.astype("int64").to_numpy()//10**9,
              *(frame[k].to_numpy(float) for k in ("open", "high", "low", "close")))
    rows=[]
    for config in candidates():
        signal = signals(frame, config, minutes)
        result={"config":config}
        for name, start, end in (("development", "2015-01-01", "2018-01-01"),
                                 ("validation", "2018-01-01", "2022-01-01")):
            first, last = np.searchsorted(arrays[0], [int(pd.Timestamp(start,tz="UTC").timestamp()), int(pd.Timestamp(end,tz="UTC").timestamp())])
            run=run_intraday_backtest(*arrays, signal, config["stop_pips"]*.0001,
                 config["target_pips"]*.0001, quote_kind="bid", initial_equity=100000,
                 max_holding_bars=config["max_holding_hours"]*60//minutes,
                 max_signal_age_seconds=minutes*60,
                 start_index=int(first), end_index=int(last), include_trades=False)
            result[name]=run["summary"]
        rows.append(result)
        print(minutes,config["name"],[(n,result[n]["eligible_trades"],round(result[n]["win_rate"],3),round(result[n]["net_profit"],2)) for n in ("development","validation")],flush=True)
    eligible=[r for r in rows if r["development"]["net_profit"]>0 and r["validation"]["net_profit"]>0 and r["validation"]["win_rate"]>=.5 and not r["validation"]["risk_breaches"]]
    report={"data_path":str(path),"sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
            "preregistration_sha256":hashlib.sha256(reg.read_bytes()).hexdigest(),
            "engine_sha256":hashlib.sha256((ROOT/"research/intraday_engine.py").read_bytes()).hexdigest(),
            "holding_period_note":"24 hours of observed native bars, capped at five calendar days; closed-market gaps can extend clock time",
            "timeframe_minutes":minutes,"holdout_evaluated":False,"candidates":rows,
            "eligible":len(eligible), "best_candidate":max(eligible,key=lambda r:r["validation"]["mean_net_pips_per_trade"])["config"] if eligible else None}
    target=ROOT/f"artifacts/intraday/sweep/m{minutes}_development_validation.json"
    target.write_text(json.dumps(report,indent=2)+"\n")


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--register",action="store_true")
    parser.add_argument("--data",type=Path)
    parser.add_argument("--minutes",type=int,choices=(5,15))
    args=parser.parse_args()
    if args.register: register()
    else: evaluate(args.data,args.minutes)
