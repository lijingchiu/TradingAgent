"""Preregistered, research-only native MES mirror study; never activates orders.

Development and validation load no April rows. Final testing requires a single
frozen eligible configuration receipt. Historical variation-margin risk is not
proved by the research engine's numeric fully collateralized price-floor model.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from research.intraday_engine import run_intraday_backtest
from research.statistics import moving_block_bootstrap_mean, summarize_trades
from trading_agent.risk import CostModel


OUT = Path("artifacts/intraday/mean_reversion/futures_mes")
SOURCE = OUT / "source/MES_5min_20260120_20260415.csv"
COSTS = CostModel(pip_size=.25, spread_pips=2, slippage_pips=1,
                  commission_bps=.35, minimum_commission=.1)
CAPITAL = 5_000_000.0
SPLITS = {
    "development": ("2026-01-21", "2026-02-14", 18),
    "validation": ("2026-02-17", "2026-02-28", 9),
    "final": ("2026-04-01", "2026-04-16", 10),
}


def read_plan() -> dict:
    plan = json.loads((OUT / "preregistration.json").read_text())
    if len(plan["family"]) != 24 or not plan["written_before_any_mes_strategy_pnl"]:
        raise ValueError("The complete 24-configuration preregistration is required")
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != plan["source_sha256"]:
        raise ValueError("Pinned native M5 source hash changed")
    return plan


def load_source(*, final: bool = False) -> pd.DataFrame:
    frame = pd.read_csv(SOURCE)
    frame["time"] = pd.to_datetime(frame["datetime"], utc=True)
    # Native prices were inspected for source quality, never final strategy
    # outcomes. This explicit research boundary keeps April out of selection.
    if not final:
        frame = frame.loc[frame["time"] < pd.Timestamp("2026-03-01", tz="UTC")].copy()
    prices = frame[["open", "high", "low", "close"]].to_numpy(float)
    if (not np.isfinite(prices).all() or (prices <= 0).any()
            or not frame["time"].is_monotonic_increasing
            or frame["time"].duplicated().any()):
        raise ValueError("Source must be positive, finite, unique and sorted")
    if ((frame["low"] > frame[["open", "close"]].min(axis=1)).any()
            or (frame["high"] < frame[["open", "close"]].max(axis=1)).any()
            or (frame["high"] < frame["low"]).any()
            or not np.allclose(prices * 4, np.rint(prices * 4), atol=1e-8, rtol=0)):
        raise ValueError("Source OHLC geometry or actual MES tick grid is invalid")
    return frame.reset_index(drop=True)


def session_arrays(frame: pd.DataFrame, start: str, end: str) -> dict:
    """Known clock/calendar masks; no future prices or future trading outcomes."""
    local = frame["time"].dt.tz_convert("America/New_York")
    minutes = local.dt.hour.to_numpy() * 60 + local.dt.minute.to_numpy()
    wall_dates = local.dt.tz_localize(None).dt.normalize()
    session_dates = wall_dates + pd.to_timedelta((minutes >= 18 * 60).astype(int), unit="D")
    valid_date = ((session_dates >= pd.Timestamp(start))
                  & (session_dates < pd.Timestamp(end))
                  & (session_dates.dt.weekday < 5)
                  & (session_dates.dt.month != 3)
                  & ~session_dates.isin(pd.to_datetime(["2026-02-16", "2026-04-03"])))
    allowed_clock = (minutes >= 18 * 60 + 5) | (minutes <= 16 * 60 + 35)
    return {
        "entry_allowed": valid_date.to_numpy() & allowed_clock,
        # The 16:45 bar becomes complete at 16:50. Its signal exits at that
        # next observed open, not at an unavailable within-bar price.
        "exit_signals": minutes == 16 * 60 + 45,
        "session_dates": session_dates,
        "valid_dates": valid_date.to_numpy(),
        "local_minutes": minutes,
    }


def causal_signals(frame: pd.DataFrame, config: dict) -> dict:
    closes = frame["close"].astype(float)
    mean = closes.rolling(config["window"], min_periods=config["window"]).mean()
    deviation = closes.rolling(config["window"], min_periods=config["window"]).std(ddof=0)
    z = (closes - mean) / deviation.replace(0, np.nan)
    ema = closes.ewm(span=96, adjust=False, min_periods=96).mean()
    complete = np.arange(len(frame)) >= 96
    signal = (z <= -config["z_threshold"]) & (closes >= frame["open"])
    if config["regime"] == "above_ema96":
        signal &= closes >= ema
    elif config["regime"] != "none":
        raise ValueError("Unregistered regime")
    return {
        "entry_signals": signal.fillna(False).to_numpy(bool) & complete,
        "stop_distances": np.full(len(frame), config["stop_points"]),
        "target_distances": np.full(len(frame), config["target_points"]),
        "z": z.to_numpy(float), "ema96": ema.to_numpy(float),
    }


def assert_scheduled_close_coverage(frame: pd.DataFrame, masks: dict) -> None:
    observed_days = set(masks["session_dates"][masks["valid_dates"]].dt.date)
    close_slots = np.flatnonzero((masks["local_minutes"] == 16 * 60 + 50)
                                 & masks["valid_dates"])
    clock_times = (frame["time"].astype("int64") // 1_000_000_000).to_numpy(np.int64)
    complete_slots = [slot for slot in close_slots if slot > 0
                      and masks["local_minutes"][slot - 1] == 16 * 60 + 45
                      and clock_times[slot] - clock_times[slot - 1] == 300
                      and masks["session_dates"].iloc[slot - 1] == masks["session_dates"].iloc[slot]]
    close_days = set(masks["session_dates"].iloc[complete_slots].dt.date)
    if observed_days - close_days:
        raise ValueError("Missing scheduled daily-flat quote: " + str(sorted(observed_days - close_days)))


def run_split(source: pd.DataFrame, config: dict, name: str,
              costs: CostModel = COSTS) -> dict:
    if name == "final":
        raise ValueError("This development entrypoint does not evaluate final; use a separately audited frozen-config evaluator")
    start, end, expected_sessions = SPLITS[name]
    frame = source.loc[(source["time"] >= pd.Timestamp(start, tz="UTC"))
                       & (source["time"] < pd.Timestamp(end, tz="UTC"))].copy().reset_index(drop=True)
    masks = session_arrays(frame, start, end)
    assert_scheduled_close_coverage(frame, masks)
    signals = causal_signals(frame, config)
    times = (frame["time"].astype("int64") // 1_000_000_000).to_numpy(np.int64)
    result = run_intraday_backtest(
        times, *(frame[column].to_numpy(float) for column in ("open", "high", "low", "close")),
        signals["entry_signals"], signals["stop_distances"], signals["target_distances"],
        entry_allowed=masks["entry_allowed"], exit_signals=masks["exit_signals"],
        max_holding_bars=12, max_holding_days=1, initial_equity=CAPITAL,
        costs=costs, quote_kind="mid", unit_step=5, max_signal_age_seconds=300,
    )
    if any(trade["units"] % 5 != 0 or any(abs(trade[key] * 4 - round(trade[key] * 4)) > 1e-8
                                         for key in ("entry_fill", "exit_fill"))
           for trade in result["trades"]):
        raise ValueError("Fractional MES contracts or impossible off-tick fills")
    stats = summarize_trades(result["trades"])
    daily = {day.isoformat(): 0.0 for day in sorted(set(masks["session_dates"][masks["valid_dates"]].dt.date))}
    for trade in result["trades"]:
        entry_index = int(trade["entry_index"])
        exit_index = int(trade["exit_index"])
        day = masks["session_dates"].iloc[exit_index].date().isoformat()
        if day not in daily or masks["session_dates"].iloc[entry_index] != masks["session_dates"].iloc[exit_index]:
            raise ValueError("Trade survived the declared Globex daily-flat session")
        exit_minutes = int(masks["local_minutes"][exit_index])
        if 16 * 60 + 50 < exit_minutes < 18 * 60:
            raise ValueError("Exit occurred after scheduled daily-flat deadline")
        daily[day] += trade["net_pnl"]
    if len(daily) != expected_sessions:
        raise ValueError("Session-count metadata inconsistent with actual native bars")
    if len(daily) >= 14:
        bootstrap = moving_block_bootstrap_mean([value / CAPITAL for value in daily.values()],
                                               block_size=7, replications=10000, seed=20261004)
        bootstrap["method"] = "Circular seven-Globex-session moving-block percentile bootstrap"
        bootstrap["block_size_sessions"] = bootstrap.pop("block_size_calendar_days")
        bootstrap["session_observations"] = bootstrap.pop("daily_observations")
    else:
        bootstrap = {"status": "insufficient_independent_session_blocks", "block_size_sessions": 7,
                     "session_observations": len(daily), "minimum_two_blocks": 14,
                     "positive_mean_confirmed_one_sided_95": False,
                     "note": "The interval is too short for the prespecified block-bootstrap confidence claim"}
    return {"engine_summary": result["summary"], "statistics": stats,
            "session_net_pnl": daily, "bootstrap": bootstrap,
            "trades": result["trades"]}


def develop() -> dict:
    plan = read_plan()
    if (OUT / "final_evaluation_receipt.json").exists():
        raise ValueError("Final was already evaluated; development cannot replace its frozen selection")
    source = load_source(final=False)
    code_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    rows = []
    for config in plan["family"]:
        runs = {name: run_split(source, config, name) for name in ("development", "validation")}
        stats = [runs[name]["statistics"] for name in ("development", "validation")]
        total_natural = sum(summary["eligible_trades"] for summary in stats)
        projected = total_natural * 37 / 27
        passes_financial = all(summary["eligible_trades"] > 0
                               and summary["natural_net_profit"] > 0
                               and summary["net_profit"] > 0
                               and summary["win_rate"] >= .5
                               and summary["risk_breaches"] == 0 for summary in stats)
        eligible = passes_financial and projected >= 500
        scores = [summary["mean_net_pnl_per_natural_trade"] for summary in stats]
        row = {"config": config, "runs": runs, "development_validation_natural_trades": total_natural,
               "projected_total_natural_trades": projected, "passes_financial_criteria": passes_financial,
               "selection_eligible": eligible,
               "score": min(scores) if all(value is not None for value in scores) else None}
        rows.append(row)
        print(json.dumps({"candidate": config["name"], "development": stats[0],
                          "validation": stats[1], "projected_total_natural_trades": projected,
                          "eligible": eligible}), flush=True)
    eligible = [row for row in rows if row["selection_eligible"]]
    report = {"preregistration": plan, "code_sha256": code_hash,
              "engine_sha256": hashlib.sha256(Path("research/intraday_engine.py").read_bytes()).hexdigest(),
              "candidate_results": rows, "eligible_count": len(eligible), "final": "UNTOUCHED",
              "paper_approved": False, "derivative_variation_margin_bound_established": False}
    if eligible:
        selected = max(eligible, key=lambda row: row["score"])
        frozen = {"config": selected["config"], "preregistration_sha256": hashlib.sha256(
                  (OUT / "preregistration.json").read_bytes()).hexdigest(), "code_sha256": code_hash,
                  "source_sha256": plan["source_sha256"], "selection_evidence": selected,
                  "final": "NOT EVALUATED", "paper_approved": False}
        (OUT / "selected_before_final.json").write_text(json.dumps(frozen, indent=2, allow_nan=False) + "\n")
        report["frozen_config"] = selected["config"]
    (OUT / "development_report.json").write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--develop", action="store_true", required=True)
    parser.parse_args()
    report = develop()
    print(json.dumps({"eligible_count": report["eligible_count"], "final": report["final"]}))


if __name__ == "__main__":
    main()
