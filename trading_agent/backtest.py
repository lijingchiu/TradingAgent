"""Chronological research with a once-only, untouched out-of-sample gate.

Run ``python -m trading_agent.backtest --data data/eurusd_yahoo_d1.csv``.
The fixed family is ranked using development and validation alone; final-test
results are never used to choose a different configuration.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .execution import Bar, evaluate_long, force_close, open_long
from .risk import DEFAULT_COSTS, CostModel, size_position
from .market import aggregate_bars
from .strategy import (StrategyConfig, candidate_configs, cost_aware_candidate_configs,
                       compute_features, entry_signal, trade_levels)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    # Unknown source wall-clock stamps are only used for ordering/elapsed days.
    # They must not be used to infer exchange opening times.
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def load_bars(path: Path | str) -> list[Bar]:
    with Path(path).open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    bars = [Bar(time=parse_time(row["timestamp"]), open=float(row["open"]),
                high=float(row["high"]), low=float(row["low"]), close=float(row["close"])) for row in rows]
    for index, bar in enumerate(bars):
        if min(bar.open, bar.high, bar.low, bar.close) <= 0:
            raise ValueError(f"Nonpositive price at row {index}")
        if not all(math.isfinite(v) for v in (bar.open, bar.high, bar.low, bar.close)):
            raise ValueError(f"Nonfinite price at row {index}")
        if bar.low > min(bar.open, bar.close) or bar.high < max(bar.open, bar.close) or bar.low > bar.high:
            raise ValueError(f"Invalid OHLC at row {index}")
        if index and bars[index - 1].time >= bar.time:
            raise ValueError(f"Non-increasing timestamps at row {index}")
    return bars


def jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def _wilson(wins: int, total: int) -> list[float] | None:
    if not total:
        return None
    z = 1.96
    rate = wins / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    spread = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return [center - spread, center + spread]


def run_backtest(
    bars: list[Bar], config: StrategyConfig, initial_equity: float = 100_000.0,
    costs: CostModel = DEFAULT_COSTS, start: datetime | None = None,
    end: datetime | None = None, features: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """One position; prior-close signal; next-open fill; identical paper exits.

    Splits begin flat. Historical pre-split bars warm indicators, and the bar
    immediately before a split may generate its first next-open entry. All
    residual holdings are explicitly liquidated at the split's final close.
    """
    features = compute_features(bars, config) if features is None else features
    indices = [i for i, bar in enumerate(bars) if (start is None or bar.time >= start)
               and (end is None or bar.time < end)]
    equity = initial_equity
    position = None
    trades: list[Any] = []
    curve: list[dict[str, Any]] = []
    peak = initial_equity
    max_drawdown = 0.0
    rejected_entries = 0
    for index in indices:
        bar = bars[index]
        existed = position is not None
        if position is not None:
            closed = evaluate_long(position, bar, costs=costs)
            if closed is not None:
                trades.append(closed)
                equity += closed.net_pnl
                position = None
        if position is None and not existed and index > 0 and entry_signal(features[index - 1], config):
            stop_distance, target_distance = trade_levels(features[index - 1], config)
            try:
                plan = size_position(equity, bar.open, stop_distance, max_days=config.max_days, costs=costs)
                position = open_long(plan, bar.time, target_price=bar.open + target_distance,
                                     signal_time=bars[index - 1].time)
                closed = evaluate_long(position, bar, costs=costs)
                if closed is not None:
                    trades.append(closed)
                    equity += closed.net_pnl
                    position = None
            except ValueError:
                rejected_entries += 1
        marked = equity
        if position is not None:
            # Liquidation mark includes an exit spread/slippage and commission.
            plan = position.plan
            half_cost = (costs.spread_pips / 2 + costs.slippage_pips) * costs.pip_size
            exit_fill = max(0.0, bar.close - half_cost)
            exit_fee = max(costs.minimum_commission, plan.units * exit_fill * costs.commission_bps / 10_000)
            marked += plan.units * (exit_fill - plan.entry_fill) - plan.entry_commission - exit_fee
        peak = max(peak, marked)
        max_drawdown = max(max_drawdown, (peak - marked) / peak if peak else 0.0)
        curve.append({"time": bar.time.isoformat(), "equity": round(marked, 8)})
    forced_count = 0
    if position is not None and indices:
        final_bar = bars[indices[-1]]
        closed = force_close(position, final_bar.time, final_bar.close, "sample_end")
        trades.append(closed)
        equity += closed.net_pnl
        forced_count = 1
        curve[-1]["equity"] = round(equity, 8)
    natural = [trade for trade in trades if trade.reason != "sample_end"]
    wins = sum(trade.net_pnl > 0 for trade in natural)
    gross_wins = sum(max(0.0, trade.net_pnl) for trade in trades)
    gross_losses = sum(max(0.0, -trade.net_pnl) for trade in trades)
    total_commission = sum(trade.entry_commission + trade.exit_commission for trade in trades)
    total_price_cost = sum(trade.units * ((trade.entry_fill - trade.entry_mid)
                                         + (trade.exit_mid - trade.exit_fill)) for trade in trades)
    summary = {
        "initial_equity": initial_equity, "ending_equity": equity,
        "net_profit": equity - initial_equity,
        "net_return": (equity - initial_equity) / initial_equity,
        "closed_trades": len(trades), "eligible_trades": len(natural),
        "wins": wins, "win_rate": wins / len(natural) if natural else 0.0,
        "win_rate_wilson_95": _wilson(wins, len(natural)),
        "profit_factor": gross_wins / gross_losses if gross_losses else (None if not gross_wins else "infinity"),
        "total_commission": total_commission, "total_carry": sum(trade.carry for trade in trades),
        "total_spread_slippage_cost": total_price_cost,
        "total_transaction_cost": total_price_cost + total_commission + sum(trade.carry for trade in trades),
        "gross_mid_profit": sum(trade.units * (trade.exit_mid - trade.entry_mid) for trade in trades),
        "max_account_drawdown_close_marks": max_drawdown,
        "max_trade_adverse_equity_fraction": max(
            (trade.max_adverse_excursion / trade.entry_equity for trade in trades), default=0.0),
        "max_trade_peak_drawdown_equity_fraction": max(
            (trade.max_drawdown / trade.entry_equity for trade in trades), default=0.0),
        "risk_breaches": sum(bool(trade.risk_breach) for trade in trades),
        "terminal_liquidations": forced_count, "rejected_entries": rejected_entries,
        "first_bar": bars[indices[0]].time.isoformat() if indices else None,
        "last_bar": bars[indices[-1]].time.isoformat() if indices else None,
    }
    return {"summary": summary, "trades": [jsonable(asdict(trade)) for trade in trades], "equity_curve": curve}


def qualifying(summary: dict[str, Any], minimum_trades: int = 30) -> bool:
    return bool(summary["eligible_trades"] >= minimum_trades and summary["win_rate"] >= .5
                and summary["net_profit"] > 0 and summary["risk_breaches"] == 0)


def freeze_research(data_path: Path, out_dir: Path, initial_equity: float = 100_000.0,
                    validation_start: str = "2019-01-01", final_start: str = "2025-01-01",
                    family_name: str = "baseline", bar_hours: int = 1) -> dict[str, Any]:
    if (out_dir / "holdout_evaluation_receipt.json").exists():
        raise ValueError("The final holdout was already inspected; frozen selection cannot be replaced")
    bars = aggregate_bars(load_bars(data_path), hours=bar_hours)
    validation_at, final_at = parse_time(validation_start), parse_time(final_start)
    if validation_at >= final_at:
        raise ValueError("Validation must precede final holdout")
    if family_name not in ("baseline", "cost_aware"):
        raise ValueError("Unknown research family")
    family = candidate_configs() if family_name == "baseline" else cost_aware_candidate_configs()
    family = [replace(config, bar_hours=bar_hours) for config in family]
    prefinal = [bar for bar in bars if bar.time < final_at]
    if not prefinal:
        raise ValueError("Pre-final development and validation bars are required")
    out_dir.mkdir(parents=True, exist_ok=True)
    preregistration = {
        "protocol": "Freeze family before final; select using development and validation; evaluate untouched final once",
        "family_name": family_name,
        "bar_hours": bar_hours,
        "research_stages": ([{"name": "initial small-target family", "trials": 24},
                             {"name": "cost diagnosis: larger moves and volatility floors", "trials": 48},
                             {"name": "cost diagnosis: shorter stops and volatility floors", "trials": 48}]
                            if family_name == "cost_aware" else [{"name": "initial small-target family", "trials": 24}]),
        "source_file": str(data_path), "sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "candidate_count": len(family), "candidates": [config.to_dict() for config in family],
        "validation_start": validation_start, "final_start": final_start,
        "minimum_final_trades": 30, "minimum_final_win_rate": .5,
        "positive_final_net_profit_required": True, "zero_risk_breaches_required": True,
        "terminal_liquidations_excluded_from_win_rate": True,
        "cost_model": asdict(DEFAULT_COSTS), "initial_equity": initial_equity,
    }
    # Persist the candidate family before calculating any candidate results.
    (out_dir / "research_preregistration.json").write_text(json.dumps(jsonable(preregistration), indent=2) + "\n")
    candidate_results = []
    for config in family:
        features = compute_features(prefinal, config)
        development = run_backtest(prefinal, config, initial_equity, end=validation_at, features=features)["summary"]
        validation = run_backtest(prefinal, config, initial_equity, start=validation_at, features=features)["summary"]
        eligible = qualifying(development) and qualifying(validation)
        candidate_results.append({"config": config.to_dict(), "development": development,
                                  "validation": validation, "selection_eligible": eligible,
                                  "selection_score": min(development["net_return"], validation["net_return"])})
    viable = [row for row in candidate_results if row["selection_eligible"]]
    # The fallback is still frozen and tested, but paper eligibility stays off.
    selection_pool = viable or candidate_results
    selected = max(selection_pool, key=lambda row: (row["selection_score"], row["validation"]["net_return"], row["config"]["name"]))
    config = StrategyConfig.from_dict(selected["config"])
    frozen = {"config": config.to_dict(), "selection_eligible": bool(viable),
              "selected_using": "development and validation only", "candidate_count": len(family),
              "family_name": family_name,
              "data_sha256": preregistration["sha256"], "final_start": final_start,
              "initial_equity": initial_equity}
    (out_dir / "selected_strategy_before_holdout.json").write_text(json.dumps(frozen, indent=2) + "\n")
    preparation = {"protocol": preregistration, "selected": frozen, "candidate_results": candidate_results,
                   "development": selected["development"], "validation": selected["validation"]}
    (out_dir / "research_before_holdout.json").write_text(json.dumps(jsonable(preparation), indent=2) + "\n")
    pending = {**frozen, "paper_approved": False, "gate_reasons": ["Untouched final evaluation pending"],
               "final_summary": None, "cost_model": asdict(DEFAULT_COSTS)}
    (out_dir / "selected_strategy.json").write_text(json.dumps(jsonable(pending), indent=2) + "\n")
    return preparation


def evaluate_frozen(final_data_path: Path, out_dir: Path) -> dict[str, Any]:
    preparation = json.loads((out_dir / "research_before_holdout.json").read_text())
    frozen = preparation["selected"]
    config = StrategyConfig.from_dict(frozen["config"])
    initial_equity = frozen["initial_equity"]
    final_at = parse_time(frozen["final_start"])
    bars = aggregate_bars(load_bars(final_data_path), hours=config.bar_hours)
    if not any(bar.time >= final_at for bar in bars):
        raise ValueError("Independent final observations are required")
    first_final = next(i for i, bar in enumerate(bars) if bar.time >= final_at)
    warmup = max(config.ema_period * 3, config.atr_period * 3, config.rsi_period * 3)
    if first_final < warmup:
        raise ValueError(f"Final data requires at least {warmup} pre-holdout warmup bars; found {first_final}")
    # A separate validated source supplies contiguous pre-holdout warmup.
    # Never concatenate an old source across a multi-year missing interval.
    if any((bars[i].time - bars[i - 1].time).days > 10 for i in range(first_final - warmup + 1, first_final + 1)):
        raise ValueError("Final warmup contains a gap larger than ten calendar days")
    final_hash = hashlib.sha256(final_data_path.read_bytes()).hexdigest()
    receipt_path = out_dir / "holdout_evaluation_receipt.json"
    if receipt_path.exists():
        receipt = json.loads(receipt_path.read_text())
        report_path = out_dir / "backtest_report.json"
        if receipt["config"] == config.to_dict() and receipt["final_sha256"] == final_hash and report_path.exists():
            return json.loads(report_path.read_text())
        raise ValueError("A final holdout was already inspected; do not select another strategy using it")
    receipt = {"config": config.to_dict(), "final_sha256": final_hash,
               "final_source_file": str(final_data_path), "final_start": frozen["final_start"],
               "evaluated_at": datetime.now(timezone.utc).isoformat()}
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    final = run_backtest(bars, config, initial_equity, start=final_at)
    # Stress uses the already frozen strategy and can never feed selection.
    stress_costs = replace(DEFAULT_COSTS, spread_pips=DEFAULT_COSTS.spread_pips * 2,
                           slippage_pips=DEFAULT_COSTS.slippage_pips * 2,
                           commission_bps=DEFAULT_COSTS.commission_bps * 2,
                           minimum_commission=DEFAULT_COSTS.minimum_commission * 2)
    stress = run_backtest(bars, config, initial_equity, costs=stress_costs, start=final_at)
    approved = frozen["selection_eligible"] and qualifying(final["summary"])
    reasons = []
    if not frozen["selection_eligible"]:
        reasons.append("No candidate passed development and validation requirements")
    if final["summary"]["eligible_trades"] < 30:
        reasons.append("Final holdout has fewer than 30 naturally closed trades")
    if final["summary"]["win_rate"] < .5:
        reasons.append("Final net winning-trade proportion is below 50%")
    if final["summary"]["net_profit"] <= 0:
        reasons.append("Final profit is not positive after modeled costs")
    if final["summary"]["risk_breaches"]:
        reasons.append("Final test contains a risk-limit breach")
    report = {**preparation, "holdout_source": receipt, "final": final,
              "stress_2x_costs": stress["summary"], "paper_approved": approved,
              "gate_reasons": reasons,
              "limitations": ["Past profitability does not establish future profitability",
                              f"Validation was reused to develop cost-aware families; all {frozen['candidate_count']} trials are disclosed",
                              "Old mirror timezone and executable-price provenance are unknown; four-hour alignment is exploratory",
                              "Public FX observations are not independently authenticated executable quotes",
                              "OHLC execution conservatively gives stop priority when both thresholds touch",
                              "Win-rate confidence intervals ignore serial trade dependence",
                              "Very small fully funded positions limit profits and absolute losses",
                              "Realized and close-mark account drawdown can accumulate across separate trades"]}
    (out_dir / "backtest_report.json").write_text(json.dumps(jsonable(report), indent=2) + "\n")
    strategy = {**frozen, "paper_approved": approved, "gate_reasons": reasons,
                "final_summary": final["summary"], "cost_model": asdict(DEFAULT_COSTS),
                "initial_equity": initial_equity}
    (out_dir / "selected_strategy.json").write_text(json.dumps(jsonable(strategy), indent=2) + "\n")
    return report


def research(data_path: Path, out_dir: Path, initial_equity: float = 100_000.0,
             validation_start: str = "2019-01-01", final_start: str = "2025-01-01",
             final_data_path: Path | None = None, family_name: str = "baseline",
             bar_hours: int = 1) -> dict[str, Any]:
    if (out_dir / "holdout_evaluation_receipt.json").exists():
        return evaluate_frozen(final_data_path or data_path, out_dir)
    freeze_research(data_path, out_dir, initial_equity, validation_start, final_start, family_name, bar_hours)
    return evaluate_frozen(final_data_path or data_path, out_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=Path("data/eurusd_yahoo_d1.csv"))
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts"))
    parser.add_argument("--initial-equity", type=float, default=100_000.0)
    parser.add_argument("--validation-start", default="2019-01-01")
    parser.add_argument("--final-start", default="2025-01-01")
    parser.add_argument("--final-data", type=Path, help="Separate vetted source, including pre-holdout warmup")
    parser.add_argument("--freeze-only", action="store_true", help="Select on development/validation without reading final outcomes")
    parser.add_argument("--evaluate-frozen", action="store_true", help="Evaluate the existing frozen config; never retune")
    parser.add_argument("--family", choices=("baseline", "cost_aware"), default="baseline")
    parser.add_argument("--bar-hours", choices=(1, 4), type=int, default=1)
    args = parser.parse_args()
    if args.freeze_only:
        report = freeze_research(args.data, args.out_dir, args.initial_equity, args.validation_start,
                                 args.final_start, args.family, args.bar_hours)
        print(json.dumps({"selected": report["selected"], "development": report["development"],
                          "validation": report["validation"], "final": "untouched"}, indent=2))
    else:
        report = (evaluate_frozen(args.final_data or args.data, args.out_dir) if args.evaluate_frozen else
                  research(args.data, args.out_dir, args.initial_equity, args.validation_start,
                           args.final_start, args.final_data, args.family, args.bar_hours))
        print(json.dumps({"selected": report["selected"]["config"], "final": report["final"]["summary"],
                          "paper_approved": report["paper_approved"], "gate_reasons": report["gate_reasons"]}, indent=2))


if __name__ == "__main__":
    main()
