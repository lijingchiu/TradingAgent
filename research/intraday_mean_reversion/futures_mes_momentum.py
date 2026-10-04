"""New MES momentum family, frozen before outcomes; development/validation only.

Source LAST_TRADE candles are an assumed execution midpoint, never observed BBO.
One whole MES contract is measured with two disclosed fee scenarios. Neither
research profitability nor historical risk measurements authorize paper orders.
"""
from __future__ import annotations

import argparse
from datetime import timedelta
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.intraday_engine import run_intraday_backtest
from research.statistics import daily_realized_returns, moving_block_bootstrap_mean, summarize_trades
from trading_agent.risk import CostModel
from .futures_mes import SOURCE, load_source


OUT = Path("artifacts/intraday/mean_reversion/futures_mes_momentum")
CAPITAL = 5_000_000.0
SPLITS = {"development": ("2026-01-21", "2026-02-14", 18),
          "validation": ("2026-02-16", "2026-02-28", 9)}


def calendar(frame: pd.DataFrame) -> dict:
    local = frame["time"].dt.tz_convert("America/New_York")
    minutes = local.dt.hour.to_numpy() * 60 + local.dt.minute.to_numpy()
    dates = local.dt.tz_localize(None).dt.normalize()
    sessions = dates + pd.to_timedelta((minutes >= 18 * 60).astype(int), unit="D")
    available = (frame["time"] + pd.Timedelta(seconds=300)).dt.tz_convert("America/New_York")
    available_minutes = available.dt.hour.to_numpy() * 60 + available.dt.minute.to_numpy()
    return {"minutes": minutes, "sessions": sessions, "availability_minutes": available_minutes}


def complete_session_source(source: pd.DataFrame, start: str, end: str) -> tuple[pd.DataFrame, dict]:
    """Discard excluded/partial source sessions before any feature construction."""
    cal = calendar(source)
    eligible = ((cal["sessions"] >= pd.Timestamp(start)) & (cal["sessions"] < pd.Timestamp(end))
                & (cal["sessions"].dt.weekday < 5) & (cal["sessions"].dt.month != 3)
                & (source["time"].dt.month != 3)
                & ~cal["sessions"].isin(pd.to_datetime(["2026-02-16", "2026-04-01", "2026-04-03"])))
    frame = source.loc[eligible].copy().reset_index(drop=True)
    cal = calendar(frame)
    included, excluded = [], []
    for day in sorted(set(cal["sessions"].dt.date)):
        first = (pd.Timestamp(day - timedelta(days=1)) + pd.Timedelta(hours=18)).tz_localize("America/New_York")
        # No DST change occurs during a normal weekday Globex session.
        expected = pd.date_range(first, periods=276, freq="5min").tz_convert("UTC")
        found = pd.DatetimeIndex(frame.loc[cal["sessions"].dt.date == day, "time"])
        if len(found) == 276 and found.equals(expected):
            included.append(day)
        else:
            excluded.append({"session_date": day.isoformat(), "observed_bars": len(found),
                             "missing_expected_bars": len(expected.difference(found)),
                             "unexpected_bars": len(found.difference(expected))})
    frame = frame.loc[cal["sessions"].dt.date.isin(included)].copy().reset_index(drop=True)
    return frame, {"included_session_dates": [day.isoformat() for day in included],
                   "included_sessions": len(included), "expected_bars_per_session": 276,
                   "incomplete_excluded": excluded, "rows": len(frame)}


def causal_signals(frame: pd.DataFrame, config: dict) -> dict:
    if (frame["time"].dt.month == 3).any() or (calendar(frame)["sessions"].dt.month == 3).any():
        raise ValueError("March rows cannot be used for features or warmup")
    n = len(frame)
    times = (frame["time"].astype("int64") // 1_000_000_000).to_numpy(np.int64)
    closes = frame["close"].to_numpy(float)
    ema = np.full(n, np.nan)
    horizon_return = np.full(n, np.nan)
    slope = np.full(n, np.nan)
    previous_change = np.full(n, np.nan)
    current_change = np.full(n, np.nan)
    signals = np.zeros(n, dtype=bool)
    starts = np.r_[0, np.flatnonzero(np.diff(times) != 300) + 1]
    ends = np.r_[starts[1:], n]
    h = config["horizon"]
    for first, last in zip(starts, ends):
        close = pd.Series(closes[first:last])
        moving = close.ewm(span=config["ema_period"], adjust=False,
                           min_periods=config["ema_period"]).mean()
        local_return = close - close.shift(h)
        local_slope = moving - moving.shift(h)
        change = close.diff()
        common = (close > moving) & (local_slope > 0)
        if config["style"] == "momentum":
            entry = common & (local_return > 0)
        elif config["style"] == "pullback":
            entry = common & (change.shift(1) < 0) & (change > 0)
        else:
            raise ValueError("Unregistered entry style")
        signals[first:last] = entry.fillna(False).to_numpy(bool)
        ema[first:last] = moving.to_numpy(float)
        horizon_return[first:last] = local_return.to_numpy(float)
        slope[first:last] = local_slope.to_numpy(float)
        previous_change[first:last] = change.shift(1).to_numpy(float)
        current_change[first:last] = change.to_numpy(float)
    cal = calendar(frame)
    completed_clock = (cal["availability_minutes"] >= 18 * 60 + 30) | (cal["availability_minutes"] <= 16 * 60 + 15)
    signals &= completed_clock
    return {"entry_signals": signals, "stop_distances": np.full(n, config["stop_points"]),
            "target_distances": np.full(n, config["target_points"]),
            "ema": ema, "horizon_return": horizon_return, "ema_slope": slope,
            "previous_change": previous_change, "current_change": current_change}


def execution_masks(frame: pd.DataFrame) -> dict:
    cal = calendar(frame)
    entry_clock = (cal["minutes"] >= 18 * 60 + 30) | (cal["minutes"] <= 16 * 60 + 15)
    exits = cal["minutes"] == 16 * 60 + 40
    timestamps = (frame["time"].astype("int64") // 1_000_000_000).to_numpy(np.int64)
    for date in set(cal["sessions"].dt.date):
        slots = np.flatnonzero((cal["sessions"].dt.date == date).to_numpy()
                               & (cal["minutes"] == 16 * 60 + 45))
        if len(slots) != 1 or slots[0] == 0 or not exits[slots[0] - 1] or timestamps[slots[0]] - timestamps[slots[0] - 1] != 300:
            raise ValueError("Daily-flat16:40/16:45 adjacent signal/execution quotes absent")
    return {"entry_allowed": entry_clock, "exit_signals": exits, "calendar": cal}


def assert_whole_contract_fees(trades: list[dict], cost_profile: str) -> None:
    for trade in trades:
        if trade["units"] != 5 or trade["trading_lots"] != 1:
            raise ValueError("The study must trade exactly one whole MES contract")
        if cost_profile == "flat2_operating_assumption" and (trade["entry_commission"] != 2 or trade["exit_commission"] != 2):
            raise ValueError("Flat fees must be exactly USD2 per contract per side")
        if any(abs(trade[key] * 4 - round(trade[key] * 4)) > 1e-8 for key in ("entry_fill", "exit_fill")):
            raise ValueError("Modeled fill is off the native MES quarter-point grid")


def run_split(frame: pd.DataFrame, source_qa: dict, config: dict,
              profile_name: str, profile: dict, name: str) -> dict:
    if name not in SPLITS:
        raise ValueError("This entrypoint never evaluates final strategy outcomes")
    start, end, count = SPLITS[name]
    if source_qa["included_sessions"] != count:
        raise ValueError("Included complete session count differs from frozen protocol")
    arrays = causal_signals(frame, config)
    masks = execution_masks(frame)
    times = (frame["time"].astype("int64") // 1_000_000_000).to_numpy(np.int64)
    result = run_intraday_backtest(
        times, *(frame[column].to_numpy(float) for column in ("open", "high", "low", "close")),
        arrays["entry_signals"], arrays["stop_distances"], arrays["target_distances"],
        entry_allowed=masks["entry_allowed"], exit_signals=masks["exit_signals"],
        max_holding_bars=12, max_holding_days=1, initial_equity=CAPITAL,
        costs=CostModel(**profile), quote_kind="mid", unit_step=5, max_signal_age_seconds=300,
    )
    assert_whole_contract_fees(result["trades"], profile_name)
    for trade in result["trades"]:
        first, last = int(trade["entry_index"]), int(trade["exit_index"])
        if masks["calendar"]["sessions"].iloc[first] != masks["calendar"]["sessions"].iloc[last]:
            raise ValueError("Position crossed its declared daily-flat session")
        if 16 * 60 + 45 < masks["calendar"]["minutes"][last] < 18 * 60:
            raise ValueError("Position exited after the scheduled flat deadline")
    stats = summarize_trades(result["trades"])
    stats["gross_last_trade_reference_profit"] = stats.pop("gross_mid_profit")
    stats["price_baseline"] = "LAST_TRADE reference; modeled midpoint fills; not observed MID/BBO"
    for trade in result["trades"]:
        trade["entry_reference_last_trade"] = trade["entry_mid"]
        trade["exit_reference_last_trade"] = trade["exit_mid"]
    aware = [dict(trade, exit_time=pd.Timestamp(trade["exit_time"], unit="s", tz="UTC").to_pydatetime())
             for trade in result["trades"]]
    # The complete Globex first session starts on the preceding NY evening.
    # Calendar returns consequently include that preceding UTC day if needed.
    first_day = frame["time"].iloc[0].floor("D")
    last_day = frame["time"].iloc[-1].floor("D") + pd.Timedelta(days=1)
    daily = daily_realized_returns(aware, CAPITAL, first_day.to_pydatetime(), last_day.to_pydatetime())
    values = [day["return"] for day in daily]
    if len(values) >= 14:
        bootstrap = moving_block_bootstrap_mean(values, block_size=7, replications=10000, seed=20261004)
    else:
        bootstrap = {"status": "insufficient_calendar_blocks", "calendar_observations": len(values),
                     "block_size_calendar_days": 7, "minimum_observations": 14,
                     "positive_mean_confirmed_one_sided_95": False}
    return {"engine_summary": result["summary"], "statistics": stats, "trades": result["trades"],
            "daily_realized_returns": daily, "bootstrap": bootstrap, "source_quality": source_qa}


def develop() -> dict:
    plan = json.loads((OUT / "preregistration.json").read_text())
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != plan["source_sha256"]:
        raise ValueError("Source hash changed")
    if (OUT / "final_evaluation_receipt.json").exists():
        raise ValueError("Final already evaluated; cannot replace frozen selection")
    source = load_source(final=False)
    frames = {name: complete_session_source(source, start, end) for name, (start, end, _) in SPLITS.items()}
    (OUT / "source_quality_receipt.json").write_text(json.dumps({name: qa for name, (_, qa) in frames.items()}, indent=2) + "\n")
    rows = []
    for config in plan["family"]:
        for profile_name, profile in plan["cost_profiles"].items():
            runs = {name: run_split(frame, qa, config, profile_name, profile, name)
                    for name, (frame, qa) in frames.items()}
            stats = [runs[name]["statistics"] for name in ("development", "validation")]
            count = sum(summary["eligible_trades"] for summary in stats)
            projection = count * 36 / 27
            financial = all(summary["eligible_trades"] > 0 and summary["natural_net_profit"] > 0
                            and summary["net_profit"] > 0 and summary["win_rate"] >= .5
                            and summary["risk_breaches"] == 0 for summary in stats)
            score_values = [summary["mean_net_pnl_per_natural_trade"] for summary in stats]
            row = {"config": config, "cost_profile": profile_name, "cost_parameters": profile,
                   "runs": runs, "passes_financial_criteria": financial,
                   "development_validation_natural_trades": count, "projected_total_natural_trades": projection,
                   "selection_eligible": bool(financial and projection >= 500),
                   "selection_score_minimum_mean_natural_net_return": min(score_values) / CAPITAL
                        if all(value is not None for value in score_values) else None,
                   "tie_validation_total_net_return": stats[1]["net_profit"] / CAPITAL}
            rows.append(row)
            print(json.dumps({"config": config["name"], "cost_profile": profile_name,
                              "development_trades": stats[0]["eligible_trades"], "validation_trades": stats[1]["eligible_trades"],
                              "development_net": stats[0]["net_profit"], "validation_net": stats[1]["net_profit"],
                              "development_wins": stats[0]["win_rate"], "validation_wins": stats[1]["win_rate"],
                              "projected_count": projection, "financial": financial, "eligible": row["selection_eligible"]}), flush=True)
    eligible = [row for row in rows if row["selection_eligible"]]
    ranked = sorted(eligible, key=lambda row: (-row["selection_score_minimum_mean_natural_net_return"],
                                             -row["tie_validation_total_net_return"], row["config"]["name"], row["cost_profile"]))
    report = {"preregistration": plan, "candidate_results": rows, "eligible_count": len(eligible),
              "financial_criteria_pass_count": sum(row["passes_financial_criteria"] for row in rows),
              "ranked_eligible_names": [{"config": row["config"]["name"], "cost_profile": row["cost_profile"]} for row in ranked],
              "unique_strategy_configurations": 24, "cost_operating_variants": 48,
              "code_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "engine_sha256": hashlib.sha256(Path("research/intraday_engine.py").read_bytes()).hexdigest(),
              "final": "UNTOUCHED; joint winner freeze belongs to root", "paper_approved": False,
              "futures_variation_margin_bound_established": False}
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
