"""Research-only one-contract, bidirectional futures execution simulator.

Source LAST_TRADE OHLC is a midpoint *proxy*, never authenticated BID/ASK.
Longs buy above and sell below this proxy; shorts sell below and buy above it.
The cash ledger reserves collateral, releases it on exit and adds signed PnL;
it never pretends that a derivative short sale credits owned-currency principal.

The initial-equity 0.8% notional reserve is a numeric research constraint, NOT
a futures loss guarantee. Short prices can rise without bound; genuine futures
prices can also become negative. Gap losses are never clipped or floored. No
production activation is authorized by this module or its observed statistics.
"""

from __future__ import annotations

import math
from dataclasses import asdict
from typing import Any

import numpy as np

from trading_agent.risk import CostModel
from .futures_statistics import summarize_trades


DEFAULT_FUTURES_COSTS = CostModel(pip_size=.25, spread_pips=2, slippage_pips=1)


def _numeric(values, name, n=None):
    array = np.asarray(values, dtype=np.float64)
    if array.ndim != 1 or (n is not None and len(array) != n):
        raise ValueError(f"{name} must be a one-dimensional matching array")
    return array


def _boolean(values, name, n, default=False):
    if values is None:
        return np.full(n, default, dtype=bool)
    array = _numeric(values, name, n)
    if np.any(~np.isfinite(array)) or np.any((array != 0) & (array != 1)):
        raise ValueError(f"{name} must contain boolean values")
    return array.astype(bool)


def run_futures_backtest(
    timestamps, opens, highs, lows, closes, direction_signals,
    stop_distances, target_distances, *, contract_multiplier: float,
    initial_equity: float, costs: CostModel = DEFAULT_FUTURES_COSTS,
    flat_fee_per_contract_per_side: float | None = None,
    max_holding_bars: int = 12, max_holding_days: int = 5,
    exit_signals=None, daily_exit=None, entry_allowed=None,
    max_signal_age_seconds: int = 300, start_index: int = 0,
    end_index: int | None = None, include_trades: bool = True,
    include_equity_curve: bool = False,
) -> dict[str, Any]:
    """One genuine-contract lot, causal next-open signals, flat sample splits.

    Directions, stop/target distances and exit signals use completed index
    ``i-1`` at execution bar ``i``. ``daily_exit`` and ``entry_allowed`` index
    the current execution bar (calendar information known at that quote).
    A daily-exit bar or prior completed exit signal also prohibits new entry.
    Opening gaps beat discretionary exits; an ambiguous stop/target bar exits
    at the stop. Prices are kept exactly as supplied, including negative prices
    in hypothetical integrity fixtures. Costs are applied without a price floor.

    Flat fees are USD per contract per side and replace the bps/minimum profile
    when supplied. Otherwise fees use absolute fill notional times bps, with the
    declared minimum on each side. ``units`` stays positive (multiplier times
    quantity), and ``direction`` supplies the PnL sign.
    """
    raw_times = _numeric(timestamps, "timestamps")
    n = len(raw_times)
    if (np.any(~np.isfinite(raw_times)) or np.any(raw_times != np.floor(raw_times))
            or np.any(np.abs(raw_times) > 2**53 - 1)):
        raise ValueError("timestamps must be exact finite integer epoch seconds")
    times = raw_times.astype(np.int64)
    if n > 1 and np.any(np.diff(times) <= 0):
        raise ValueError("timestamps must increase strictly")
    op, hi, lo, cl = tuple(_numeric(value, label, n) for value, label in (
        (opens, "opens"), (highs, "highs"), (lows, "lows"), (closes, "closes")))
    if any(np.any(~np.isfinite(a)) for a in (op, hi, lo, cl)):
        raise ValueError("OHLC prices must be finite")
    if np.any(lo > np.minimum(op, cl)) or np.any(hi < np.maximum(op, cl)) or np.any(lo > hi):
        raise ValueError("OHLC prices are inconsistent")
    signals = _numeric(direction_signals, "direction signals", n)
    if np.any(~np.isfinite(signals)) or np.any(~np.isin(signals, [-1, 0, 1])):
        raise ValueError("directions must be -1, 0 or +1")
    stops = _numeric(np.full(n, stop_distances) if np.isscalar(stop_distances) else stop_distances, "stop distances", n)
    targets = _numeric(np.full(n, target_distances) if np.isscalar(target_distances) else target_distances, "target distances", n)
    exits = _boolean(exit_signals, "exit signals", n)
    daily = _boolean(daily_exit, "daily exits", n)
    allowed = _boolean(entry_allowed, "entry allowed", n, default=True)
    for value, label in ((contract_multiplier, "contract multiplier"), (initial_equity, "initial equity")):
        if isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise ValueError(label + " must be finite and positive")
    for value, label, maximum in ((max_holding_bars, "holding bars", 12),
                                  (max_holding_days, "holding days", 5),
                                  (max_signal_age_seconds, "signal age", None)):
        if (not isinstance(value, int) or isinstance(value, bool) or value <= 0
                or (maximum is not None and value > maximum)):
            raise ValueError(label + " exceeds the supported positive integer range")
    if flat_fee_per_contract_per_side is not None and (
        isinstance(flat_fee_per_contract_per_side, bool)
        or not math.isfinite(flat_fee_per_contract_per_side) or flat_fee_per_contract_per_side < 0
    ):
        raise ValueError("flat fee must be finite and nonnegative")
    if costs.carry_per_1000_per_day != 0:
        raise ValueError("this futures research model has no ongoing carry component")
    if not math.isfinite(costs.side_price_cost):
        raise ValueError("modeled side price cost must be finite")
    end_index = n if end_index is None else end_index
    if (not isinstance(start_index, int) or isinstance(start_index, bool)
            or not isinstance(end_index, int) or isinstance(end_index, bool)
            or not 0 <= start_index <= end_index <= n):
        raise ValueError("sample indices must form a valid half-open interval")

    side_cost = costs.side_price_cost
    quantity = 1
    units = float(contract_multiplier)
    allocation_cap = initial_equity * .008
    cash = float(initial_equity)
    position = None
    trades = []
    curve = []
    account_peak = cash
    account_drawdown = 0.0
    rejected = stale_rejected = halted_rejected = 0
    halted = False

    def fee(fill):
        return (float(flat_fee_per_contract_per_side) * quantity
                if flat_fee_per_contract_per_side is not None
                else costs.commission(abs(fill) * units))

    def mark(current, quote):
        nonlocal halted
        fill = quote - current["direction"] * side_cost
        gross = current["direction"] * units * (fill - current["entry_fill"])
        pnl = gross - current["entry_commission"] - fee(fill)
        current["max_adverse_excursion"] = max(current["max_adverse_excursion"], -pnl, 0.0)
        current["peak_pnl"] = max(current["peak_pnl"], pnl)
        current["max_drawdown"] = max(current["max_drawdown"], current["peak_pnl"] - pnl)
        if max(-pnl, current["max_adverse_excursion"], current["max_drawdown"]) > current["entry_equity"] * .01 + 1e-8:
            halted = True
        return pnl

    def close(current, i, quote, reason):
        nonlocal cash
        mark(current, quote)
        fill = quote - current["direction"] * side_cost
        exit_fee = fee(fill)
        gross = current["direction"] * units * (fill - current["entry_fill"])
        net = gross - current["entry_commission"] - exit_fee
        cash += current["notional_reserve"] + gross - exit_fee
        source_gross = current["direction"] * units * (quote - current["entry_quote"])
        risk_limit = current["entry_equity"] * .01
        breach = max(-net, current["max_adverse_excursion"], current["max_drawdown"]) > risk_limit + 1e-8
        trades.append({
            "entry_index": current["entry_index"], "exit_index": i,
            "entry_time": current["entry_time"], "exit_time": int(times[i]),
            "direction": current["direction"], "side": "long" if current["direction"] == 1 else "short",
            "contracts": quantity, "quantity_lots": quantity, "trading_lots": quantity,
            "contract_multiplier": units, "units": units,
            "entry_quote": current["entry_quote"], "exit_quote": float(quote),
            "entry_mid": current["entry_quote"], "exit_mid": float(quote),
            "entry_fill": current["entry_fill"], "exit_fill": float(fill),
            "entry_commission": current["entry_commission"], "exit_commission": exit_fee,
            "carry": 0.0, "total_fees": current["entry_commission"] + exit_fee,
            "gross_pnl": gross, "net_pnl": net,
            "source_last_trade_gross_pnl": source_gross,
            "spread_cost": units * costs.spread_pips * costs.pip_size,
            "slippage_cost": units * 2 * costs.slippage_pips * costs.pip_size,
            "modeled_spread_slippage_cost": source_gross - gross,
            "price_baseline": "source_last_trade_as_mid_proxy",
            "mid_quotes_observed": False, "quote_model": "last_trade_as_mid_proxy_fixed_spread",
            "entry_equity": current["entry_equity"], "risk_limit": risk_limit,
            "max_adverse_excursion": current["max_adverse_excursion"],
            "max_drawdown": current["max_drawdown"], "risk_breach": breach,
            "notional_reserve": current["notional_reserve"],
            "cash_after_entry": current["cash_after_entry"], "cash_after_exit": cash,
            "stop_price": current["stop_price"], "target_price": current["target_price"],
            "reason": reason, "derivative_loss_bound_established": False,
            "excursion_model": "conservative_OHLC_pre_exit_upper_envelope",
        })
        if not math.isclose(cash - current["entry_equity"], net, rel_tol=1e-10, abs_tol=1e-7):
            raise RuntimeError("collateral release and signed cash PnL do not reconcile")

    for i in range(start_index, end_index):
        existed = position is not None
        discretionary_exit = daily[i] or (i > 0 and exits[i - 1])
        eligible = not existed and i > 0 and signals[i - 1] and allowed[i] and not discretionary_exit
        if eligible and halted:
            halted_rejected += 1
        if eligible and not halted:
            if times[i] - times[i - 1] > max_signal_age_seconds:
                stale_rejected += 1
            else:
                direction = int(signals[i - 1])
                stop_distance, target_distance = stops[i - 1], targets[i - 1]
                entry_fill = float(op[i] + direction * side_cost)
                # A short's discounted sale proxy must not understate the
                # contract reserve at the notional boundary. Reserve the larger
                # absolute source reference or fill, never short-sale proceeds.
                reserve = max(abs(float(op[i])), abs(entry_fill)) * units
                entry_fee = fee(entry_fill)
                if (not math.isfinite(stop_distance) or stop_distance <= 0
                        or not math.isfinite(target_distance) or target_distance <= 0
                        or not math.isfinite(reserve) or reserve > min(allocation_cap, cash * .008) + 1e-8
                        or cash <= 0 or reserve + entry_fee > cash):
                    rejected += 1
                else:
                    entry_equity = cash
                    cash -= reserve + entry_fee
                    position = {
                        "entry_index": i, "entry_time": int(times[i]), "direction": direction,
                        "entry_quote": float(op[i]), "entry_fill": entry_fill,
                        "entry_commission": entry_fee, "entry_equity": entry_equity,
                        "notional_reserve": reserve, "cash_after_entry": cash,
                        "stop_price": float(op[i] - direction * stop_distance),
                        "target_price": float(op[i] + direction * target_distance),
                        "max_adverse_excursion": 0.0, "peak_pnl": 0.0, "max_drawdown": 0.0,
                    }
                    mark(position, float(op[i]))
        if position is not None:
            p = position
            direction = p["direction"]
            mark(p, float(op[i]))
            reason = None
            exit_quote = 0.0
            if direction * (op[i] - p["stop_price"]) <= 0:
                reason, exit_quote = "stop_gap", float(op[i])
            elif direction * (op[i] - p["target_price"]) >= 0:
                reason, exit_quote = "target_gap", float(op[i])
            elif times[i] - p["entry_time"] >= max_holding_days * 86400:
                reason, exit_quote = "expiry", float(op[i])
            elif i - p["entry_index"] >= max_holding_bars:
                reason, exit_quote = "holding_bars", float(op[i])
            elif existed and discretionary_exit:
                reason, exit_quote = "daily_exit" if daily[i] else "signal_exit", float(op[i])
            elif (lo[i] <= p["stop_price"] if direction == 1 else hi[i] >= p["stop_price"]):
                # Unknown OHLC ordering can approach the target before the
                # stop. The target is a conservative supremum of still-held
                # favorable prices, not a claim that the target filled first.
                favorable = min(hi[i], p["target_price"]) if direction == 1 else max(lo[i], p["target_price"])
                mark(p, float(favorable))
                reason, exit_quote = "stop", p["stop_price"]
            elif (hi[i] >= p["target_price"] if direction == 1 else lo[i] <= p["target_price"]):
                # The quote can approach the target, retrace adversely, then
                # touch it. Cap pre-exit favorable exposure at target rather
                # than using the later bar extreme beyond an executable exit.
                mark(p, p["target_price"])
                mark(p, float(lo[i] if direction == 1 else hi[i]))
                reason, exit_quote = "target", p["target_price"]
            else:
                mark(p, float(hi[i] if direction == 1 else lo[i]))
                mark(p, float(lo[i] if direction == 1 else hi[i]))
                mark(p, float(cl[i]))
            if reason is not None:
                close(p, i, exit_quote, reason)
                position = None
        if position is None:
            marked = cash
        else:
            # Read liquidation without changing the already-recorded OHLC path.
            fill = cl[i] - position["direction"] * side_cost
            gross = position["direction"] * units * (fill - position["entry_fill"])
            marked = cash + position["notional_reserve"] + gross - fee(fill)
        account_peak = max(account_peak, marked)
        account_drawdown = max(account_drawdown, (account_peak - marked) / account_peak)
        if include_equity_curve:
            curve.append({"time": int(times[i]), "equity": float(marked)})
    if position is not None and end_index > start_index:
        close(position, end_index - 1, float(cl[end_index - 1]), "sample_end")
        if include_equity_curve:
            curve[-1]["equity"] = cash

    summary = summarize_trades(trades)
    if not math.isclose(cash - initial_equity, summary["net_profit"], rel_tol=1e-10, abs_tol=1e-6):
        raise RuntimeError("aggregate futures trade PnL does not reconcile cash ledger")
    summary.update({
        "initial_equity": float(initial_equity), "ending_equity": cash,
        "net_return": summary["net_profit"] / initial_equity,
        "natural_closed_trades": summary["eligible_trades"],
        "natural_net_profit_per_trade": summary["mean_net_pnl_per_natural_trade"],
        "profit_factor": summary["natural_net_profit_factor"],
        "max_account_drawdown_close_marks": account_drawdown,
        "rejected_entries": rejected, "stale_signal_entries_rejected": stale_rejected,
        "contract_multiplier": units, "contracts_per_trade": 1,
        "notional_reserve_fraction_of_initial_equity": .008,
        "notional_reserve_cap_basis": "0.8% of min(initial equity, current entry equity)",
        "max_signal_age_seconds": max_signal_age_seconds,
        "max_holding_bars": max_holding_bars, "max_holding_days": max_holding_days,
        "cost_model": asdict(costs), "flat_fee_per_contract_per_side": flat_fee_per_contract_per_side,
        "commission_profile": "flat_per_contract_per_side" if flat_fee_per_contract_per_side is not None else "bps_with_minimum_per_side",
        "quote_model": "last_trade_as_mid_proxy_fixed_spread",
        "mid_quotes_observed": False, "executable_bid_ask_verified": False,
        "risk_model": "collateral_reserve_and_directional_futures_pnl",
        "derivative_loss_bound_established": False,
        "derivative_variation_margin_bound_established": False,
        "paper_activation_authorized": False,
        "bars": end_index - start_index,
        "daily_flat_dependent_on_caller_calendar_masks": True,
        "risk_halt_triggered": halted, "halted_entries_rejected": halted_rejected,
        "excursion_model": "conservative_OHLC_pre_exit_upper_envelope",
    })
    return {"summary": summary, "trades": trades if include_trades else [], "equity_curve": curve}
