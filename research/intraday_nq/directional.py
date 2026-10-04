"""Fixed bidirectional NQ trend rules with a separate genuine futures engine.

Only development and validation are executable here. Research includes true
short liabilities, which are unbounded in possible future price paths; it does
not authorize production/paper futures activation or a guaranteed loss limit.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd

from .study import (SOURCE, COMMIT, CAPITAL, PROFILES, sha256, write_json,
                    load_selection_source, assert_daily_flat_coverage, session_arrays)
from .momentum import SPLITS, complete_session_masks


OUT = Path("artifacts/intraday/nq_directional")
EXTENSION = Path("artifacts/intraday/futures_directional_extension.json")
ADDITIONAL_RESERVE = Path("artifacts/intraday/futures_additional_reserved_protocol.json")


def candidates() -> list[dict]:
    return [{"name": f"nq_m5_directional_h{h}_ema{span}_{style}_s{stop}_t{target}",
             "horizon": h, "ema_span": span, "style": style,
             "stop_points": stop, "target_points": target}
            for h in (6, 24) for span in (48, 192) for style in ("momentum", "pullback")
            for stop, target in ((40, 40), (40, 60), (60, 60))]


def futures_api():
    # Imports happen only after the separately audited engine/statistics exist.
    from research.futures_engine import run_futures_backtest
    from research.futures_statistics import summarize_futures_trades
    return run_futures_backtest, summarize_futures_trades


def software_paths() -> dict[str, Path]:
    return {"directional_sha256": Path(__file__),
            "shared_nq_study_sha256": Path("research/intraday_nq/study.py"),
            "shared_nq_momentum_sha256": Path("research/intraday_nq/momentum.py"),
            "futures_engine_sha256": Path("research/futures_engine.py"),
            "futures_statistics_sha256": Path("research/futures_statistics.py")}


def preregister() -> dict:
    if (OUT / "preregistration.json").exists() or (OUT / "development_report.json").exists():
        raise ValueError("Preserve prior directional registration/results")
    engine, stats = futures_api()
    if not EXTENSION.exists() or not ADDITIONAL_RESERVE.exists():
        raise ValueError("Joint directional extension must precede new P&L")
    plan = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "written_before_any_nq_directional_pnl": True,
        "joint_directional_extension": {"path": str(EXTENSION), "sha256": sha256(EXTENSION)},
        "supplementary_reserved_protocol": {"path": str(ADDITIONAL_RESERVE), "sha256": sha256(ADDITIONAL_RESERVE),
                    "scope": "Source QA only; apply same frozen full-session rules; no supplementary strategy features/counts/outcomes inspected before joint freeze"},
        "hypothesis": "Symmetric long/short trend momentum or trend pullback using one predeclared rule per completed bar; no direction chosen from future results",
        "source": {"path": str(SOURCE), "sha256": sha256(SOURCE),
                   "pinned_commit": COMMIT,
                   "url": f"https://raw.githubusercontent.com/axb0306/cme-futures-ohlc/{COMMIT}/NQ/NQ_5min_20260120_20260415.csv",
                   "instrument": "Actual NQ native M5, not MNQ proxy",
                   "price_side": "Last-trade OHLC, modeled mid proxy with assumed spread/slippage",
                   "timestamp_timezone": "Source-declared UTC; bar-opening label assumption independently unverified",
                   "historical_contract_identity": "Updater requests CON.F.US.ENQ.M26; initial backfill expiry/roll unverified",
                   "source_quality_receipt": "artifacts/intraday/nq/source_quality_receipt.json",
                   "source_quality_receipt_sha256": sha256(Path("artifacts/intraday/nq/source_quality_receipt.json"))},
        "family": candidates(), "signal_configuration_count": 24, "disclosed_cost_operating_variants": 48,
        "splits": SPLITS,
        "calendar": {"timezone": "America/New_York", "session_date": "NY date plus one at/after18:00",
                     "weekdays": "Monday through Friday session dates",
                     "exclude_all_UTC_and_session_March_rows_before_features": True,
                     "complete_sessions_only": "Exact276 native M5 opening timestamps18:00 through16:55; source calendar QA, independent of price outcomes",
                     "known_short_sessions_excluded": ["2026-02-16", "2026-04-03"],
                     "final_incomplete_after_March_removal_excluded": "2026-04-01",
                     "entry_execution_clock": "18:30 through16:15 inclusive",
                     "flat": "Completed16:40 signal exits16:45 open; execution16:45 daily_exit also blocks entry",
                     "missing_flat_reference": "Evaluation blocked before any strategy P&L"},
        "signal": {"long_common": "close[i]>EMA[i] AND EMA[i]>EMA[i-horizon]",
                   "short_common": "close[i]<EMA[i] AND EMA[i]<EMA[i-horizon]",
                   "momentum_long": "Additionally close[i]>close[i-horizon]",
                   "momentum_short": "Additionally close[i]<close[i-horizon]",
                   "pullback_long": "Additionally close[i-1]<close[i-2] AND close[i]>close[i-1]",
                   "pullback_short": "Additionally close[i-1]>close[i-2] AND close[i]<close[i-1]",
                   "signal_encoding": "+1 long, -1 short, 0 flat; common regimes mutually exclusive",
                   "completed_bar": "Every EMA/return/confirmation uses observations at or before completed signal bar i",
                   "EMA": "adjust=False, min_periods=span",
                   "warmup": "span+horizon consecutive observations:54/72/198/216 by configuration",
                   "reset": "Every non300second timestamp interval; no cross-maintenance/weekend/roll indicators",
                   "execution": "First next M5 open, signal maximum age300seconds; one position; no same-bar close/reopen",
                   "max_holding_bars": 12, "max_holding_days": 1,
                   "stop_target": "Directional distances around input entry last-trade open; long stopbelow/targetabove, short stopabove/targetbelow",
                   "opening_gaps": "Actual observed open, unclipped",
                   "ambiguous_stop_and_target": "Adverse stop first",
                   "sample_end": "Include costs/P&L in account; exclude artificial exits from natural count/win rate"},
        "costs": {"profiles": {p: asdict(c) for p, c in PROFILES.items()},
                  "flat_fee_per_contract_per_side": {"operating_fixed_5_per_side": 5., "conservative_bps_proxy": None},
                  "operating_profile": "operating_fixed_5_per_side",
                  "last_trade_proxy_side_friction": "+/-0.50points from halfspread0.25 + each-side slip0.25; quartertick valid",
                  "long": "Buy entry+0.50, sell exit-0.50",
                  "short": "Sell entry-0.50, buy-cover exit+0.50",
                  "fee_guard": "Exactly1 NQ contract; flat USD5 each side=USD10 roundtrip",
                  "broker_fee_schedule_verified": False,
                  "final_stress_if_later_authorized": [1.5, 2.0],
                  "stress_rounding": "Round side friction up to0.25tick; scale every explicit flat or bps fee"},
        "risk": {"virtual_initial_equity_usd": CAPITAL, "contract_multiplier_usd_per_point": 20,
                 "contracts_per_trade": 1, "numeric_notional_reserve_cap_fraction": .008,
                 "reserve_cap_basis": "0.8percent of min(initial equity,current entry equity); reference reserve is conservative for both sides",
                 "one_position": True, "no_margin_or_financing_schedule_verified": True,
                 "modeled_trade_checks": "Adverse excursion and peak-to-trough drawdown versus entry equity<=1percent, using a conservative OHLC envelope",
                 "intrabar_risk_envelope": "Reachable favorable pre-exit mark capped at target, then adverse before modeled exit; conservative envelope, not observed tick ordering",
                 "modeled_breach": "Preserve uncapped loss/risk record; halt subsequent new entries after a modeled1percent breach",
                 "short_all_path_liability": "UNBOUNDED: notional reserve or observed stops do not cap all possible upward gaps",
                 "derivative_all_path_loss_bound_established": False,
                 "paper_live_activation": False},
        "selection": {"financial_eligibility_each_split": "Natural count>0;net win fraction>=0.50;positive natural and account net;zero observed1percent breaches",
                      "rank_cost_profile": "operating_fixed_5_per_side",
                      "score": "Minimum development/validation MEAN NATURAL net P&L / initial equity",
                      "tie_breakers": ["Maximum validation total net return", "Stable candidate name ascending"],
                      "projection": "Natural selection count*36/27 from27 selection to36 total complete sessions; threshold375 for projected500",
                      "projection_is_observed_final_count": False,
                      "projection_is_rank_filter": False,
                      "joint_rank_scope": "All financially eligible OPERATING rows across assets; projection retained as a separate diagnostic",
                      "literal_user_count": "500 TOTAL natural closes from same frozen strategy across declared splits",
                      "preferred_final_independent_natural_count": 500,
                      "no_adaptive_params": True,
                      "final_requires_immutable_joint_selection_and_root_authorization": True},
        "statistics": {"separate_direction_aware_module": "research/futures_statistics.py; no inverted prices or units passed into old long-only statistics",
                       "wilson": "95percent descriptive independence-assumption interval",
                       "final_bootstrap_if_later_authorized": {"unit": "UTC daily realized account returns using previous realized equity, zero calendar days retained",
                         "block_calendar_days": 7, "replications": 10000, "seed": 20261004,
                         "sensitivity_blocks": [14, 28]}},
        "software": {field: sha256(path) for field, path in software_paths().items()},
        "interfaces": {"engine": str(inspect.signature(engine)), "statistics": str(inspect.signature(stats))},
        "limitations": ["Research only; no broker/live/paper gate activation.",
                        "Short liabilities are unbounded across possible future paths; observed<=1percent is not a mathematical future guarantee.",
                        "Third-party last-trade source, historical expiry, timestamp label, bid/ask fills and broker fees remain independently unverified.",
                        "Virtual equity is an exposure-model parameter and does not certify an exchange margin account.",
                        "Earlier48 NQ signal configs/96 cost variants remain unchanged; this adds24 configs/48 variants."]}
    write_json(OUT / "preregistration.json", plan)
    return plan


def read_plan() -> dict:
    plan = json.loads((OUT / "preregistration.json").read_text())
    if not plan["written_before_any_nq_directional_pnl"] or plan["family"] != candidates():
        raise ValueError("Unchanged complete directional preregistration required")
    for field, path in software_paths().items():
        if plan["software"][field] != sha256(path):
            raise ValueError("Preregistered software changed: " + field)
    if (plan["source"]["sha256"] != sha256(SOURCE)
            or plan["joint_directional_extension"]["sha256"] != sha256(EXTENSION)
            or plan["supplementary_reserved_protocol"]["sha256"] != sha256(ADDITIONAL_RESERVE)):
        raise ValueError("Preregistered source/extension changed")
    engine, stats = futures_api()
    if plan["interfaces"] != {"engine": str(inspect.signature(engine)), "statistics": str(inspect.signature(stats))}:
        raise ValueError("Preregistered engine/statistics interface changed")
    return plan


def causal_signals(frame: pd.DataFrame, config: dict) -> dict:
    n = len(frame)
    directions = np.zeros(n, dtype=np.int8)
    ema_values = np.full(n, np.nan)
    slope_values = np.full(n, np.nan)
    horizon_returns = np.full(n, np.nan)
    prior_returns = np.full(n, np.nan)
    times = (frame["time"].astype("int64") // 1_000_000_000).to_numpy(np.int64)
    boundaries = np.r_[0, np.flatnonzero(np.diff(times) != 300) + 1, n]
    for first, last in zip(boundaries[:-1], boundaries[1:]):
        close = frame["close"].iloc[first:last].astype(float).reset_index(drop=True)
        ema = close.ewm(span=config["ema_span"], adjust=False, min_periods=config["ema_span"]).mean()
        slope = ema - ema.shift(config["horizon"])
        change = close / close.shift(config["horizon"]) - 1
        previous = close.shift(1) / close.shift(2) - 1
        long, short = (close > ema) & (slope > 0), (close < ema) & (slope < 0)
        if config["style"] == "momentum":
            long &= change > 0
            short &= change < 0
        elif config["style"] == "pullback":
            long &= (previous < 0) & (close > close.shift(1))
            short &= (previous > 0) & (close < close.shift(1))
        else:
            raise ValueError("Unregistered directional style")
        if (long & short).any():
            raise ValueError("Long and short signals cannot overlap")
        directions[first:last] = np.where(long.fillna(False), 1, np.where(short.fillna(False), -1, 0))
        ema_values[first:last] = ema.to_numpy(float)
        slope_values[first:last] = slope.to_numpy(float)
        horizon_returns[first:last] = change.to_numpy(float)
        prior_returns[first:last] = previous.to_numpy(float)
    return {"direction_signals": directions, "ema": ema_values, "ema_slope": slope_values,
            "horizon_return": horizon_returns, "prior_one_bar_return": prior_returns,
            "stop_distances": np.full(n, config["stop_points"]),
            "target_distances": np.full(n, config["target_points"])}


def run_split(source: pd.DataFrame, config: dict, name: str, profile: str) -> dict:
    if name not in ("development", "validation"):
        raise ValueError("Final evaluation is not authorized")
    engine, summarize = futures_api()
    split = SPLITS[name]
    dates = session_arrays(source, split["start_inclusive"], split["end_exclusive"])["session_dates"]
    frame = source.loc[(dates >= pd.Timestamp(split["start_inclusive"]) - pd.Timedelta(days=2))
                       & (dates < pd.Timestamp(split["end_exclusive"]))].copy().reset_index(drop=True)
    masks = complete_session_masks(frame, split["start_inclusive"], split["end_exclusive"])
    assert_daily_flat_coverage(masks)
    observed_sessions = set(masks["session_dates"][masks["valid_dates"]].dt.date)
    if len(observed_sessions) != split["sessions"]:
        raise ValueError("Expected complete-session coverage differs from source")
    signals = causal_signals(frame, config)
    times = (frame["time"].astype("int64") // 1_000_000_000).to_numpy(np.int64)
    result = engine(times, *(frame[c].to_numpy(float) for c in ("open", "high", "low", "close")),
                    signals["direction_signals"], signals["stop_distances"], signals["target_distances"],
                    contract_multiplier=20, initial_equity=CAPITAL, costs=PROFILES[profile],
                    flat_fee_per_contract_per_side=5. if profile == "operating_fixed_5_per_side" else None,
                    max_holding_bars=12, max_holding_days=1, max_signal_age_seconds=300,
                    entry_allowed=masks["entry_allowed"], exit_signals=masks["exit_signals"],
                    daily_exit=masks["local_minutes"] == 16 * 60 + 45)
    for trade in result["trades"]:
        i, j = trade["entry_index"], trade["exit_index"]
        if (trade["contracts"] != 1 or trade["units"] != 20 or trade["direction"] not in (-1, 1)
                or any(abs(trade[k] * 4 - round(trade[k] * 4)) > 1e-8 for k in ("entry_fill", "exit_fill"))):
            raise ValueError("Expected positive units, one NQ contract, explicit direction and valid ticks")
        if profile == "operating_fixed_5_per_side" and (trade["entry_commission"] != 5 or trade["exit_commission"] != 5):
            raise ValueError("Expected USD5 fee per contract per side")
        if (not masks["entry_allowed"][i] or masks["session_dates"].iloc[i] != masks["session_dates"].iloc[j]
                or 16 * 60 + 45 < masks["local_minutes"][j] < 18 * 60):
            raise ValueError("Directional trade violates entry/session/daily-flat rules")
    stats = summarize(result["trades"])
    daily = {day.isoformat(): 0. for day in sorted(observed_sessions)}
    for trade in result["trades"]:
        day = masks["session_dates"].iloc[trade["exit_index"]].date().isoformat()
        daily[day] += trade["net_pnl"]
    return {"cost_profile": profile, "engine_summary": result["summary"], "statistics": stats,
            "observed_sessions": len(observed_sessions), "session_realized_net_pnl": daily,
            "trades": result["trades"]}


def evaluate_selection() -> dict:
    plan = read_plan()
    if (OUT / "development_report.json").exists():
        raise ValueError("Preserve completed directional trial outcomes")
    source = load_selection_source()
    results = []
    for profile, config in [(p, c) for p in PROFILES for c in plan["family"]]:
        runs = {name: run_split(source, config, name, profile) for name in ("development", "validation")}
        stats = [runs[n]["statistics"] for n in ("development", "validation")]
        financial = all(s["eligible_trades"] > 0 and s["win_rate"] >= .5 and s["net_profit"] > 0
                        and s["natural_net_profit"] > 0 and s["risk_breaches"] == 0 for s in stats)
        count = sum(s["eligible_trades"] for s in stats)
        projected = count * 36 / 27
        row = {"config": config, "cost_profile": profile, "runs": runs,
               "selection_natural_trades": count, "projected_36session_total_natural_trades": projected,
               "projection_is_observed_final_count": False, "financial_eligible": financial,
               "projected_frequency_eligible": projected >= 500, "selection_eligible": financial,
               "score": min(s["mean_net_pnl_per_natural_trade"] / CAPITAL if s["mean_net_pnl_per_natural_trade"] is not None else 0. for s in stats)}
        results.append(row)
        print(json.dumps({"candidate": config["name"], "cost_profile": profile,
                          "development": {k: stats[0][k] for k in ("eligible_trades", "win_rate", "net_profit", "risk_breaches")},
                          "validation": {k: stats[1][k] for k in ("eligible_trades", "win_rate", "net_profit", "risk_breaches")},
                          "selection_natural_count": count, "projected_total": projected,
                          "financial_eligible": financial, "selection_eligible": row["selection_eligible"]}), flush=True)
    eligible = [r for r in results if r["selection_eligible"] and r["cost_profile"] == "operating_fixed_5_per_side"]
    report = {"preregistration_sha256": sha256(OUT / "preregistration.json"),
              "joint_extension_sha256": plan["joint_directional_extension"]["sha256"],
              "software": plan["software"], "source": plan["source"],
              "candidate_count": len(plan["family"]), "cost_operating_variant_count": len(results),
              "candidate_results": results,
              "financial_eligible_count_by_profile": {p: sum(r["financial_eligible"] for r in results if r["cost_profile"] == p) for p in PROFILES},
              "selection_eligible_count": len(eligible), "final": "UNTOUCHED_NO_STRATEGY_FEATURE_COUNTS_OR_PNL_EVALUATED",
              "paper_approved": False, "derivative_variation_margin_bound_established": False,
              "short_all_path_liability": "UNBOUNDED"}
    if eligible:
        chosen = sorted(eligible, key=lambda r: (-r["score"], -r["runs"]["validation"]["engine_summary"]["net_return"], r["config"]["name"]))[0]
        frozen = {"created_at_utc": datetime.now(timezone.utc).isoformat(),
                  "selected_config": chosen["config"], "cost_profile": chosen["cost_profile"],
                  "source": plan["source"], "software": plan["software"],
                  "preregistration_sha256": report["preregistration_sha256"], "selection_evidence": chosen,
                  "final": "UNTOUCHED_PENDING_ROOT_JOINT_SELECTION_AUTHORIZATION", "paper_approved": False,
                  "short_all_path_liability": "UNBOUNDED"}
        write_json(OUT / "selected_before_final.json", frozen)
        report["selected_config"] = chosen["config"]
    write_json(OUT / "development_report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preregister", "evaluate-selection"))
    args = parser.parse_args()
    result = preregister() if args.command == "preregister" else evaluate_selection()
    print(json.dumps({"command": args.command, "selection_eligible_count": result.get("selection_eligible_count"),
                      "final": result.get("final", "UNTOUCHED")}))


if __name__ == "__main__":
    main()
