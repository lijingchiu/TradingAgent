"""Inspectible after-cost statistics; no data fetches or strategy selection.

The functions accept trade dictionaries or dataclasses. Prices and executions
are supplied by the caller. Synthetic self-checks are not performance evidence.
"""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta, timezone
import math
from typing import Any, Iterable, Mapping, Sequence

import numpy as np


UTC = timezone.utc
BOOTSTRAP_SEED = 20261004


def _row(value: Any) -> dict[str, Any]:
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    if isinstance(value, Mapping):
        return dict(value)
    raise TypeError("Each trade must be a mapping or dataclass")


def _finite(value: Any, name: str) -> float:
    if isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{name} must be finite numeric data, not a boolean")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _utc(value: datetime | str | int) -> datetime:
    # The intraday engine emits UTC epoch seconds, never naive wall-clock data.
    if isinstance(value, (int, np.integer)) and not isinstance(value, (bool, np.bool_)):
        return datetime.fromtimestamp(int(value), UTC)
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Trade timestamps must be UTC epoch seconds or explicitly timezone-aware")
    return value.astimezone(UTC)


def _bound(value: datetime | date | str) -> datetime:
    if isinstance(value, str) and len(value) == 10:
        value = date.fromisoformat(value)
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime(value.year, value.month, value.day, tzinfo=UTC)
    return _utc(value)


def wilson_interval(wins: int, total: int, z: float = 1.96) -> list[float] | None:
    """A descriptive interval; it assumes independent Bernoulli observations."""
    if any(isinstance(value, bool) or not isinstance(value, int) for value in (wins, total)):
        raise ValueError("Win and trade counts must be integers")
    if total < 0 or not 0 <= wins <= total:
        raise ValueError("Invalid win/trade counts")
    if total == 0:
        return None
    z = _finite(z, "z")
    if z <= 0:
        raise ValueError("z must be positive")
    rate = wins / total
    denominator = 1 + z * z / total
    center = (rate + z * z / (2 * total)) / denominator
    spread = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, center - spread), min(1.0, center + spread)]


def summarize_trades(trades: Iterable[Any], terminal_reason: str = "sample_end") -> dict[str, Any]:
    """Separate natural-close net expectancy from all-exit account profit."""
    rows = [_row(trade) for trade in trades]
    all_net = [_finite(row["net_pnl"], "net_pnl") for row in rows]
    natural = [row for row in rows if row.get("reason") != terminal_reason]
    natural_net = [_finite(row["net_pnl"], "net_pnl") for row in natural]
    winners = [value for value in natural_net if value > 0]
    losers = [-value for value in natural_net if value < 0]
    count = len(natural)
    average_win = math.fsum(winners) / len(winners) if winners else 0.0
    average_loss = math.fsum(losers) / len(losers) if losers else 0.0
    win_rate = len(winners) / count if count else 0.0
    loss_rate = len(losers) / count if count else 0.0
    expectancy = math.fsum(natural_net) / count if count else None
    decomposed = win_rate * average_win - loss_rate * average_loss if count else None
    loss_sum = math.fsum(losers)
    winner_sum = math.fsum(winners)
    explicit_fees = mid_gross = bid_gross = fill_gross = None
    observed_spread_cost = modeled_spread_cost = slippage_cost = None
    fee_fields_complete = all(all(key in row for key in ("entry_commission", "exit_commission", "carry")) for row in rows)
    if fee_fields_complete:
        explicit_fees = math.fsum(_finite(row[key], key) for row in rows
                                  for key in ("entry_commission", "exit_commission", "carry"))
        if any(_finite(row[key], key) < 0 for row in rows for key in ("entry_commission", "exit_commission", "carry")):
            raise ValueError("The declared commission and carry cost model must use nonnegative fees")
    if all("gross_pnl" in row for row in rows):
        fill_gross = math.fsum(_finite(row["gross_pnl"], "gross_pnl") for row in rows)
        if fee_fields_complete:
            for row, net in zip(rows, all_net):
                after_fees = _finite(row["gross_pnl"], "gross_pnl") - math.fsum(
                    _finite(row[key], key) for key in ("entry_commission", "exit_commission", "carry"))
                if not math.isclose(net, after_fees, rel_tol=1e-10, abs_tol=1e-8):
                    raise ValueError("Trade net P&L does not reconcile gross fill P&L and explicit costs")
    if all(all(row.get(key) is not None for key in ("units", "entry_mid", "exit_mid")) for row in rows):
        mid_gross = math.fsum(_finite(row["units"], "units") *
                              (_finite(row["exit_mid"], "exit_mid") - _finite(row["entry_mid"], "entry_mid"))
                              for row in rows)
    bid_fields_complete = bool(rows) and all(all(row.get(key) is not None for key in
        ("units", "entry_bid", "exit_bid", "bid_gross_pnl")) for row in rows)
    observed_book_costs_complete = bid_fields_complete and all(all(row.get(key) is not None for key in
        ("entry_ask", "spread_at_entry", "modeled_spread_at_entry", "entry_fill",
         "exit_fill", "spread_cost", "slippage_cost")) for row in rows)
    if bid_fields_complete:
        bid_gross = math.fsum(_finite(row["bid_gross_pnl"], "bid_gross_pnl") for row in rows)
        for row in rows:
            units = _finite(row["units"], "units")
            if units <= 0:
                raise ValueError("BID-baseline trades require positive units")
            expected_bid_gross = units * (_finite(row["exit_bid"], "exit_bid") -
                                           _finite(row["entry_bid"], "entry_bid"))
            if not math.isclose(expected_bid_gross, _finite(row["bid_gross_pnl"], "bid_gross_pnl"),
                                rel_tol=1e-10, abs_tol=1e-8):
                raise ValueError("BID gross P&L does not reconcile observed BID reference quotes")
    if observed_book_costs_complete:
        for row in rows:
            units = _finite(row["units"], "units")
            bid = _finite(row["entry_bid"], "entry_bid")
            ask = _finite(row["entry_ask"], "entry_ask")
            observed_spread = _finite(row["spread_at_entry"], "spread_at_entry")
            modeled_spread = _finite(row["modeled_spread_at_entry"], "modeled_spread_at_entry")
            modeled_ask = bid + modeled_spread
            expected_slippage = units * (_finite(row["entry_fill"], "entry_fill") - modeled_ask
                                          + _finite(row["exit_bid"], "exit_bid") -
                                          _finite(row["exit_fill"], "exit_fill"))
            spread = _finite(row["spread_cost"], "spread_cost")
            slippage = _finite(row["slippage_cost"], "slippage_cost")
            if (ask < bid or observed_spread < 0 or modeled_spread < observed_spread - 1e-12
                    or spread < 0 or slippage < -1e-8 or expected_slippage < -1e-8):
                raise ValueError("Observed book, stressed spread or modeled slippage is inconsistent")
            for actual, expected, label in (
                (observed_spread, ask - bid, "observed spread"),
                (spread, units * modeled_spread, "modeled spread cost"),
                (slippage, expected_slippage, "slippage cost"),
            ):
                if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8):
                    raise ValueError(label + " does not reconcile observed quotes and fills")
            if row.get("gross_pnl") is not None and not math.isclose(
                _finite(row["bid_gross_pnl"], "bid_gross_pnl") - spread - slippage,
                _finite(row["gross_pnl"], "gross_pnl"), rel_tol=1e-10, abs_tol=1e-8
            ):
                raise ValueError("BID gross minus spread and slippage does not reconcile fill P&L")
        observed_spread_cost = math.fsum(_finite(row["units"], "units") *
                                        _finite(row["spread_at_entry"], "spread_at_entry") for row in rows)
        modeled_spread_cost = math.fsum(_finite(row["spread_cost"], "spread_cost") for row in rows)
        slippage_cost = math.fsum(_finite(row["slippage_cost"], "slippage_cost") for row in rows)
    baseline_gross = bid_gross if bid_fields_complete else mid_gross
    baseline = "bid" if bid_fields_complete else ("mid" if mid_gross is not None else "mixed_or_unavailable")
    adverse = []
    peak_drawdowns = []
    breaches = 0
    for row, net in zip(rows, all_net):
        breached = bool(row.get("risk_breach", False))
        if "entry_equity" in row:
            equity = _finite(row["entry_equity"], "entry_equity")
            if equity <= 0:
                raise ValueError("entry_equity must be positive")
            mae = _finite(row.get("max_adverse_excursion", max(0, -net)), "max_adverse_excursion")
            drawdown = _finite(row.get("max_drawdown", mae), "max_drawdown")
            if mae < 0 or drawdown < 0:
                raise ValueError("Excursions and drawdowns cannot be negative")
            adverse.append(max(0, -net, mae) / equity)
            peak_drawdowns.append(drawdown / equity)
            breached = breached or adverse[-1] > .01 + 1e-12 or peak_drawdowns[-1] > .01 + 1e-12
        breaches += breached
    return {
        "closed_trades": len(rows), "eligible_trades": count,
        "terminal_liquidations": len(rows) - count,
        "wins": len(winners), "losses": len(losers),
        "breakeven": count - len(winners) - len(losers),
        "win_rate": win_rate, "loss_rate": loss_rate,
        "win_rate_wilson_95_independence_assumption": wilson_interval(len(winners), count),
        "average_net_winner": average_win, "average_absolute_net_loser": average_loss,
        "net_payoff_ratio": average_win / average_loss if average_loss else None,
        "natural_net_profit": math.fsum(natural_net), "net_profit": math.fsum(all_net),
        "mean_net_pnl_per_natural_trade": expectancy,
        "decomposed_mean_net_pnl": decomposed,
        "decomposition_error": expectancy - decomposed if count else None,
        "natural_net_profit_factor": winner_sum / loss_sum if loss_sum else ("infinity" if winner_sum else None),
        "gross_mid_profit": mid_gross, "gross_bid_profit": bid_gross,
        "price_baseline": baseline, "source_baseline_gross_profit": baseline_gross,
        "gross_after_price_friction_before_fees": fill_gross,
        "spread_slippage_friction": baseline_gross - fill_gross if baseline_gross is not None and fill_gross is not None else None,
        "observed_entry_spread_cost": observed_spread_cost,
        "modeled_entry_spread_cost": modeled_spread_cost,
        "modeled_slippage_cost": slippage_cost,
        "explicit_commission_and_carry": explicit_fees,
        "max_trade_adverse_equity_fraction": max(adverse, default=None),
        "max_trade_peak_drawdown_equity_fraction": max(peak_drawdowns, default=None),
        "risk_breaches": breaches,
        "risk_measurements_complete": all(all(key in row for key in
            ("entry_equity", "max_adverse_excursion", "max_drawdown")) for row in rows),
        "explicit_fee_fields_complete": fee_fields_complete,
        "observed_book_costs_complete": observed_book_costs_complete,
    }


def daily_realized_returns(
    trades: Iterable[Any], initial_equity: float,
    start: datetime | date | str, end: datetime | date | str,
) -> list[dict[str, Any]]:
    """Calendar-day realized returns, including inactive days and terminal exits.

    ``end`` is exclusive. Bounds must be UTC midnight. Each exit must lie in
    the requested interval; silently dropping exits would distort evidence.
    This series does not measure unrealized or intraday marked equity risk.
    """
    equity = _finite(initial_equity, "initial_equity")
    if equity <= 0:
        raise ValueError("initial_equity must be positive")
    first, last = _bound(start), _bound(end)
    if first >= last or any(value.time().isoformat() != "00:00:00" for value in (first, last)):
        raise ValueError("Daily bounds must be ordered UTC midnight timestamps")
    pnl_by_day: dict[date, list[float]] = {}
    for supplied in trades:
        row = _row(supplied)
        exited = _utc(row["exit_time"])
        if not first <= exited < last:
            raise ValueError("Trade exit lies outside the specified final interval")
        pnl_by_day.setdefault(exited.date(), []).append(_finite(row["net_pnl"], "net_pnl"))
    result = []
    day = first.date()
    while day < last.date():
        pnl = math.fsum(pnl_by_day.get(day, []))
        daily_return = pnl / equity
        equity += pnl
        if equity <= 0:
            raise ValueError("Realized equity exhausted; return series is not defined")
        result.append({"date": day.isoformat(), "realized_net_pnl": pnl,
                       "realized_equity": equity, "return": daily_return})
        day += timedelta(days=1)
    return result


def moving_block_bootstrap_mean(
    values: Sequence[float], block_size: int = 7, replications: int = 10_000,
    seed: int = BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Circular moving-block percentile intervals for the mean daily return.

    Seven *calendar* days retain weekly dependence and inactive days. Bounds
    are not p-values or a guarantee of future profit. Use the declared block
    size; choosing it after examining bounds is additional selection.
    """
    data = np.asarray([_finite(value, "daily return") for value in values], dtype=np.float64)
    for number, name in ((block_size, "block_size"), (replications, "replications"), (seed, "seed")):
        if not isinstance(number, int) or isinstance(number, bool) or number < (0 if name == "seed" else 1):
            raise ValueError(f"{name} must be an integer in its supported range")
    if data.size < 2 * block_size:
        raise ValueError("At least two complete blocks of daily observations are required")
    if replications < 1000:
        raise ValueError("At least 1000 bootstrap replications are required")
    rng = np.random.default_rng(seed)
    blocks = math.ceil(data.size / block_size)
    offsets = np.arange(block_size)
    means = np.empty(replications, dtype=np.float64)
    # Bound temporary memory for a multi-year series and many replications.
    for first in range(0, replications, 256):
        size = min(256, replications - first)
        starts = rng.integers(0, data.size, size=(size, blocks))
        indices = ((starts[:, :, None] + offsets) % data.size).reshape(size, -1)[:, :data.size]
        means[first:first + size] = data[indices].mean(axis=1)
    lower_two, upper_two = (float(value) for value in np.quantile(means, [.025, .975]))
    lower_one = float(np.quantile(means, .05))
    return {"method": "circular moving-block percentile bootstrap of calendar-day realized returns",
            "daily_observations": int(data.size), "block_size_calendar_days": block_size,
            "approximate_observed_blocks": float(data.size / block_size),
            "replications": replications, "seed": seed, "mean_daily_return": float(data.mean()),
            "mean_daily_return_ci_95_two_sided": [lower_two, upper_two],
            "mean_daily_return_lower_95_one_sided": lower_one,
            "bootstrap_fraction_mean_nonpositive": float(np.mean(means <= 0)),
            "positive_mean_confirmed_one_sided_95": bool(lower_one > 0),
            "short_series_warning": bool(data.size / block_size < 20)}


def acceptance_assessment(
    summary: Mapping[str, Any], bootstrap: Mapping[str, Any] | None = None,
    minimum_eligible_trades: int = 500,
) -> dict[str, Any]:
    """Keep the stated sample criteria separate from stronger expectancy evidence.

    Apply this to the final interval for the preferred independent 500-trade
    target. To assess a user-requested pooled count, supply a separately named
    pooled summary and disclose the split counts; do not call it independent.
    """
    if not isinstance(minimum_eligible_trades, int) or isinstance(minimum_eligible_trades, bool) or minimum_eligible_trades <= 0:
        raise ValueError("minimum_eligible_trades must be a positive integer")
    reasons = []
    count = _finite(summary.get("eligible_trades", 0), "eligible_trades")
    rate = _finite(summary.get("win_rate", 0), "win_rate")
    net = _finite(summary.get("net_profit", 0), "net_profit")
    breaches = _finite(summary.get("risk_breaches", 1), "risk_breaches")
    if count < 0 or not count.is_integer() or not 0 <= rate <= 1 or breaches < 0 or not breaches.is_integer():
        raise ValueError("Invalid count, win rate or breach count")
    if count < minimum_eligible_trades:
        reasons.append(f"Fewer than {minimum_eligible_trades} natural closes in this declared interval")
    if rate < .5:
        reasons.append("Net winning-trade proportion below 50%")
    if net <= 0:
        reasons.append("Profit after all modeled costs is not positive")
    if summary.get("mean_net_pnl_per_natural_trade") is not None and _finite(
        summary["mean_net_pnl_per_natural_trade"], "natural-trade mean net P&L"
    ) <= 0:
        reasons.append("Mean net P&L of naturally closed trades is not positive")
    if breaches:
        reasons.append("Observed 1% per-trade risk or drawdown violation")
    if summary.get("risk_measurements_complete") is False:
        reasons.append("Some trades lack entry-equity risk measurements")
    for name in ("max_trade_adverse_equity_fraction", "max_trade_peak_drawdown_equity_fraction"):
        value = summary.get(name)
        if value is None:
            reasons.append(name + " was not measured")
        elif _finite(value, name) > .01 + 1e-12:
            reasons.append(name + " exceeds 1%")
    confirmed = bool(bootstrap is not None and
                     _finite(bootstrap["mean_daily_return_lower_95_one_sided"], "bootstrap lower bound") > 0)
    return {"sample_criteria_passed": not reasons, "sample_gate_reasons": reasons,
            "minimum_eligible_trades_assessed": minimum_eligible_trades,
            "dependence_aware_positive_expectancy_evidence": confirmed,
            "strong_positive_expectancy_evidence": not reasons and confirmed,
            "evidence_note": ("Positive after-cost sample and positive dependence-aware lower confidence bound"
                              if not reasons and confirmed else
                              "Report sample results and expectancy uncertainty separately; no future-profit guarantee")}
