"""Confirm one unchanged earlier session diagnostic on complete paired quotes.

No new session parameters, no final observations, and no production orders.
The fixed strategy comes from the disclosed 2015 observed-book diagnostic.
"""
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from research.fxcm_rsi2 import ROOT, sha, inputs, diagnostics
from research.intraday_mean_reversion.session_study import SessionConfig, evaluate

OUT=ROOT/"artifacts/intraday/fxcm_fixed_session"


def study():
    plan=json.loads((OUT/"preregistration.json").read_text())
    if (OUT/"selection_report.json").exists():
        raise RuntimeError("Preserve existing confirmation outcomes")
    origin=ROOT/plan["fixed_config_origin"]
    if sha(origin) != plan["fixed_config_origin_sha256"]:
        raise ValueError("Original diagnostic receipt changed")
    source_path=ROOT/"data/intraday/fxcm_official/eurusd_fixed_session_development_validation_2015_2021_provenance.json"
    provenance=json.loads(source_path.read_text())
    record=provenance["outputs"]["m15"]
    path=ROOT/record["path"]
    if sha(path) != record["sha256"]:
        raise ValueError("Official source candle hash mismatch")
    raw_frame=pd.read_csv(path)
    raw_frame["time"]=pd.to_datetime(raw_frame.time,utc=True)
    if not ((raw_frame.time >= pd.Timestamp("2015-01-01",tz="UTC"))
            & (raw_frame.time < pd.Timestamp("2022-01-01",tz="UTC"))).all():
        raise ValueError("Only registered pre-final observations permitted")
    frame=raw_frame.rename(columns={f"Bid{key.title()}":key for key in ("open","high","low","close")}
                           | {"AskOpen":"ask_open"})
    config=SessionConfig(**{k:v for k,v in plan["fixed_config"].items() if k!="name"})
    hashes={"research/fxcm_fixed_session.py":sha(Path(__file__)),
            "research/intraday_mean_reversion/session_study.py":sha(ROOT/"research/intraday_mean_reversion/session_study.py"),
            "research/intraday_engine.py":sha(ROOT/"research/intraday_engine.py"),
            "research/statistics.py":sha(ROOT/"research/statistics.py"),
            str(path.relative_to(ROOT)):sha(path),str(source_path.relative_to(ROOT)):sha(source_path),
            "preregistration.json":sha(OUT/"preregistration.json")}
    feature_settings=json.loads((ROOT/"artifacts/intraday/fxcm_rsi2/preregistration.json").read_text())["base_signal"]
    features=inputs(raw_frame,feature_settings)["x"]
    rows=[]
    for capital in plan["initial_capitals_usd"]:
        results={}
        name=f"{config.name}_usd{capital}"
        for phase,key in (("development","development"),("validation","selection_validation")):
            start,end=plan[key]
            result=evaluate(frame,config,start=start,end=end,initial_equity=capital,
                            observed_book=True,book_source="Official FXCM public Active Trader indicative paired M1, complete UTC M15 blocks",
                            minimum_eligible_trades=500,blocks=(7,14,28))
            results[phase]=result
        dev,val=results["development"],results["validation"]
        ds,vs=dev["engine_summary"],val["engine_summary"]
        eligible=(ds["eligible_trades"]>=500 and vs["eligible_trades"]>=500
                  and ds["win_rate"]>=.5 and vs["win_rate"]>=.5 and ds["net_profit"]>0 and vs["net_profit"]>0
                  and ds["risk_breaches"]==vs["risk_breaches"]==0)
        row=dict(config={**config.to_dict(),"capital":capital,"minutes":15,"symbol":"EURUSD","operating_name":name},
                 development=ds,validation=vs,development_statistics=dev["summary"],validation_statistics=val["summary"],
                 development_bootstrap=dev["bootstrap"],validation_bootstrap=val["bootstrap"],
                 selection_eligible=bool(eligible),selection_score=min(ds["net_profit"]/capital,vs["net_profit"]/capital))
        for phase,result in results.items():
            quote_trace=ROOT/"data/intraday/fxcm_official"/f"{name}_{phase}_trades.json"
            quote_trace.write_text(json.dumps(result["trades"],indent=2)+"\n")
            trace,comparison=diagnostics(result["trades"],features,name)
            public_path=OUT/f"{name}_{phase}_trade_features.csv"
            trace.to_csv(public_path,index=False,lineterminator="\n")
            if phase=="development":
                (OUT/f"{name}_development_pattern_comparison.json").write_text(json.dumps(comparison,indent=2)+"\n")
            row[phase+"_local_quote_trace_path"]=str(quote_trace.relative_to(ROOT))
            row[phase+"_local_quote_trace_sha256"]=sha(quote_trace)
            row[phase+"_trade_features_path"]=str(public_path.relative_to(ROOT))
            row[phase+"_trade_features_sha256"]=sha(public_path)
        rows.append(row)
        print(json.dumps({"name":name,"dev_n":ds["eligible_trades"],"val_n":vs["eligible_trades"],
                          "dev_net":ds["net_profit"],"val_net":vs["net_profit"],"dev_win":ds["win_rate"],
                          "val_win":vs["win_rate"],"eligible":bool(eligible),
                          "val_bootstrap_lower95":val["bootstrap"]["7"]["mean_daily_return_lower_95_one_sided"]}),flush=True)
    eligible=sorted([r for r in rows if r["selection_eligible"]],key=lambda r:(-r["selection_score"],r["config"]["capital"]))
    selected=eligible[0] if eligible else None
    report=dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),registered_protocol_sha256=sha(OUT/"preregistration.json"),
                code_data_hashes=hashes,candidates=rows,selection_eligible_count=len(eligible),
                selected_config=selected["config"] if selected else None,final="UNTOUCHED; one unchanged configuration only",
                paper_approved=False,source_evaluations=2,new_operating_parameter_configs=0,limitations=plan["source_limits"])
    if selected:
        freeze=dict(frozen_at_utc=datetime.now(timezone.utc).isoformat(),config=selected["config"],code_data_hashes=hashes,
                    registered_protocol_sha256=sha(OUT/"preregistration.json"),final_outcomes_evaluated=False,
                    development=selected["development"],validation=selected["validation"])
        (OUT/"selected_strategy_freeze.json").write_text(json.dumps(freeze,indent=2)+"\n")
    (OUT/"selection_report.json").write_text(json.dumps(report,indent=2)+"\n")
    return report


if __name__ == "__main__":
    result=study()
    print(json.dumps({"source_evaluations":len(result["candidates"]),"qualified":result["selection_eligible_count"],
                      "selected":result["selected_config"],"final":result["final"]}),flush=True)
