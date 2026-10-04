"""Pre-registered replication on GBPUSD/NZDUSD, not more parameter tuning.

Uses the unchanged base and tailguard hypotheses. Every learned filter is
locked using each instrument's 2017 development trades before the first new
selection-validation backtest. Only one global winner may reach final data.
"""
from datetime import datetime, timezone
import json
from pathlib import Path

import pandas as pd

from research.fxcm_rsi2 import ROOT, inputs, simulate, diagnostics, sha, fit_filter, pattern_mask
from research.fxcm_rsi2_tailguard import signal_inputs

OUT = ROOT/"artifacts/intraday/fxcm_rsi2_cross_asset"


def study():
    plan=json.loads((OUT/"preregistration.json").read_text())
    if (OUT/"selection_report.json").exists():
        raise RuntimeError("Preserve completed outcomes; no silent overwrite")
    protocols={}
    for kind,key in (("patterns","base_protocol"),("tailguard","tail_protocol")):
        path=ROOT/plan[key]
        if sha(path) != plan[key+"_sha256"]:
            raise ValueError("Replication protocol changed after preregistration")
        protocols[kind]=json.loads(path.read_text())
    hashes={"research/fxcm_rsi2_cross_asset.py":sha(Path(__file__)),
            "research/fxcm_rsi2.py":sha(ROOT/"research/fxcm_rsi2.py"),
            "research/fxcm_rsi2_tailguard.py":sha(ROOT/"research/fxcm_rsi2_tailguard.py"),
            "research/intraday_engine.py":sha(ROOT/"research/intraday_engine.py"),
            "research/statistics.py":sha(ROOT/"research/statistics.py"),
            "preregistration.json":sha(OUT/"preregistration.json")}
    prepared,models,datasets=[],{},{}
    for symbol in plan["symbols"]:
        source_path=ROOT/f"data/intraday/fxcm_official/{symbol.lower()}_development_validation_2017_2021_provenance.json"
        source=json.loads(source_path.read_text())
        hashes[str(source_path.relative_to(ROOT))]=sha(source_path)
        for minutes in protocols["patterns"]["timeframes_minutes"]:
            record=source["outputs"][f"m{minutes}"]
            path=ROOT/record["path"]
            if sha(path) != record["sha256"]:
                raise ValueError("Candles differ from official-source-quality hash")
            frame=pd.read_csv(path)
            arrays=inputs(frame,protocols["patterns"]["base_signal"])
            if not ((arrays["time"] >= pd.Timestamp("2017-01-01",tz="UTC"))
                    & (arrays["time"] < pd.Timestamp("2022-01-01",tz="UTC"))).all():
                raise ValueError("Reserved final timestamps cannot enter selection")
            split=int(arrays["time"].searchsorted(pd.Timestamp("2018-01-01",tz="UTC")))
            datasets[(symbol,minutes)]=(frame,split)
            hashes[record["path"]]=sha(path)
            for capital in protocols["patterns"]["initial_capitals_usd"]:
                base=f"{symbol.lower()}_rsi2_m{minutes}_usd{capital}"
                dev=simulate(frame,arrays,protocols["patterns"],minutes,capital,0,split)
                trace,_=diagnostics(dev["trades"],arrays["x"],base)
                training_path=OUT/f"{base}_development_training_features.csv"
                trace.to_csv(training_path,index=False,lineterminator="\n")
                prepared.append(dict(config=dict(name=base+"_unfiltered",symbol=symbol,minutes=minutes,capital=capital,
                                                  family="patterns",variant="unfiltered",model_name=None),
                                     arrays=arrays,mask=None,development=dev))
                for depth in protocols["patterns"]["pattern_learning"]["max_depths"]:
                    name=base+f"_stop_pattern_tree_depth{depth}"
                    model=fit_filter(arrays["x"],dev["trades"],depth,protocols["patterns"])
                    model["training_trade_features_sha256"]=sha(training_path)
                    models[name]=model
                    mask=pattern_mask(arrays["x"],model)
                    refined=simulate(frame,arrays,protocols["patterns"],minutes,capital,0,split,mask)
                    prepared.append(dict(config=dict(name=name,symbol=symbol,minutes=minutes,capital=capital,
                                                      family="patterns",variant=f"stop_pattern_tree_depth{depth}",model_name=name),
                                         arrays=arrays,mask=mask,development=refined))
                for variant in protocols["tailguard"]["variants_per_base"]:
                    new_arrays=signal_inputs(frame,protocols["tailguard"],variant)
                    name=base+"_"+variant
                    dev=simulate(frame,new_arrays,protocols["tailguard"],minutes,capital,0,split)
                    prepared.append(dict(config=dict(name=name,symbol=symbol,minutes=minutes,capital=capital,
                                                      family="tailguard",variant=variant,model_name=None),
                                         arrays=new_arrays,mask=None,development=dev))
                print(json.dumps({"phase":"development","symbol":symbol,"minutes":minutes,"capital":capital,
                                  "prepared_configs":len(prepared)}),flush=True)
    if len(prepared) != plan["total_configurations"]:
        raise ValueError("Prepared candidate count differs from registered replication")
    lock=dict(locked_at_utc=datetime.now(timezone.utc).isoformat(),models=models,hashes=hashes,
              all_filters_fit_on="Each instrument's 2017 development natural trades only",
              new_selection_validation_outcomes_evaluated=False,final_outcomes_evaluated=False)
    lock_path=OUT/"development_pattern_lock.json"
    if lock_path.exists():
        raise RuntimeError("Refuse overwrite of locked models")
    lock_path.write_text(json.dumps(lock,indent=2)+"\n")
    rows=[]
    for candidate in prepared:
        config=candidate["config"]
        symbol,minutes,capital=config["symbol"],config["minutes"],config["capital"]
        frame,split=datasets[(symbol,minutes)]
        protocol=protocols[config["family"]]
        dev=candidate["development"]
        val=simulate(frame,candidate["arrays"],protocol,minutes,capital,split,len(frame),candidate["mask"])
        ds,vs=dev["summary"],val["summary"]
        criteria=protocol["selection_criteria"]
        eligible=(ds["eligible_trades"] >= criteria["minimum_development_natural_trades"]
                  and vs["eligible_trades"] >= criteria["minimum_validation_natural_trades"]
                  and ds["net_profit"]>0 and vs["net_profit"]>0 and ds["win_rate"]>=.5 and vs["win_rate"]>=.5
                  and ds["risk_breaches"]==vs["risk_breaches"]==0)
        row=dict(config=config,development=ds,validation=vs,
                 development_statistics=dev["inspectible_statistics"],validation_statistics=val["inspectible_statistics"],
                 selection_eligible=bool(eligible),selection_score=min(ds["net_profit"]/capital,vs["net_profit"]/capital))
        for phase,result in (("development",dev),("validation",val)):
            trace_path=OUT/f'{config["name"]}_{phase}_trade_features.csv'
            trace,comparison=diagnostics(result["trades"],candidate["arrays"]["x"],config["name"])
            trace.to_csv(trace_path,index=False,lineterminator="\n")
            if phase=="development":
                (OUT/f'{config["name"]}_development_pattern_comparison.json').write_text(json.dumps(comparison,indent=2)+"\n")
            raw_path=ROOT/"data/intraday/fxcm_official"/f'{config["name"]}_{phase}_trades.json'
            raw_path.write_text(json.dumps(result["trades"],indent=2)+"\n")
            row[phase+"_trade_features_path"]=str(trace_path.relative_to(ROOT))
            row[phase+"_trade_features_sha256"]=sha(trace_path)
            row[phase+"_local_quote_trace_path"]=str(raw_path.relative_to(ROOT))
            row[phase+"_local_quote_trace_sha256"]=sha(raw_path)
        rows.append(row)
        print(json.dumps({"phase":"validation","name":config["name"],"dev_n":ds["eligible_trades"],"val_n":vs["eligible_trades"],
                          "dev_net":ds["net_profit"],"val_net":vs["net_profit"],"dev_win":ds["win_rate"],
                          "val_win":vs["win_rate"],"eligible":bool(eligible)}),flush=True)
    qualified=sorted([r for r in rows if r["selection_eligible"]],
                     key=lambda r:(-r["selection_score"],-r["validation"]["net_profit"]/r["config"]["capital"],r["config"]["name"]))
    selected=qualified[0] if qualified else None
    report=dict(completed_at_utc=datetime.now(timezone.utc).isoformat(),
                registered_protocol_sha256=sha(OUT/"preregistration.json"),pattern_lock_sha256=sha(lock_path),
                candidates=rows,selection_eligible_count=len(qualified),selected_config=selected["config"] if selected else None,
                final="UNTOUCHED; one global configuration only",paper_approved=False,
                limitations=protocols["patterns"]["source_limitations"]+[plan["independence_note"]])
    if selected:
        freeze=dict(frozen_at_utc=datetime.now(timezone.utc).isoformat(),config=selected["config"],
                    model=models.get(selected["config"]["model_name"]),protocol=protocols[selected["config"]["family"]],
                    registered_replication_sha256=sha(OUT/"preregistration.json"),pattern_lock_sha256=sha(lock_path),
                    code_data_hashes=hashes,final_outcomes_evaluated=False,
                    development=selected["development"],validation=selected["validation"])
        (OUT/"selected_strategy_freeze.json").write_text(json.dumps(freeze,indent=2)+"\n")
    (OUT/"selection_report.json").write_text(json.dumps(report,indent=2)+"\n")
    return report


if __name__ == "__main__":
    result=study()
    print(json.dumps({"configurations":len(result["candidates"]),"qualified":result["selection_eligible_count"],
                      "selected":result["selected_config"],"final":result["final"]}),flush=True)
