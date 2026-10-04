"""Research-only MES directional rules, frozen before directional PnL.

Actual quote levels, positive contract multipliers and explicit direction are
retained. Reserved notional is not a proof that short futures losses are bounded.
This module has no final-evaluation or paper-order entrypoint.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.statistics import daily_realized_returns, moving_block_bootstrap_mean
from trading_agent.risk import CostModel
from .futures_mes import SOURCE, load_source
from .futures_mes_momentum import calendar, complete_session_source, execution_masks


OUT = Path("artifacts/intraday/mean_reversion/futures_mes_directional")
CAPITAL = 5_000_000.0
SPLITS = {"development": ("2026-01-21", "2026-02-14", 18),
          "validation": ("2026-02-16", "2026-02-28", 9)}


def causal_direction_signals(frame: pd.DataFrame, config: dict) -> dict:
    if (frame["time"].dt.month == 3).any() or (calendar(frame)["sessions"].dt.month == 3).any():
        raise ValueError("Excluded March observations cannot warm up directional features")
    times = (frame["time"].astype("int64") // 1_000_000_000).to_numpy(np.int64)
    closes = frame["close"].to_numpy(float)
    n = len(frame)
    directions = np.zeros(n, dtype=np.int8)
    ema = np.full(n, np.nan)
    slope = np.full(n, np.nan)
    horizon_return = np.full(n, np.nan)
    previous_change = np.full(n, np.nan)
    current_change = np.full(n, np.nan)
    starts = np.r_[0, np.flatnonzero(np.diff(times) != 300) + 1]
    ends = np.r_[starts[1:], n]
    for first, last in zip(starts, ends):
        close = pd.Series(closes[first:last])
        moving = close.ewm(span=config["ema_period"], adjust=False,
                           min_periods=config["ema_period"]).mean()
        trend = moving - moving.shift(config["horizon"])
        change = close.diff()
        returned = close - close.shift(config["horizon"])
        long_rule = (close > moving) & (trend > 0)
        short_rule = (close < moving) & (trend < 0)
        if config["style"] == "momentum":
            long_rule &= returned > 0
            short_rule &= returned < 0
        elif config["style"] == "pullback":
            long_rule &= (change.shift(1) < 0) & (change > 0)
            short_rule &= (change.shift(1) > 0) & (change < 0)
        else:
            raise ValueError("Unregistered directional style")
        longs = long_rule.fillna(False).to_numpy(bool)
        shorts = short_rule.fillna(False).to_numpy(bool)
        if np.any(longs & shorts):
            raise ValueError("A bar cannot request both directions")
        directions[first:last] = longs.astype(np.int8) - shorts.astype(np.int8)
        ema[first:last], slope[first:last] = moving.to_numpy(float), trend.to_numpy(float)
        horizon_return[first:last] = returned.to_numpy(float)
        previous_change[first:last], current_change[first:last] = change.shift(1).to_numpy(float), change.to_numpy(float)
    clock = calendar(frame)["availability_minutes"]
    permitted = (clock >= 18 * 60 + 30) | (clock <= 16 * 60 + 15)
    directions[~permitted] = 0
    return {"direction_signals": directions, "stop_distances": np.full(n, config["stop_points"]),
            "target_distances": np.full(n, config["target_points"]), "ema": ema, "ema_slope": slope,
            "horizon_return": horizon_return, "previous_change": previous_change, "current_change": current_change}


def assert_directional_trade_integrity(trades: list[dict], profile: str) -> None:
    for trade in trades:
        if trade["units"] != 5 or trade["contracts"] != 1 or trade["direction"] not in (-1, 1):
            raise ValueError("Actual prices and exactly one positive-unit MES contract must be retained")
        if profile == "flat2_operating_assumption" and (trade["entry_commission"] != 2 or trade["exit_commission"] != 2):
            raise ValueError("MES operating fees must equal USD2 per side")
        if any(abs(trade[key] * 4 - round(trade[key] * 4)) > 1e-8 for key in ("entry_fill", "exit_fill")):
            raise ValueError("Directional modeled fills must remain on quarter-point ticks")


def run_split(frame: pd.DataFrame, source_qa: dict, config: dict,
              profile_name: str, profile: dict, name: str) -> dict:
    if name not in SPLITS:
        raise ValueError("This directional research entrypoint refuses final evaluation")
    from research.futures_engine import run_futures_backtest
    from research.futures_statistics import summarize_futures_trades
    start, end, sessions = SPLITS[name]
    if source_qa["included_sessions"] != sessions:
        raise ValueError("Complete Globex session count differs from frozen protocol")
    arrays = causal_direction_signals(frame, config)
    masks = execution_masks(frame)
    times = (frame["time"].astype("int64") // 1_000_000_000).to_numpy(np.int64)
    result = run_futures_backtest(
        times, *(frame[column].to_numpy(float) for column in ("open", "high", "low", "close")),
        arrays["direction_signals"], arrays["stop_distances"], arrays["target_distances"],
        contract_multiplier=5, initial_equity=CAPITAL, costs=CostModel(**profile["costs"]),
        flat_fee_per_contract_per_side=profile["flat_fee_per_contract_per_side"],
        entry_allowed=masks["entry_allowed"], exit_signals=masks["exit_signals"],
        max_holding_bars=12, max_holding_days=1, max_signal_age_seconds=300,
    )
    assert_directional_trade_integrity(result["trades"], profile_name)
    for trade in result["trades"]:
        first, last = int(trade["entry_index"]), int(trade["exit_index"])
        if masks["calendar"]["sessions"].iloc[first] != masks["calendar"]["sessions"].iloc[last]:
            raise ValueError("Position crossed its daily-flat session")
        if 16 * 60 + 45 < masks["calendar"]["minutes"][last] < 18 * 60:
            raise ValueError("Directional position remained past daily-flat deadline")
    statistics = summarize_futures_trades(result["trades"])
    aware = [dict(trade, exit_time=pd.Timestamp(trade["exit_time"], unit="s", tz="UTC").to_pydatetime())
             for trade in result["trades"]]
    first_day, last_day = frame["time"].iloc[0].floor("D"), frame["time"].iloc[-1].floor("D") + pd.Timedelta(days=1)
    daily = daily_realized_returns(aware, CAPITAL, first_day.to_pydatetime(), last_day.to_pydatetime())
    if len(daily) >= 14:
        bootstrap = moving_block_bootstrap_mean([day["return"] for day in daily], block_size=7, replications=10000, seed=20261004)
    else:
        bootstrap = {"status": "insufficient_calendar_blocks", "calendar_observations": len(daily),
                     "block_size_calendar_days": 7, "minimum_observations": 14,
                     "positive_mean_confirmed_one_sided_95": False}
    return {"engine_summary": result["summary"], "statistics": statistics, "trades": result["trades"],
            "daily_realized_returns": daily, "bootstrap": bootstrap, "source_quality": source_qa}


def develop() -> dict:
    plan = json.loads((OUT / "preregistration.json").read_text())
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != plan["source_sha256"]:
        raise ValueError("Pinned actual-price source changed")
    for path, expected in plan["frozen_file_sha256"].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError("Preregistered directional code or protocol changed: " + path)
    if (OUT / "final_evaluation_receipt.json").exists():
        raise ValueError("Final was evaluated; cannot replace frozen selection")
    source = load_source(final=False)
    frames = {name: complete_session_source(source, start, end) for name, (start, end, _) in SPLITS.items()}
    (OUT / "source_quality_receipt.json").write_text(json.dumps({name: qa for name, (_, qa) in frames.items()}, indent=2) + "\n")
    rows = []
    for config in plan["family"]:
        for profile_name, profile in plan["cost_profiles"].items():
            runs = {name: run_split(frame, qa, config, profile_name, profile, name) for name, (frame, qa) in frames.items()}
            statistics = [runs[name]["statistics"] for name in ("development", "validation")]
            count = sum(stat["eligible_trades"] for stat in statistics)
            projection = count * 36 / 27
            financial = all(stat["eligible_trades"] > 0 and stat["natural_net_profit"] > 0
                            and stat["net_profit"] > 0 and stat["win_rate"] >= .5
                            and stat["risk_breaches"] == 0 for stat in statistics)
            means = [stat["mean_net_pnl_per_natural_trade"] for stat in statistics]
            row = {"config": config, "cost_profile": profile_name, "cost_parameters": profile,
                   "runs": runs, "passes_financial_criteria": financial,
                   "development_validation_natural_trades": count, "projected_total_natural_trades": projection,
                   "selection_eligible": bool(financial and projection >= 500),
                   "selection_score_minimum_mean_natural_net_return": min(means) / CAPITAL if all(value is not None for value in means) else None,
                   "tie_validation_total_net_return": statistics[1]["net_profit"] / CAPITAL}
            rows.append(row)
            print(json.dumps({"config": config["name"], "cost_profile": profile_name,
                              "development_trades": statistics[0]["eligible_trades"], "validation_trades": statistics[1]["eligible_trades"],
                              "development_net": statistics[0]["net_profit"], "validation_net": statistics[1]["net_profit"],
                              "development_wins": statistics[0]["win_rate"], "validation_wins": statistics[1]["win_rate"],
                              "financial": financial, "eligible": row["selection_eligible"], "projected_count": projection}), flush=True)
    eligible = [row for row in rows if row["selection_eligible"]]
    ranked = sorted(eligible, key=lambda row: (-row["selection_score_minimum_mean_natural_net_return"],
                                             -row["tie_validation_total_net_return"], row["config"]["name"], row["cost_profile"]))
    report = {"preregistration": plan, "candidate_results": rows, "eligible_count": len(eligible),
              "financial_criteria_pass_count": sum(row["passes_financial_criteria"] for row in rows),
              "ranked_eligible_names": [{"config": row["config"]["name"], "cost_profile": row["cost_profile"]} for row in ranked],
              "unique_strategy_configurations": 24, "strategy_cost_variants": 48,
              "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "engine_sha256": hashlib.sha256(Path("research/futures_engine.py").read_bytes()).hexdigest(),
              "statistics_sha256": hashlib.sha256(Path("research/futures_statistics.py").read_bytes()).hexdigest(),
              "final": "UNTOUCHED; root must freeze one global directional candidate first", "paper_approved": False,
              "actual_futures_loss_bound_established": False, "short_liabilities_unbounded": True}
    (OUT / "development_report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--develop", action="store_true", required=True)
    parser.parse_args()
    report = develop()
    print(json.dumps({"eligible_count": report["eligible_count"], "financial_criteria_pass_count": report["financial_criteria_pass_count"],
                      "final": report["final"]}))


if __name__ == "__main__":
    main()
