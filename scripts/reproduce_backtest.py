"""Recompute frozen results without selecting strategies or editing receipts."""

from dataclasses import replace
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from trading_agent.backtest import load_bars, parse_time, run_backtest
from trading_agent.market import aggregate_bars
from trading_agent.risk import DEFAULT_COSTS
from trading_agent.strategy import StrategyConfig


def main():
    stored = json.loads((ROOT / "artifacts/backtest_report.json").read_text())
    frozen = stored["selected"]
    config = StrategyConfig.from_dict(frozen["config"])
    old = aggregate_bars(load_bars(ROOT / "data/eurusd_h1.csv"), config.bar_hours)
    recent = aggregate_bars(load_bars(ROOT / "data/eurusd_yahoo_h1.csv"), config.bar_hours)
    start = parse_time(frozen["final_start"])
    validation = parse_time("2019-01-01")
    costs = DEFAULT_COSTS
    stress = replace(costs, spread_pips=costs.spread_pips * 2,
        slippage_pips=costs.slippage_pips * 2, commission_bps=costs.commission_bps * 2,
        minimum_commission=costs.minimum_commission * 2)
    checks = [
        ("development", run_backtest(old, config, end=validation)["summary"], stored["development"]),
        ("validation", run_backtest(old, config, start=validation)["summary"], stored["validation"]),
        ("final", run_backtest(recent, config, start=start)["summary"], stored["final"]["summary"]),
        ("stress", run_backtest(recent, config, costs=stress, start=start)["summary"], stored["stress_2x_costs"]),
    ]
    for name, actual, expected in checks:
        for key in ("net_profit", "eligible_trades", "win_rate", "risk_breaches"):
            if abs(actual[key] - expected[key]) > 1e-7:
                raise AssertionError(f"{name}.{key} differs: {actual[key]} vs {expected[key]}")
        print(name, "matches", actual["eligible_trades"], "trades", "net", round(actual["net_profit"], 6))


if __name__ == "__main__":
    main()
