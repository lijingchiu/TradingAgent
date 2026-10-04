"""Fixed stop/time/confirmation tests justified by 2017 stop diagnostics.

This adds twelve disclosed operating configurations. It does not alter the
preceding frozen pattern study or read any reserved final observations.
"""
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.fxcm_rsi2 import ROOT, inputs, simulate, diagnostics, sha

OUT = ROOT/"artifacts/intraday/fxcm_rsi2_tailguard"


def signal_inputs(frame: pd.DataFrame, plan: dict, variant: str) -> dict:
    allowed_variants = plan["variants_per_base"]
    if variant not in allowed_variants:
        raise ValueError("Unregistered tail-risk variant")
    arrays = inputs(frame, plan["base_signal"])
    if variant != "smaller_stop_and_time":
        settings = plan["base_signal"]
        change = frame.BidClose.diff()
        gain = change.clip(lower=0).ewm(alpha=1/settings["rsi_period"], adjust=False,
                                       min_periods=settings["rsi_period"]).mean()
        loss = (-change).clip(lower=0).ewm(alpha=1/settings["rsi_period"], adjust=False,
                                          min_periods=settings["rsi_period"]).mean()
        rsi = (100*gain/(gain+loss)).mask((gain+loss == 0) & gain.notna(), 50.)
        rule = plan["confirmation"]
        ready = np.arange(len(frame)) >= settings["minimum_warmup_trading_bars"]
        signal = (ready & (rsi.shift(1) <= rule["prior_completed_rsi_at_most"])
                  & (rsi > rule["current_completed_rsi_lower_exclusive"])
                  & (rsi <= rule["current_completed_rsi_upper_inclusive"])
                  & (frame.BidClose > frame.BidClose.shift(1)))
        arrays["entries"] = (signal & (arrays["stop"]/.0001/settings["stop_atr"]
                                      >= settings["minimum_atr_pips"])).to_numpy(bool)
    if variant.endswith("atr_not_compressed"):
        # x[i,1] is ATR14/ATR96 from completed i-1. Current OHLC cannot gate entry.
        arrays["allowed"] &= (arrays["x"][:,1] >= plan["compression_filter"]["completed_atr14_divided_by_atr96_at_least"])
    return arrays


def study():
    plan=json.loads((OUT/"preregistration.json").read_text())
    if (OUT/"selection_report.json").exists():
        raise RuntimeError("Preserve the existing study; no silent outcome overwrite")
    provenance_path=ROOT/"data/intraday/fxcm_official/eurusd_development_validation_2017_2021_provenance.json"
    provenance=json.loads(provenance_path.read_text())
    hashes={"research/fxcm_rsi2_tailguard.py":sha(Path(__file__)),
            "research/fxcm_rsi2.py":sha(ROOT/"research/fxcm_rsi2.py"),
            "research/intraday_engine.py":sha(ROOT/"research/intraday_engine.py"),
            "research/statistics.py":sha(ROOT/"research/statistics.py"),
            "preregistration.json":sha(OUT/"preregistration.json"),
            str(provenance_path.relative_to(ROOT)):sha(provenance_path)}
    rows=[]
    for minutes in plan["timeframes_minutes"]:
        record=provenance["outputs"][f"m{minutes}"]
        path=ROOT/record["path"]
        if sha(path) != record["sha256"]:
            raise ValueError("Source-quality candle hash changed")
        frame=pd.read_csv(path)
        time=pd.to_datetime(frame.time,utc=True)
        if not ((time >= pd.Timestamp("2017-01-01",tz="UTC")) & (time < pd.Timestamp("2022-01-01",tz="UTC"))).all():
            raise ValueError("Only registered development/selection dates may enter")
        split=int(time.searchsorted(pd.Timestamp("2018-01-01",tz="UTC")))
        hashes[record["path"]]=sha(path)
        for capital in plan["initial_capitals_usd"]:
            for variant in plan["variants_per_base"]:
                arrays=signal_inputs(frame,plan,variant)
                name=f"rsi2_m{minutes}_usd{capital}_{variant}"
                dev=simulate(frame,arrays,plan,minutes,capital,0,split)
                val=simulate(frame,arrays,plan,minutes,capital,split,len(frame))
                ds,vs=dev["summary"],val["summary"]
                criteria=plan["selection_criteria"]
                eligible=(ds["eligible_trades"] >= criteria["minimum_development_natural_trades"]
                          and vs["eligible_trades"] >= criteria["minimum_validation_natural_trades"]
                          and ds["net_profit"]>0 and vs["net_profit"]>0 and ds["win_rate"]>=.5 and vs["win_rate"]>=.5
                          and ds["risk_breaches"]==vs["risk_breaches"]==0)
                row=dict(config=dict(name=name,minutes=minutes,capital=capital,variant=variant),
                         development=ds,validation=vs,development_statistics=dev["inspectible_statistics"],
                         validation_statistics=val["inspectible_statistics"],selection_eligible=bool(eligible),
                         selection_score=min(ds["net_profit"]/capital,vs["net_profit"]/capital))
                for phase,result in (("development",dev),("validation",val)):
                    raw_path=ROOT/"data/intraday/fxcm_official"/f"{name}_{phase}_trades.json"
                    raw_path.write_text(json.dumps(result["trades"],indent=2)+"\n")
                    trace,comparison=diagnostics(result["trades"],arrays["x"],name)
                    trace_path=OUT/f"{name}_{phase}_trade_features.csv"
                    trace.to_csv(trace_path,index=False,lineterminator="\n")
                    if phase=="development":
                        (OUT/f"{name}_development_pattern_comparison.json").write_text(json.dumps(comparison,indent=2)+"\n")
                    row[phase+"_local_quote_trace_path"]=str(raw_path.relative_to(ROOT))
                    row[phase+"_local_quote_trace_sha256"]=sha(raw_path)
                    row[phase+"_trade_features_path"]=str(trace_path.relative_to(ROOT))
                    row[phase+"_trade_features_sha256"]=sha(trace_path)
                rows.append(row)
                print(json.dumps({"name":name,"dev_n":ds["eligible_trades"],"val_n":vs["eligible_trades"],
                                  "dev_net":ds["net_profit"],"val_net":vs["net_profit"],
                                  "dev_win":ds["win_rate"],"val_win":vs["win_rate"],"eligible":bool(eligible)}),flush=True)
    qualified=sorted([r for r in rows if r["selection_eligible"]],
                     key=lambda r:(-r["selection_score"],-r["validation"]["net_profit"]/r["config"]["capital"],r["config"]["name"]))
    selected=qualified[0] if qualified else None
    report=dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),
                registered_protocol_sha256=sha(OUT/"preregistration.json"),code_data_hashes=hashes,
                candidates=rows,selection_eligible_count=len(qualified),selected_config=selected["config"] if selected else None,
                final="UNTOUCHED; select only one frozen configuration",paper_approved=False,
                limitations=plan["source_limitations"]+[plan["independence_note"]])
    if selected:
        freeze=dict(frozen_at_utc=datetime.now(timezone.utc).isoformat(),config=selected["config"],
                    plan_sha256=sha(OUT/"preregistration.json"),code_data_hashes=hashes,final_outcomes_evaluated=False,
                    development=selected["development"],validation=selected["validation"])
        (OUT/"selected_strategy_freeze.json").write_text(json.dumps(freeze,indent=2)+"\n")
    (OUT/"selection_report.json").write_text(json.dumps(report,indent=2)+"\n")
    return report


if __name__ == "__main__":
    result=study()
    print(json.dumps({"configurations":len(result["candidates"]),"qualified":result["selection_eligible_count"],
                      "selected":result["selected_config"],"final":result["final"]}),flush=True)
