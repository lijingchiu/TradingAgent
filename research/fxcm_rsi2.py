"""Pre-registered RSI2 study and development-only stop-pattern refinement.

Run development/selection, never reserved final prices, with:
    python -m research.fxcm_rsi2
Pattern filters are fitted and serialized before any validation outcome runs.
The production paper ledger is neither read nor written.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.tree import DecisionTreeRegressor

from research.intraday_engine import run_intraday_backtest
from research.statistics import summarize_trades
from trading_agent.risk import CostModel

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts/intraday/fxcm_rsi2"
FEATURES = ["atr_pips", "atr_fast_slow_ratio", "ema_slope_atr", "distance_from_ema_atr",
            "zscore20", "completed_bar_body_fraction", "current_quote_spread_pips", "current_quote_hour_utc"]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inputs(frame: pd.DataFrame, settings: dict) -> dict:
    """At execution row i, feature prices stop at completed row i-1.

    Only the current observed spread and clock are contemporaneous entry
    features. No current bar high, low, or close enters the feature vector.
    RSI and ATR use trading observations across gaps, without fabricating bars.
    """
    time = pd.to_datetime(frame.time, utc=True)
    if not time.is_monotonic_increasing or time.duplicated().any():
        raise ValueError("Sorted unique UTC bars required")
    close = frame.BidClose.astype(float)
    previous = close.shift(1)
    change = close.diff()
    gain = change.clip(lower=0).ewm(alpha=1/settings["rsi_period"], adjust=False,
                                  min_periods=settings["rsi_period"]).mean()
    loss = (-change).clip(lower=0).ewm(alpha=1/settings["rsi_period"], adjust=False,
                                     min_periods=settings["rsi_period"]).mean()
    rsi = 100*gain/(gain+loss)
    rsi = rsi.mask((gain+loss == 0) & gain.notna(), 50.)
    tr = pd.concat([frame.BidHigh-frame.BidLow, (frame.BidHigh-previous).abs(),
                    (frame.BidLow-previous).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1/settings["atr_period"], adjust=False, min_periods=settings["atr_period"]).mean()
    slow = tr.ewm(alpha=1/settings["atr_slow_period"], adjust=False, min_periods=settings["atr_slow_period"]).mean()
    ema = close.ewm(span=settings["ema_period"], adjust=False, min_periods=settings["ema_period"]).mean()
    mean = close.rolling(settings["zscore_period"]).mean()
    sd = close.rolling(settings["zscore_period"]).std(ddof=0).replace(0, np.nan)
    completed = pd.DataFrame({
        "atr_pips": atr/.0001,
        "atr_fast_slow_ratio": atr/slow.replace(0, np.nan),
        "ema_slope_atr": (ema-ema.shift(settings["ema_slope_bars"]))/slow.replace(0, np.nan),
        "distance_from_ema_atr": (close-ema)/slow.replace(0, np.nan),
        "zscore20": (close-mean)/sd,
        "completed_bar_body_fraction": (close-frame.BidOpen)/(frame.BidHigh-frame.BidLow).replace(0, np.nan),
    }).shift(1)
    spread = (frame.AskOpen-frame.BidOpen)/.0001
    completed["current_quote_spread_pips"] = spread
    completed["current_quote_hour_utc"] = time.dt.hour+time.dt.minute/60
    x = completed[FEATURES].to_numpy(float)
    ready = np.arange(len(frame)) >= settings["minimum_warmup_trading_bars"]
    entries = (ready & (rsi <= settings["rsi_max"])
               & (atr/.0001 >= settings["minimum_atr_pips"])).to_numpy(bool)
    hours = settings["entry_hours_utc"]
    allowed = ((time.dt.hour >= hours[0]) & (time.dt.hour < hours[1])
               & (spread >= 0) & (spread <= settings["maximum_entry_spread_pips"])).to_numpy(bool)
    allowed &= np.isfinite(x).all(axis=1)
    return dict(time=time, epoch=(time.astype("int64")//1_000_000_000).to_numpy(np.int64),
                entries=entries, exits=(rsi >= settings["exit_rsi_at_least"]).fillna(False).to_numpy(bool),
                stop=(atr*settings["stop_atr"]).to_numpy(float),
                target=(atr*settings["target_atr"]).to_numpy(float), x=x, allowed=allowed)


def fit_filter(x: np.ndarray, trades: list[dict], depth: int, plan: dict) -> dict:
    natural = [t for t in trades if t["reason"] != "sample_end"]
    minimum = plan["pattern_learning"]["minimum_samples_per_leaf"]
    if len(natural) < minimum:
        return dict(depth=depth, disabled=True, reason="Too few natural development trades for a leaf", nodes=[], eligible_leaves=[])
    indices = np.array([t["entry_index"] for t in natural], dtype=int)
    y = np.array([t["net_pnl"]/t["units"]/.0001 for t in natural], dtype=float)
    samples = x[indices]
    if not np.isfinite(samples).all():
        raise ValueError("Pattern learning cannot use missing entry features")
    regressor = DecisionTreeRegressor(max_depth=depth, min_samples_leaf=minimum,
                                     random_state=plan["pattern_learning"]["random_state"])
    regressor.fit(samples, y)
    tree = regressor.tree_
    leaf_ids = regressor.apply(samples)
    nodes = []
    for i in range(tree.node_count):
        nodes.append(dict(left=int(tree.children_left[i]), right=int(tree.children_right[i]),
                          feature=int(tree.feature[i]), threshold=float(tree.threshold[i]),
                          training_samples=int(tree.n_node_samples[i]), expected_net_pips=float(tree.value[i,0,0])))
    leaves, eligible = {}, []
    for leaf in np.unique(leaf_ids):
        mask = leaf_ids == leaf
        wins = float((y[mask] > 0).mean())
        stops = float(np.mean([natural[i]["reason"] in ("stop", "stop_gap") for i in np.flatnonzero(mask)]))
        leaves[str(int(leaf))] = dict(trades=int(mask.sum()), win_rate=wins,
                                     stop_rate=stops, mean_net_pips=float(y[mask].mean()))
        if y[mask].mean() > 0 and wins >= .5:
            eligible.append(int(leaf))
    result = dict(depth=depth, disabled=False, features=FEATURES, nodes=nodes,
                  leaf_training_diagnostics=leaves, eligible_leaves=eligible,
                  fit_period="2017 only", training_natural_trades=len(natural),
                  evidence_role="Exploratory development patterns; validation not yet evaluated")
    # Explicit numeric serialization must match sklearn, including float32
    # input coercion at threshold comparisons. No pickle/code deserialization.
    if not np.array_equal(apply_leaves(samples, result), leaf_ids):
        raise ValueError("Serialized tree does not reproduce sklearn leaves")
    return result


def apply_leaves(x: np.ndarray, model: dict) -> np.ndarray:
    if model["disabled"]:
        return np.full(len(x), -1, dtype=int)
    result = np.full(len(x), -1, dtype=int)
    finite = np.isfinite(x).all(axis=1)
    samples = x.astype(np.float32)
    for i in np.flatnonzero(finite):
        node = 0
        while model["nodes"][node]["left"] != -1:
            info = model["nodes"][node]
            node = info["left"] if samples[i,info["feature"]] <= info["threshold"] else info["right"]
        result[i] = node
    return result


def pattern_mask(x: np.ndarray, model: dict) -> np.ndarray:
    return np.isin(apply_leaves(x, model), model["eligible_leaves"])


def simulate(frame, arrays, plan, minutes, capital, first, last, mask=None, multiplier=1.):
    costs = plan["baseline_costs"].copy()
    for field in ("slippage_pips", "commission_bps", "minimum_commission"):
        costs[field] *= multiplier
    allowed = arrays["allowed"] if mask is None else (arrays["allowed"] & mask)
    # Placeholder at crossed opens is never executable: allowed is false
    # there. Retain the real BID candle so existing positions can still exit.
    asks = np.maximum(frame.AskOpen.to_numpy(float), frame.BidOpen.to_numpy(float))
    result = run_intraday_backtest(
        arrays["epoch"], *[frame[f"Bid{key}"].to_numpy(float) for key in ("Open", "High", "Low", "Close")],
        arrays["entries"], arrays["stop"], arrays["target"], exit_signals=arrays["exits"],
        entry_allowed=allowed, start_index=first, end_index=last,
        max_holding_bars=plan["base_signal"]["max_holding_observed_bars"],
        max_holding_days=plan["base_signal"]["max_holding_days"], initial_equity=capital,
        costs=CostModel(**costs), quote_kind="bid", ask_opens=asks,
        observed_spread_multiplier=multiplier, max_signal_age_seconds=minutes*60,
        book_source="FXCM official public indicative Active Trader BID/ASK M1 aggregated complete blocks")
    result["inspectible_statistics"] = summarize_trades(result["trades"])
    return result


def diagnostics(trades, x, name: str):
    records = []
    for trade in trades:
        if trade["reason"] == "sample_end":
            continue
        row = dict(variant=name, entry_time=datetime.fromtimestamp(trade["entry_time"], timezone.utc).isoformat(),
                   exit_time=datetime.fromtimestamp(trade["exit_time"], timezone.utc).isoformat(),
                   entry_index=trade["entry_index"], reason=trade["reason"], net_pnl=trade["net_pnl"],
                   net_pips=trade["net_pnl"]/trade["units"]/.0001,
                   stopped=trade["reason"] in ("stop", "stop_gap"), won=trade["net_pnl"] > 0,
                   holding_seconds=trade["exit_time"]-trade["entry_time"])
        row.update(zip(FEATURES, map(float, x[trade["entry_index"]])))
        records.append(row)
    frame = pd.DataFrame(records)
    comparisons = []
    if not frame.empty:
        for key in FEATURES:
            boundaries = np.unique(frame[key].quantile([0,.25,.5,.75,1]).to_numpy())
            if len(boundaries) < 2:
                continue
            labels = pd.cut(frame[key], boundaries, include_lowest=True, duplicates="drop")
            for label, group in frame.groupby(labels, observed=True):
                comparisons.append(dict(feature=key, development_bin=str(label), trades=len(group),
                                        stop_rate=float(group.stopped.mean()), win_rate=float(group.won.mean()),
                                        mean_net_pips=float(group.net_pips.mean()), net_pnl=float(group.net_pnl.sum())))
    return frame, comparisons


def study() -> dict:
    plan = json.loads((OUT/"preregistration.json").read_text())
    if plan["pattern_learning"]["features"] != FEATURES:
        raise ValueError("Feature names must match preregistration")
    if (OUT/"selection_report.json").exists():
        raise RuntimeError("Study already evaluated: use a separate documented reproduction directory; preserve outcomes")
    provenance_path = ROOT/"data/intraday/fxcm_official/eurusd_development_validation_2017_2021_provenance.json"
    provenance = json.loads(provenance_path.read_text())
    datasets, models, prepared = {}, {}, []
    hashes = {str(Path(__file__).relative_to(ROOT)): sha(Path(__file__)),
              "research/intraday_engine.py": sha(ROOT/"research/intraday_engine.py"),
              "research/statistics.py": sha(ROOT/"research/statistics.py"),
              "research/fxcm_data.py": sha(ROOT/"research/fxcm_data.py"),
              "preregistration.json": sha(OUT/"preregistration.json"),
              str(provenance_path.relative_to(ROOT)): sha(provenance_path)}
    for minutes in plan["timeframes_minutes"]:
        record = provenance["outputs"][f"m{minutes}"]
        path = ROOT/record["path"]
        if sha(path) != record["sha256"]:
            raise ValueError("Candles do not match source-quality provenance hash")
        frame = pd.read_csv(path)
        arrays = inputs(frame, plan["base_signal"])
        if not ((arrays["time"] >= pd.Timestamp("2017-01-01", tz="UTC"))
                & (arrays["time"] < pd.Timestamp("2022-01-01", tz="UTC"))).all():
            raise ValueError("Reserved final or unexpected dates cannot enter selection study")
        split = int(arrays["time"].searchsorted(pd.Timestamp("2018-01-01", tz="UTC")))
        datasets[minutes] = (frame, arrays, split)
        hashes[record["path"]] = sha(path)
        for capital in plan["initial_capitals_usd"]:
            base = f"rsi2_m{minutes}_usd{capital}"
            dev = simulate(frame, arrays, plan, minutes, capital, 0, split)
            trade_frame, comparisons = diagnostics(dev["trades"], arrays["x"], base)
            trace_path = OUT/f"{base}_development_trade_features.csv"
            trade_frame.to_csv(trace_path, index=False, lineterminator="\n")
            (OUT/f"{base}_development_pattern_comparison.json").write_text(json.dumps(comparisons, indent=2)+"\n")
            prepared.append(dict(name=base+"_unfiltered", minutes=minutes, capital=capital, model_name=None,
                                 development=dev, mask=None))
            for depth in plan["pattern_learning"]["max_depths"]:
                name = base+f"_stop_pattern_tree_depth{depth}"
                model = fit_filter(arrays["x"], dev["trades"], depth, plan)
                model["training_trade_features_sha256"] = sha(trace_path)
                models[name] = model
                mask = pattern_mask(arrays["x"], model)
                refined = simulate(frame, arrays, plan, minutes, capital, 0, split, mask)
                prepared.append(dict(name=name, minutes=minutes, capital=capital, model_name=name,
                                     development=refined, mask=mask))
            print(json.dumps({"phase":"development","base":base,"trades":dev["summary"]["eligible_trades"],
                              "net":dev["summary"]["net_profit"],"net_win_rate":dev["summary"]["win_rate"]}),flush=True)
    # This durable lock must precede the first validation backtest.
    lock = dict(locked_at_utc=datetime.now(timezone.utc).isoformat(), models=models, hashes=hashes,
                all_filters_fit_on="2017 development natural trades only",
                validation_outcomes_evaluated=False, final_outcomes_evaluated=False)
    lock_path = OUT/"development_pattern_lock.json"
    if lock_path.exists():
        raise RuntimeError("Refuse to overwrite a locked pattern model")
    lock_path.write_text(json.dumps(lock, indent=2)+"\n")
    rows = []
    for candidate in prepared:
        frame, arrays, split = datasets[candidate["minutes"]]
        val = simulate(frame, arrays, plan, candidate["minutes"], candidate["capital"], split, len(frame), candidate["mask"])
        dev = candidate["development"]
        ds, vs = dev["summary"], val["summary"]
        criteria = plan["selection_criteria"]
        eligible = (ds["eligible_trades"] >= criteria["minimum_development_natural_trades"]
                    and vs["eligible_trades"] >= criteria["minimum_validation_natural_trades"]
                    and ds["net_profit"] > 0 and vs["net_profit"] > 0
                    and ds["win_rate"] >= .5 and vs["win_rate"] >= .5
                    and ds["risk_breaches"] == vs["risk_breaches"] == 0)
        row = dict(config={k:candidate[k] for k in ("name","minutes","capital","model_name")},
                   development=ds, validation=vs,
                   development_statistics=dev["inspectible_statistics"],
                   validation_statistics=val["inspectible_statistics"],
                   selection_eligible=bool(eligible),
                   selection_score=min(ds["net_profit"]/candidate["capital"], vs["net_profit"]/candidate["capital"]))
        for phase, result in (("development",dev),("validation",val)):
            # Full quote-bearing execution traces remain local and ignored.
            # Publish entry-time diagnostics without redistributing raw quotes.
            path = ROOT/"data/intraday/fxcm_official"/f'{candidate["name"]}_{phase}_trades.json'
            path.write_text(json.dumps(result["trades"],indent=2)+"\n")
            public_path = OUT/f'{candidate["name"]}_{phase}_trade_features.csv'
            trace, _ = diagnostics(result["trades"], arrays["x"], candidate["name"])
            trace.to_csv(public_path,index=False,lineterminator="\n")
            row[phase+"_local_quote_trace_path"] = str(path.relative_to(ROOT))
            row[phase+"_local_quote_trace_sha256"] = sha(path)
            row[phase+"_trade_features_path"] = str(public_path.relative_to(ROOT))
            row[phase+"_trade_features_sha256"] = sha(public_path)
        rows.append(row)
        print(json.dumps({"phase":"validation","name":candidate["name"],"dev_n":ds["eligible_trades"],
                          "val_n":vs["eligible_trades"],"dev_net":ds["net_profit"],"val_net":vs["net_profit"],
                          "dev_win":ds["win_rate"],"val_win":vs["win_rate"],"eligible":bool(eligible)}),flush=True)
    qualified = sorted([r for r in rows if r["selection_eligible"]],
                       key=lambda r:(-r["selection_score"],-r["validation"]["net_profit"]/r["config"]["capital"],r["config"]["name"]))
    selected = qualified[0] if qualified else None
    report = dict(registered_protocol_sha256=sha(OUT/"preregistration.json"),
                  pattern_lock_sha256=sha(lock_path),completed_at_utc=datetime.now(timezone.utc).isoformat(),
                  candidates=rows,selection_eligible_count=len(qualified),selected_config=selected["config"] if selected else None,
                  final="UNTOUCHED; no alternative may be selected on final outcomes",
                  paper_approved=False, pattern_learning_scope="2017 development only",
                  limitations=plan["source_limitations"]+["Stop/winner comparisons are exploratory, not causal proofs",
                                                        "Earlier calendar-period research and all 12 new configurations are disclosed"])
    if selected:
        freeze = dict(frozen_at_utc=datetime.now(timezone.utc).isoformat(),config=selected["config"],
                      model=models.get(selected["config"]["model_name"]),plan_sha256=sha(OUT/"preregistration.json"),
                      pattern_lock_sha256=sha(lock_path),code_data_hashes=hashes,final_outcomes_evaluated=False,
                      development=selected["development"],validation=selected["validation"])
        (OUT/"selected_strategy_freeze.json").write_text(json.dumps(freeze,indent=2)+"\n")
    (OUT/"selection_report.json").write_text(json.dumps(report,indent=2)+"\n")
    return report


if __name__ == "__main__":
    report=study()
    print(json.dumps({"configurations":len(report["candidates"]),"qualified":report["selection_eligible_count"],
                      "selected":report["selected_config"],"final":report["final"]}),flush=True)
