"""Bounded native-NQ M5 mean-reversion research, never an execution strategy.

Preregistration precedes the first candidate result. The selection command
discards March/April rows before constructing any strategy feature. There is
deliberately no final-evaluation command: that requires the root agent's later
authorization and an immutable selection receipt.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from research.intraday_engine import run_intraday_backtest
from research.statistics import summarize_trades
from trading_agent.risk import CostModel


OUT = Path("artifacts/intraday/nq")
SOURCE = OUT / "source/NQ_5min_20260120_20260415.csv"
COMMIT = "60abd3fb6369c6ce0b6a4a65b0f2562fc96b1264"
CAPITAL = 80_000_000.0
COSTS = CostModel(pip_size=.25, spread_pips=2, slippage_pips=1,
                  commission_bps=.35, minimum_commission=.1)
PROFILES = {
    "conservative_bps_proxy": COSTS,
    "operating_fixed_5_per_side": CostModel(pip_size=.25, spread_pips=2, slippage_pips=1,
                                            commission_bps=0, minimum_commission=5),
}
SPLITS = {
    "development": {"start_inclusive": "2026-01-21", "end_exclusive": "2026-02-14", "sessions": 18},
    "validation": {"start_inclusive": "2026-02-16", "end_exclusive": "2026-02-28", "sessions": 9},
    "final": {"start_inclusive": "2026-04-01", "end_exclusive": "2026-04-16", "sessions": 10},
}
HOLIDAYS = ("2026-02-16", "2026-04-03")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def candidates() -> list[dict]:
    return [{"name": f"nq_m5_w{window}_z{z:g}_{regime}_s{points}_t{points}",
             "window": window, "z_threshold": z, "regime": regime,
             "stop_points": points, "target_points": points}
            for window in (6, 12) for z in (1., 1.5)
            for regime in ("none", "above_ema96") for points in (20, 30, 40)]


def preregister() -> dict:
    path = OUT / "preregistration.json"
    if path.exists():
        raise ValueError("Preregistration already exists and must not be overwritten")
    if (OUT / "development_report.json").exists():
        raise ValueError("Candidate results already exist; cannot retroactively preregister")
    receipt_path = OUT / "source_quality_receipt.json"
    receipt = json.loads(receipt_path.read_text())
    plan = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "written_before_any_nq_strategy_pnl": True,
        "source": {"repository": "https://github.com/axb0306/cme-futures-ohlc",
                   "pinned_commit": COMMIT,
                   "url": f"https://raw.githubusercontent.com/axb0306/cme-futures-ohlc/{COMMIT}/NQ/NQ_5min_20260120_20260415.csv",
                   "path": str(SOURCE), "sha256": sha256(SOURCE),
                   "timeframe": "native_M5", "timestamp_timezone": "UTC_as_source_declares",
                   "bar_timestamp_convention": "Assumed bar-opening time; provider label semantics independently unverified",
                   "instrument": "NQ_root_csv_not_MNQ", "contract_multiplier_usd_per_point": 20,
                   "quote_side": "last_trade_OHLC_as_declared_source",
                   "contract_identity": "updater_requests_CON.F.US.ENQ.M26_initial_backfill_unverified",
                   "source_quality_receipt_sha256": sha256(receipt_path)},
        "family": candidates(), "declared_candidate_count": 24,
        "declared_cost_operating_variant_count": 48,
        "splits": SPLITS,
        "calendar": {"timezone": "America/New_York", "session_date": "NY_date_plus_one_after_18:00",
                     "weekdays": "Globex_session_date_Monday_to_Friday",
                     "exclude_entire_session_and_UTC_month": "2026-03; no March rows in strategy features or entries",
                     "excluded_short_session_dates": list(HOLIDAYS),
                     "entry_execution_clock": "18:30_through_16:15_inclusive",
                     "mandatory_flat": "16:40_completed_signal_executes_16:45_open",
                     "missing_16:40_or_16:45_quotes": "block_entire_study_before_strategy_evaluation"},
        "signal": {"prior_dip": "close[j-1] relative to population mean/std of window closes ending at j-2; z<=-threshold",
                   "completed_rebound_confirmation": "close[j]>open[j] and close[j]>close[j-1]",
                   "regime_when_enabled": "close[j-1]>=EMA96[j-2]",
                   "feature_reset": "every native timestamp gap >300 seconds, including maintenance/weekends",
                   "warmup": "all configurations require >=98 consecutive observations including the rebound bar; EMA96 excludes dip/rebound",
                   "entry": "Next native M5 open after completed rebound; max signal age 300 seconds",
                   "one_position": True, "same_bar_reentry": False,
                   "holding_limit": "12_bars_or_daily_flat_whichever_first; hard_days1",
                   "stop_target_anchor": "entry_input_last_trade_open",
                   "OHLC_ambiguous_stop_target_priority": "stop_first",
                   "gap_exit": "actual_observed_open_unclipped",
                   "terminal_liquidations": "fees_and_PnL_in_account_totals_exclude_from_natural_close_statistics",
                   "selection_warmup": "up_to_two_calendar_days_before_first_session; allowedmaskblocksoutside_split"},
        "costs": {"profiles": {name: asdict(costs) for name, costs in PROFILES.items()},
                  "operating_profile": "operating_fixed_5_per_side",
                  "conservative_sensitivity_profile": "conservative_bps_proxy",
                  "fee_scenario_disclosure": "24 unchanged signals under each of two profiles = 48 disclosed cost-operating variants; added flat USD5 per contract per side before any NQ P&L. Both are configured simulations, not measured broker schedules.",
                  "flat_fee_guard": "Every trade must have exactly one NQ contract or evaluation fails; minimum commission USD5 then implements USD5 per contract per side correctly",
                  "fill_side_cost_points": .5,
                  "baseline_fill_prices": "buy_last_trade_open_plus0.5; sell_exit_last_trade_reference_minus0.5",
                  "interpretation": "conservative_mid_proxy_applied_to_last_trade_OHLC_not_observed_book",
                  "verified_fee_schedule": False,
                  "final_stress_if_later_authorized": [1.5, 2.0],
                  "stress_rounding": "round_each_side_price_friction_up_to0.25tick; scalecommission_andminimumfee"},
        "risk": {"initial_virtual_equity_usd": CAPITAL, "unit_step": 20,
                 "one_NQ_contract_when_capacity_allows": True,
                 "numeric_model": "fully_paid_nonnegative_price_units;0.8percentprincipalcap;1percentfullprincipalbudget",
                 "derivative_variation_margin_bound_established": False,
                 "activation_authorized": False,
                 "observed_checks": "Both adverse excursion versus entry equity and peak-to-trough trade drawdown must be <=1 percent"},
        "selection": {"financial_eligibility_each_split": "natural_count>0,net_win_rate>=0.5,positive_natural_and_account_net,zero_observed_1percent_breaches",
                      "rank": "maximize_minimum_development_validation_net_return",
                      "tie_breakers": ["maximum_validation_net_return", "candidate_name_ascending"],
                      "rank_cost_profile": "operating_fixed_5_per_side; conservative profile retained as sensitivity, not used to pick a different final winner",
                      "frequency_projection": "27_dev_validation_sessions_plus10reserved_final_sessions;projected_count=observed_selection_count*37/27",
                      "minimum_observed_selection_natural_count_for_projection500": math.ceil(500 * 27 / 37),
                      "frequency_eligibility_is_projection_not_actual_count": True,
                      "literal_user_count": "500_total_natural_closes_across_dev_validation_final",
                      "preferred_independent_final_count": 500,
                      "final_must_remain_unread_before_freeze": True},
        "statistics": {"wilson": "95percent_independence_assumption",
                       "final_bootstrap_if_later_authorized": {"unit": "UTC calendar realized daily returns; previous realized equity denominator; zero days retained",
                         "block_calendar_days": 7, "replications": 10000, "seed": 20261004,
                         "sensitivity_blocks_calendar_days": [14, 28]}},
        "software": {"study_sha256": sha256(Path(__file__)),
                     "engine_sha256": sha256(Path("research/intraday_engine.py")),
                     "statistics_sha256": sha256(Path("research/statistics.py"))},
        "source_quality_only_final_inspection_permitted": True,
        "source_audit_row_count": receipt["global_quality"]["rows"],
        "limitations": ["Third-party TopstepX/ProjectX mirror; original API responses not authenticated here.",
                        "CSV has no per-row expiry identifier; initial historical native contract identity unverified.",
                        "Last-trade candles do not establish observable bid/ask spread or queue/fill ordering.",
                        "UTC timestamp semantics are source-declared; the bar-start label convention is assumed and independently unverified.",
                        "Commission schedule remains an explicit assumption and is not independently verified.",
                        "Virtual USD80 million supports whole-contract arithmetic only; it does not establish a derivative loss guarantee.",
                        "24 additional NQ signal configurations and 48 cost-operating variants are disclosed selection trials; sample profit does not establish future expectancy."]}
    write_json(path, plan)
    return plan


def read_plan() -> dict:
    plan = json.loads((OUT / "preregistration.json").read_text())
    if plan["family"] != candidates() or not plan["written_before_any_nq_strategy_pnl"]:
        raise ValueError("The complete unchanged 24-configuration preregistration is required")
    for name, path in (("study_sha256", Path(__file__)), ("engine_sha256", Path("research/intraday_engine.py")),
                       ("statistics_sha256", Path("research/statistics.py"))):
        if sha256(path) != plan["software"][name]:
            raise ValueError("Preregistered software hash changed: " + name)
    if sha256(SOURCE) != plan["source"]["sha256"]:
        raise ValueError("Pinned source bytes changed")
    return plan


def load_selection_source() -> pd.DataFrame:
    frame = pd.read_csv(SOURCE)
    frame["time"] = pd.to_datetime(frame["datetime"], utc=True)
    # Only source audit may inspect later data before freezing. April never
    # reaches a feature constructor or candidate count in this command.
    frame = frame.loc[frame["time"] < pd.Timestamp("2026-03-01", tz="UTC")].copy()
    prices = frame[["open", "high", "low", "close"]].to_numpy(float)
    if (not np.isfinite(prices).all() or (prices <= 0).any()
            or not frame["time"].is_monotonic_increasing or frame["time"].duplicated().any()
            or (frame["low"] > frame[["open", "close"]].min(axis=1)).any()
            or (frame["high"] < frame[["open", "close"]].max(axis=1)).any()
            or not np.allclose(prices * 4, np.rint(prices * 4), rtol=0, atol=1e-8)):
        raise ValueError("Native NQ input failed timestamp/OHLC/tick checks")
    return frame.reset_index(drop=True)


def session_arrays(frame: pd.DataFrame, start: str, end: str) -> dict:
    local = frame["time"].dt.tz_convert("America/New_York")
    minutes = local.dt.hour.to_numpy() * 60 + local.dt.minute.to_numpy()
    dates = local.dt.tz_localize(None).dt.normalize()
    session_dates = dates + pd.to_timedelta((minutes >= 18 * 60).astype(int), unit="D")
    valid = ((session_dates >= pd.Timestamp(start)) & (session_dates < pd.Timestamp(end))
             & (session_dates.dt.weekday < 5) & (session_dates.dt.month != 3)
             & (frame["time"].dt.month != 3)
             & ~session_dates.isin(pd.to_datetime(HOLIDAYS)))
    clock = (minutes >= 18 * 60 + 30) | (minutes <= 16 * 60 + 15)
    return {"session_dates": session_dates, "valid_dates": valid.to_numpy(bool),
            "local_minutes": minutes, "entry_allowed": valid.to_numpy(bool) & clock,
            "exit_signals": minutes == 16 * 60 + 40}


def assert_daily_flat_coverage(masks: dict) -> None:
    dates = masks["session_dates"]
    valid = masks["valid_dates"]
    observed = set(dates[valid].dt.date)
    for minute in (16 * 60 + 40, 16 * 60 + 45):
        present = set(dates[valid & (masks["local_minutes"] == minute)].dt.date)
        if observed - present:
            raise ValueError("Missing mandatory daily-flat signal/open: " + str(sorted(observed - present)))


def causal_signals(frame: pd.DataFrame, config: dict) -> dict:
    if config["regime"] not in ("none", "above_ema96"):
        raise ValueError("Unregistered regime")
    n = len(frame)
    signal = np.zeros(n, dtype=bool)
    prior_z = np.full(n, np.nan)
    prior_ema = np.full(n, np.nan)
    times = (frame["time"].astype("int64") // 1_000_000_000).to_numpy(np.int64)
    boundaries = np.r_[0, np.flatnonzero(np.diff(times) != 300) + 1, n]
    for first, last in zip(boundaries[:-1], boundaries[1:]):
        closes = frame["close"].iloc[first:last].astype(float).reset_index(drop=True)
        opens = frame["open"].iloc[first:last].astype(float).reset_index(drop=True)
        mean = closes.rolling(config["window"], min_periods=config["window"]).mean().shift(2)
        std = closes.rolling(config["window"], min_periods=config["window"]).std(ddof=0).shift(2)
        z = (closes.shift(1) - mean) / std.replace(0, np.nan)
        ema = closes.ewm(span=96, adjust=False, min_periods=96).mean().shift(2)
        rebound = (closes > opens) & (closes > closes.shift(1))
        eligible = (z <= -config["z_threshold"]) & rebound & ema.notna()
        if config["regime"] == "above_ema96":
            eligible &= closes.shift(1) >= ema
        signal[first:last] = eligible.fillna(False).to_numpy(bool)
        prior_z[first:last] = z.to_numpy(float)
        prior_ema[first:last] = ema.to_numpy(float)
    return {"entry_signals": signal, "prior_dip_z": prior_z, "prior_ema96": prior_ema,
            "stop_distances": np.full(n, config["stop_points"]),
            "target_distances": np.full(n, config["target_points"])}


def run_split(source: pd.DataFrame, config: dict, name: str,
              cost_profile: str = "conservative_bps_proxy") -> dict:
    if name not in ("development", "validation"):
        raise ValueError("Final evaluation is not authorized by this command")
    costs = PROFILES[cost_profile]
    split = SPLITS[name]
    initial_masks = session_arrays(source, split["start_inclusive"], split["end_exclusive"])
    session_dates = initial_masks["session_dates"]
    warmup_start = pd.Timestamp(split["start_inclusive"]) - pd.Timedelta(days=2)
    frame = source.loc[(session_dates >= warmup_start)
                       & (session_dates < pd.Timestamp(split["end_exclusive"]))].copy().reset_index(drop=True)
    masks = session_arrays(frame, split["start_inclusive"], split["end_exclusive"])
    assert_daily_flat_coverage(masks)
    observed_sessions = set(masks["session_dates"][masks["valid_dates"]].dt.date)
    if len(observed_sessions) != split["sessions"]:
        raise ValueError("Actual native coverage differs from preregistered session count")
    signals = causal_signals(frame, config)
    times = (frame["time"].astype("int64") // 1_000_000_000).to_numpy(np.int64)
    result = run_intraday_backtest(
        times, *(frame[c].to_numpy(float) for c in ("open", "high", "low", "close")),
        signals["entry_signals"], signals["stop_distances"], signals["target_distances"],
        entry_allowed=masks["entry_allowed"], exit_signals=masks["exit_signals"],
        max_holding_bars=12, max_holding_days=1, initial_equity=CAPITAL,
        costs=costs, quote_kind="mid", unit_step=20, max_signal_age_seconds=300)
    for trade in result["trades"]:
        i, j = trade["entry_index"], trade["exit_index"]
        if (trade["units"] != 20 or trade["trading_lots"] != 1
                or any(abs(trade[k] * 4 - round(trade[k] * 4)) > 1e-8
                       for k in ("entry_fill", "exit_fill"))):
            raise ValueError("Expected one whole NQ contract and valid quarter-point fills")
        if cost_profile == "operating_fixed_5_per_side" and (
                trade["entry_commission"] != 5 or trade["exit_commission"] != 5):
            raise ValueError("Flat per-contract commission scenario did not charge USD5 per side")
        if (not masks["entry_allowed"][i] or masks["session_dates"].iloc[i] != masks["session_dates"].iloc[j]
                or 16 * 60 + 45 < masks["local_minutes"][j] < 18 * 60):
            raise ValueError("Trade violated the preregistered session or daily-flat rule")
        trade["source_last_trade_gross_pnl"] = trade["units"] * (trade["exit_mid"] - trade["entry_mid"])
        trade["source_price_baseline"] = "last_trade_OHLC_with_modeled_mid_proxy_costs"
    stats = summarize_trades(result["trades"])
    stats["source_last_trade_gross_profit"] = stats.pop("gross_mid_profit")
    stats["price_baseline"] = "last_trade_proxy"
    daily = {day.isoformat(): 0. for day in sorted(observed_sessions)}
    for trade in result["trades"]:
        day = masks["session_dates"].iloc[trade["exit_index"]].date().isoformat()
        daily[day] += trade["net_pnl"]
    return {"cost_profile": cost_profile, "engine_summary": result["summary"], "statistics": stats,
            "session_realized_net_pnl": daily, "observed_sessions": len(observed_sessions),
            "trades": result["trades"]}


def evaluate_selection() -> dict:
    plan = read_plan()
    if (OUT / "development_report.json").exists():
        raise ValueError("Preserved selection report already exists; do not overwrite trials")
    source = load_selection_source()
    results = []
    for cost_profile, config in [(p, c) for p in PROFILES for c in plan["family"]]:
        runs = {name: run_split(source, config, name, cost_profile) for name in ("development", "validation")}
        summaries = [runs[name]["statistics"] for name in ("development", "validation")]
        financially_eligible = all(s["eligible_trades"] > 0 and s["win_rate"] >= .5
                                  and s["natural_net_profit"] > 0 and s["net_profit"] > 0
                                  and s["risk_breaches"] == 0 for s in summaries)
        count = sum(s["eligible_trades"] for s in summaries)
        projected_total = count * 37 / 27
        eligible = financially_eligible and projected_total >= 500
        row = {"config": config, "cost_profile": cost_profile, "runs": runs,
               "selection_natural_trades": count,
               "projected_37session_total_natural_trades": projected_total,
               "projection_is_observed_final_count": False,
               "financial_eligible": financially_eligible,
               "projected_frequency_eligible": projected_total >= 500,
               "selection_eligible": eligible,
               "score": min(runs[n]["engine_summary"]["net_return"] for n in runs)}
        results.append(row)
        print(json.dumps({"candidate": config["name"], "cost_profile": cost_profile,
                          "development": {k: summaries[0][k] for k in ("eligible_trades", "win_rate", "net_profit", "risk_breaches")},
                          "validation": {k: summaries[1][k] for k in ("eligible_trades", "win_rate", "net_profit", "risk_breaches")},
                          "selection_count": count, "projected_total": projected_total,
                          "financial_eligible": financially_eligible, "selection_eligible": eligible}), flush=True)
    eligible_rows = [row for row in results if row["selection_eligible"]
                     and row["cost_profile"] == "operating_fixed_5_per_side"]
    report = {"preregistration_sha256": sha256(OUT / "preregistration.json"),
              "software": plan["software"], "source": plan["source"],
              "candidate_results": results, "candidate_count": len(plan["family"]),
              "cost_operating_variant_count": len(results),
              "financial_eligible_count_by_profile": {p: sum(row["financial_eligible"] for row in results
                                                           if row["cost_profile"] == p) for p in PROFILES},
              "selection_eligible_count": len(eligible_rows),
              "final": "UNTOUCHED_NO_STRATEGY_FEATURE_COUNTS_OR_PNL_EVALUATED",
              "paper_approved": False, "derivative_variation_margin_bound_established": False}
    if eligible_rows:
        selected = sorted(eligible_rows, key=lambda row: (-row["score"],
                    -row["runs"]["validation"]["engine_summary"]["net_return"], row["config"]["name"]))[0]
        frozen = {"created_at_utc": datetime.now(timezone.utc).isoformat(),
                  "selected_config": selected["config"], "cost_profile": selected["cost_profile"], "score": selected["score"],
                  "source": plan["source"], "software": plan["software"],
                  "preregistration_sha256": report["preregistration_sha256"],
                  "selection_evidence": selected,
                  "final": "UNTOUCHED_PENDING_ROOT_AUTHORIZATION",
                  "paper_approved": False, "derivative_variation_margin_bound_established": False}
        write_json(OUT / "selected_before_final.json", frozen)
        report["selected_config"] = selected["config"]
    write_json(OUT / "development_report.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("preregister", "evaluate-selection"))
    args = parser.parse_args()
    report = preregister() if args.command == "preregister" else evaluate_selection()
    print(json.dumps({"command": args.command,
                      "candidate_count": report.get("declared_candidate_count", report.get("candidate_count")),
                      "selection_eligible_count": report.get("selection_eligible_count"),
                      "final": report.get("final", "UNTOUCHED")}))


if __name__ == "__main__":
    main()
