"""Separate preregistered NQ M5 trend/momentum hypothesis; selection only.

This module cannot evaluate April. It preserves the earlier mean-reversion
history and preregisters 24 fixed configurations under both fee scenarios
before any new strategy P&L. Completed signal bars execute at the next open.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.intraday_engine import run_intraday_backtest
from research.statistics import summarize_trades
from .study import (SOURCE, COMMIT, CAPITAL, PROFILES, SPLITS as BASE_SPLITS, HOLIDAYS,
                    sha256, write_json, load_selection_source,
                    session_arrays, assert_daily_flat_coverage)


OUT = Path("artifacts/intraday/nq_momentum")
EXTENSION = Path("artifacts/intraday/futures_momentum_extension.json")
CALENDAR_CLARIFICATION = Path("artifacts/intraday/futures_momentum_calendar_clarification.json")
SPLITS = {name: dict(value) for name, value in BASE_SPLITS.items()}
# All UTC-March rows are excluded. Apr1 therefore loses the previous evening's
# first24 bars and is an incomplete Globex session under the joint protocol.
SPLITS["final"]["sessions"] = 9


def candidates() -> list[dict]:
    return [{"name": f"nq_m5_momentum_h{horizon}_ema{span}_{style}_s{stop}_t{target}",
             "return_horizon": horizon, "ema_span": span, "entry_style": style,
             "stop_points": stop, "target_points": target}
            for horizon in (6, 24) for span in (48, 192)
            for style in ("positive_momentum", "bullish_trend_pullback")
            for stop, target in ((40, 40), (40, 60), (60, 60))]


def preregister() -> dict:
    path = OUT / "preregistration.json"
    if path.exists() or (OUT / "development_report.json").exists():
        raise ValueError("Do not overwrite preserved registration/results")
    if not EXTENSION.exists() or not CALENDAR_CLARIFICATION.exists():
        raise ValueError("Joint family extension must precede any momentum P&L")
    plan = {
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "written_before_any_nq_momentum_pnl": True,
        "joint_family_extension": {"path": str(EXTENSION), "sha256": sha256(EXTENSION)},
        "calendar_clarification": {"path": str(CALENDAR_CLARIFICATION), "sha256": sha256(CALENDAR_CLARIFICATION)},
        "hypothesis": "Separate bullish trend continuation/pullback family after preserving failed mean reversion",
        "source": {"path": str(SOURCE), "sha256": sha256(SOURCE),
                   "repository": "https://github.com/axb0306/cme-futures-ohlc",
                   "pinned_commit": COMMIT,
                   "url": f"https://raw.githubusercontent.com/axb0306/cme-futures-ohlc/{COMMIT}/NQ/NQ_5min_20260120_20260415.csv",
                   "native_timeframe": "M5", "instrument": "NQ CSV, not MNQ",
                   "timestamp_timezone": "UTC as source declares",
                   "bar_timestamp_convention": "Assumed opening timestamp; label semantics independently unverified",
                   "price_side": "Last-trade OHLC; modeled conservative mid proxy, not observed book",
                   "historical_contract_identity": "Updater requests CON.F.US.ENQ.M26; initial backfill/per-row expiry unverified",
                   "source_quality_receipt": "artifacts/intraday/nq/source_quality_receipt.json",
                   "source_quality_receipt_sha256": sha256(Path("artifacts/intraday/nq/source_quality_receipt.json"))},
        "family": candidates(), "signal_configuration_count": 24,
        "disclosed_cost_operating_variants": 48,
        "splits": SPLITS,
        "calendar": {"timezone": "America/New_York", "session_date": "NY date plus one at/after18:00",
                     "allowed_session_weekdays": "Monday through Friday",
                     "excluded_entire_UTC_and_session_month": "2026-03",
                     "no_March_rows_in_strategy_features": True,
                     "excluded_short_sessions": list(HOLIDAYS),
                     "excluded_final_incomplete_session_after_March_removal": "2026-04-01",
                     "complete_session_policy": "Only sessions with every expected276 native M5 opening timestamp from18:00 through16:55 NY, after exclusions; determined from source QA, not price outcomes",
                     "entry_clock": "18:30 through 16:15 inclusive",
                     "mandatory_flat": "Completed16:40 bar signals sale at16:45 open",
                     "absent_mandatory_signal_or_exit_quote": "Block evaluation before P&L"},
        "signal": {"common_completed_signal_bar_i": "close[i] > EMAspan[i] AND EMAspan[i] > EMAspan[i-horizon]",
                   "positive_momentum": "Additionally close[i] > close[i-horizon]",
                   "bullish_trend_pullback": "Additionally close[i-1] < close[i-2] AND close[i] > close[i-1]",
                   "pullback_return_definition": "Previous ONE-bar close return is negative; horizon parameter measures EMA slope in both styles",
                   "EMA": "adjust=False, min_periods=span; all inputs are completed closes through signal bar i",
                   "warmup": "At least span+horizon consecutive observations after every gap; maximum216 observations",
                   "feature_reset": "Every timestamp interval different from300seconds; no cross-maintenance/weekend/contract-gap indicators",
                   "next_open_entry": True, "max_signal_age_seconds": 300,
                   "one_position": True, "same_bar_reentry": False,
                   "stop_target_anchor": "Actual input entry last-trade open",
                   "ambiguous_intrabar_priority": "Stop first",
                   "opening_gap_fills": "Actual next observed open, losses unclipped",
                   "max_holding_bars": 12, "hard_max_holding_days": 1,
                   "sample_end": "Account includes exit costs/P&L; natural-close statistics exclude artificial exits",
                   "selection_warmup": "Up to two calendar days before first split session; execution masks exclude those days"},
        "costs": {"profiles": {p: asdict(c) for p, c in PROFILES.items()},
                  "operating_profile": "operating_fixed_5_per_side",
                  "conservative_sensitivity": "conservative_bps_proxy",
                  "fixed_price_friction": "Full spread0.50points; each-side slippage0.25points; entry+0.50,exit-0.50points",
                  "tick_size_points": .25,
                  "flat_fee_guard": "Exactly one NQ contract on every trade, otherwise fail; USD5 minimum is then USD5 per contract per side",
                  "verified_broker_fee_schedule": False,
                  "final_stress_if_later_authorized": [1.5, 2.0],
                  "stress_rounding": "Round each-side price friction up to0.25tick; scale flat fee/commission"},
        "risk": {"initial_virtual_equity_usd": CAPITAL, "unit_step": 20,
                 "exact_trading_lots": 1, "principal_cap_fraction": .008,
                 "full_principal_loss_budget_fraction": .01,
                 "numeric_model": "Fully paid nonnegative-price arithmetic",
                 "observed_check": "Both adverse excursion and peak-to-trough per-trade drawdown versus entry equity<=1percent",
                 "derivative_variation_margin_bound_established": False,
                 "paper_activation": False},
        "selection": {"financial_eligibility_each_split": "Natural count>0,net win rate>=50%,positive natural and all-exit net,zero observed1percent breaches",
                      "rank_cost_profile": "operating_fixed_5_per_side",
                      "rank": "Maximum minimum development/validation MEAN NATURAL net P&L divided by initial equity",
                      "tie_breakers": ["Maximum validation net return", "Candidate name ascending"],
                      "frequency_projection": "27 observed development/validation sessions to36 including9 reserved complete final sessions",
                      "projection_formula": "selection_natural_count*36/27",
                      "selection_projection_count_threshold": 375,
                      "projection_is_not_observed_final_count": True,
                      "literal_user_requirement": "500 total natural closes from this same strategy across declared splits",
                      "preferred_independent_final_count": 500,
                      "no_adaptive_parameters_after_results": True,
                      "final_requires_frozen_selection_and_root_authorization": True},
        "statistics": {"wilson_95": "Descriptive; ignores serial dependence",
                       "final_bootstrap_if_later_authorized": {"unit": "UTC calendar realized daily returns using previous realized equity; inactive days retained",
                         "block_calendar_days": 7, "replications": 10000, "seed": 20261004,
                         "sensitivity_blocks": [14, 28]}},
        "software": {"momentum_sha256": sha256(Path(__file__)),
                     "shared_nq_study_sha256": sha256(Path("research/intraday_nq/study.py")),
                     "engine_sha256": sha256(Path("research/intraday_engine.py")),
                     "statistics_sha256": sha256(Path("research/statistics.py"))},
        "limitations": ["Third-party mirror; original historical API responses not authenticated.",
                        "Root CSV does not verify each historical native expiry or roll/back-adjustment.",
                        "Last-trade OHLC lacks actual spread and execution path; bar-opening timestamp convention is assumed.",
                        "Both fee profiles are explicit simulations; broker schedules remain unverified.",
                        "USD80million virtual equity enables whole-contract numeric arithmetic, not a derivatives risk guarantee.",
                        "Preserve the previous24 mean-reversion signals/48 cost variants plus these24 signals/48 variants as disclosed selection trials."]}
    write_json(path, plan)
    return plan


def read_plan() -> dict:
    plan = json.loads((OUT / "preregistration.json").read_text())
    if plan["family"] != candidates() or not plan["written_before_any_nq_momentum_pnl"]:
        raise ValueError("Complete unchanged preregistration required")
    for field, path in (("momentum_sha256", Path(__file__)),
                        ("shared_nq_study_sha256", Path("research/intraday_nq/study.py")),
                        ("engine_sha256", Path("research/intraday_engine.py")),
                        ("statistics_sha256", Path("research/statistics.py"))):
        if plan["software"][field] != sha256(path):
            raise ValueError("Preregistered software changed: " + field)
    if (plan["source"]["sha256"] != sha256(SOURCE)
            or plan["joint_family_extension"]["sha256"] != sha256(EXTENSION)
            or plan["calendar_clarification"]["sha256"] != sha256(CALENDAR_CLARIFICATION)):
        raise ValueError("Preregistered source/extension changed")
    return plan


def causal_signals(frame: pd.DataFrame, config: dict) -> dict:
    n = len(frame)
    signals = np.zeros(n, dtype=bool)
    ema_values = np.full(n, np.nan)
    slope_values = np.full(n, np.nan)
    horizon_returns = np.full(n, np.nan)
    prior_returns = np.full(n, np.nan)
    times = (frame["time"].astype("int64") // 1_000_000_000).to_numpy(np.int64)
    boundaries = np.r_[0, np.flatnonzero(np.diff(times) != 300) + 1, n]
    horizon, span = config["return_horizon"], config["ema_span"]
    for first, last in zip(boundaries[:-1], boundaries[1:]):
        closes = frame["close"].iloc[first:last].astype(float).reset_index(drop=True)
        ema = closes.ewm(span=span, adjust=False, min_periods=span).mean()
        slope = ema - ema.shift(horizon)
        returns = closes / closes.shift(horizon) - 1
        previous_return = closes.shift(1) / closes.shift(2) - 1
        common = (closes > ema) & (slope > 0)
        if config["entry_style"] == "positive_momentum":
            entries = common & (returns > 0)
        elif config["entry_style"] == "bullish_trend_pullback":
            entries = common & (previous_return < 0) & (closes > closes.shift(1))
        else:
            raise ValueError("Unregistered entry style")
        signals[first:last] = entries.fillna(False).to_numpy(bool)
        ema_values[first:last] = ema.to_numpy(float)
        slope_values[first:last] = slope.to_numpy(float)
        horizon_returns[first:last] = returns.to_numpy(float)
        prior_returns[first:last] = previous_return.to_numpy(float)
    return {"entry_signals": signals, "ema": ema_values, "ema_slope": slope_values,
            "horizon_return": horizon_returns, "prior_one_bar_return": prior_returns,
            "stop_distances": np.full(n, config["stop_points"]),
            "target_distances": np.full(n, config["target_points"])}


def complete_session_masks(frame: pd.DataFrame, start: str, end: str) -> dict:
    """Source-calendar completeness, frozen before P&L; no price-based filter."""
    masks = session_arrays(frame, start, end)
    complete_dates = set()
    for day in set(masks["session_dates"][masks["valid_dates"]]):
        selected = (masks["session_dates"] == day) & masks["valid_dates"]
        observed = frame.loc[selected, "time"]
        opening = (pd.Timestamp(day) - pd.Timedelta(days=1) + pd.Timedelta(hours=18)).tz_localize("America/New_York")
        expected = pd.date_range(opening, periods=276, freq="5min").tz_convert("UTC")
        if len(observed) == 276 and np.array_equal(observed.astype("int64").to_numpy(), expected.astype("int64").to_numpy()):
            complete_dates.add(day)
    complete = masks["session_dates"].isin(complete_dates).to_numpy(bool)
    masks["valid_dates"] &= complete
    masks["entry_allowed"] &= complete
    return masks


def run_split(source: pd.DataFrame, config: dict, name: str, cost_profile: str) -> dict:
    if name not in ("development", "validation"):
        raise ValueError("Final evaluation is not authorized")
    split = SPLITS[name]
    sessions = session_arrays(source, split["start_inclusive"], split["end_exclusive"])["session_dates"]
    frame = source.loc[(sessions >= pd.Timestamp(split["start_inclusive"]) - pd.Timedelta(days=2))
                       & (sessions < pd.Timestamp(split["end_exclusive"]))].copy().reset_index(drop=True)
    masks = complete_session_masks(frame, split["start_inclusive"], split["end_exclusive"])
    assert_daily_flat_coverage(masks)
    observed_sessions = set(masks["session_dates"][masks["valid_dates"]].dt.date)
    if len(observed_sessions) != split["sessions"]:
        raise ValueError("Coverage differs from preregistered sessions")
    signals = causal_signals(frame, config)
    times = (frame["time"].astype("int64") // 1_000_000_000).to_numpy(np.int64)
    result = run_intraday_backtest(
        times, *(frame[c].to_numpy(float) for c in ("open", "high", "low", "close")),
        signals["entry_signals"], signals["stop_distances"], signals["target_distances"],
        entry_allowed=masks["entry_allowed"], exit_signals=masks["exit_signals"],
        max_holding_bars=12, max_holding_days=1, initial_equity=CAPITAL,
        costs=PROFILES[cost_profile], quote_kind="mid", unit_step=20, max_signal_age_seconds=300)
    for trade in result["trades"]:
        i, j = trade["entry_index"], trade["exit_index"]
        if (trade["units"] != 20 or trade["trading_lots"] != 1
                or any(abs(trade[k] * 4 - round(trade[k] * 4)) > 1e-8
                       for k in ("entry_fill", "exit_fill"))):
            raise ValueError("Expected one whole NQ contract and quarter-point fills")
        if cost_profile == "operating_fixed_5_per_side" and (
                trade["entry_commission"] != 5 or trade["exit_commission"] != 5):
            raise ValueError("Expected flat USD5 commission per side for one contract")
        if (not masks["entry_allowed"][i] or masks["session_dates"].iloc[i] != masks["session_dates"].iloc[j]
                or 16 * 60 + 45 < masks["local_minutes"][j] < 18 * 60):
            raise ValueError("Daily-flat or allowed-session violation")
        trade["source_last_trade_gross_pnl"] = trade["units"] * (trade["exit_mid"] - trade["entry_mid"])
        trade["source_price_baseline"] = "last_trade_OHLC_with_modeled_mid_proxy_costs"
    stats = summarize_trades(result["trades"])
    stats["source_last_trade_gross_profit"] = stats.pop("gross_mid_profit")
    stats["price_baseline"] = "last_trade_proxy"
    daily = {day.isoformat(): 0. for day in sorted(observed_sessions)}
    for trade in result["trades"]:
        day = masks["session_dates"].iloc[trade["exit_index"]].date().isoformat()
        daily[day] += trade["net_pnl"]
    return {"cost_profile": cost_profile, "engine_summary": result["summary"],
            "statistics": stats, "observed_sessions": len(observed_sessions),
            "session_realized_net_pnl": daily, "trades": result["trades"]}


def evaluate_selection() -> dict:
    plan = read_plan()
    if (OUT / "development_report.json").exists():
        raise ValueError("Do not overwrite preserved candidate results")
    source = load_selection_source()
    results = []
    for profile, config in [(p, c) for p in PROFILES for c in plan["family"]]:
        runs = {name: run_split(source, config, name, profile) for name in ("development", "validation")}
        stats = [runs[name]["statistics"] for name in ("development", "validation")]
        financial = all(s["eligible_trades"] > 0 and s["win_rate"] >= .5 and s["net_profit"] > 0
                        and s["natural_net_profit"] > 0 and s["risk_breaches"] == 0 for s in stats)
        count = sum(s["eligible_trades"] for s in stats)
        projected = count * 36 / 27
        row = {"config": config, "cost_profile": profile, "runs": runs,
               "selection_natural_trades": count, "projected_36session_total_natural_trades": projected,
               "projection_is_observed_final_count": False, "financial_eligible": financial,
               "projected_frequency_eligible": projected >= 500,
               "selection_eligible": financial and projected >= 500,
               "score": min(runs[n]["statistics"]["mean_net_pnl_per_natural_trade"] / CAPITAL
                            if runs[n]["statistics"]["mean_net_pnl_per_natural_trade"] is not None else 0.
                            for n in runs)}
        results.append(row)
        print(json.dumps({"candidate": config["name"], "cost_profile": profile,
                          "development": {k: stats[0][k] for k in ("eligible_trades", "win_rate", "net_profit", "risk_breaches")},
                          "validation": {k: stats[1][k] for k in ("eligible_trades", "win_rate", "net_profit", "risk_breaches")},
                          "selection_natural_count": count, "projected_total": projected,
                          "financial_eligible": financial, "selection_eligible": row["selection_eligible"]}), flush=True)
    eligible = [x for x in results if x["selection_eligible"] and x["cost_profile"] == "operating_fixed_5_per_side"]
    report = {"preregistration_sha256": sha256(OUT / "preregistration.json"),
              "joint_extension_sha256": plan["joint_family_extension"]["sha256"],
              "software": plan["software"], "source": plan["source"],
              "candidate_count": len(plan["family"]), "cost_operating_variant_count": len(results),
              "candidate_results": results,
              "financial_eligible_count_by_profile": {p: sum(x["financial_eligible"] for x in results if x["cost_profile"] == p) for p in PROFILES},
              "selection_eligible_count": len(eligible),
              "final": "UNTOUCHED_NO_STRATEGY_FEATURE_COUNTS_OR_PNL_EVALUATED",
              "paper_approved": False, "derivative_variation_margin_bound_established": False}
    if eligible:
        chosen = sorted(eligible, key=lambda x: (-x["score"], -x["runs"]["validation"]["engine_summary"]["net_return"], x["config"]["name"]))[0]
        frozen = {"created_at_utc": datetime.now(timezone.utc).isoformat(),
                  "selected_config": chosen["config"], "cost_profile": chosen["cost_profile"],
                  "source": plan["source"], "software": plan["software"],
                  "preregistration_sha256": report["preregistration_sha256"],
                  "selection_evidence": chosen, "final": "UNTOUCHED_PENDING_ROOT_AUTHORIZATION",
                  "paper_approved": False, "derivative_variation_margin_bound_established": False}
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
