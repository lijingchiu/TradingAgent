"""Fast research-only fully funded long FX simulation.

Signals and stop/target distances are arrays for completed bars. At execution
bar ``i`` only index ``i - 1`` may generate an entry or a discretionary exit.
An entry-allowed session mask instead applies to execution bar ``i``. Account
cash is debited for the complete purchase and entry commission, then credited
with actual modeled sale proceeds less exit commission. There is no leverage,
negative currency ownership, ongoing financing, or clipping of realized loss.

When available, Numba accelerates the identical numeric loop. Validation always
runs before the loop; the JIT path does not provide an alternative risk policy.
The production execution module remains the reference used by the tests.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from trading_agent.risk import CostModel, DEFAULT_COSTS

try:
    from numba import njit
except ImportError:
    njit = None


REASONS = {
    1: "stop_gap", 2: "target_gap", 3: "expiry", 4: "stop",
    5: "target", 6: "holding_bars", 7: "signal_exit", 8: "sample_end",
}
TRADE_COLUMNS = (
    "entry_index", "exit_index", "entry_time", "exit_time", "units",
    "entry_mid", "entry_fill", "exit_mid", "exit_fill", "entry_commission",
    "exit_commission", "gross_pnl", "net_pnl", "max_adverse_excursion",
    "max_drawdown", "entry_equity", "risk_limit", "worst_case_loss",
    "reason_code", "entry_notional", "cash_after_entry", "cash_after_exit",
    "stop_price", "target_price", "risk_breach",
)


def _observe(mid, units, entry_fill, entry_fee, side_cost, fee_rate,
             minimum_fee, mae, peak, drawdown):
    exit_fill = max(0.0, mid - side_cost)
    pnl = units * (exit_fill - entry_fill) - entry_fee - max(minimum_fee, units * exit_fill * fee_rate)
    mae = max(mae, -pnl, 0.0)
    peak = max(peak, pnl)
    drawdown = max(drawdown, peak - pnl)
    return mae, peak, drawdown


if njit is not None:
    _observe = njit(cache=True)(_observe)


def _simulate(times, opens, highs, lows, closes, entries, stop_distances,
              target_distances, exits, allowed, first, last, initial_equity,
              entry_costs, exit_cost, fee_rate, minimum_fee, max_days, max_bars,
              max_signal_age, unit_step, save_curve):
    rows = []
    curve = np.empty(last - first if save_curve else 0, dtype=np.float64)
    cash = initial_equity
    account_peak = initial_equity
    account_drawdown = 0.0
    rejected = 0
    stale_rejected = 0
    active = False
    entry_index = -1
    entry_time = 0
    units = 0
    entry_mid = 0.0
    entry_fill = 0.0
    entry_fee = 0.0
    entry_equity = 0.0
    entry_notional = 0.0
    cash_after_entry = 0.0
    risk_limit = 0.0
    worst_case = 0.0
    stop = 0.0
    target = 0.0
    mae = 0.0
    trade_peak = 0.0
    trade_drawdown = 0.0
    for i in range(first, last):
        existed_at_open = active
        stale_signal = i > 0 and times[i] - times[i - 1] > max_signal_age
        if not active and i > 0 and entries[i - 1] and allowed[i] and stale_signal:
            stale_rejected += 1
        if not active and i > 0 and entries[i - 1] and allowed[i] and not stale_signal:
            distance = stop_distances[i - 1]
            target_distance = target_distances[i - 1]
            if (not math.isfinite(distance) or distance <= 0 or distance >= opens[i]
                    or not math.isfinite(target_distance) or target_distance <= 0
                    or not math.isfinite(opens[i] + target_distance)):
                rejected += 1
            else:
                proposed_fill = opens[i] + entry_costs[i]
                budget = cash * 0.01
                maximum_notional = min(cash * 0.008, budget - 2 * minimum_fee,
                                       (budget - minimum_fee) / (1 + fee_rate))
                proposed_units = int(math.floor(maximum_notional / (proposed_fill * unit_step))) * unit_step
                proposed_notional = proposed_units * proposed_fill
                proposed_fee = max(minimum_fee, proposed_notional * fee_rate)
                proposed_worst = proposed_notional + proposed_fee + minimum_fee
                if (proposed_units < 1 or proposed_worst > budget + 1e-9
                        or proposed_notional + proposed_fee > cash):
                    rejected += 1
                else:
                    active = True
                    entry_index = i
                    entry_time = times[i]
                    units = proposed_units
                    entry_mid = opens[i]
                    entry_fill = proposed_fill
                    entry_fee = proposed_fee
                    entry_equity = cash
                    entry_notional = proposed_notional
                    risk_limit = budget
                    worst_case = proposed_worst
                    stop = entry_mid - distance
                    target = entry_mid + target_distance
                    cash -= entry_notional + entry_fee
                    cash_after_entry = cash
                    mae, trade_peak, trade_drawdown = _observe(
                        entry_mid, units, entry_fill, entry_fee, exit_cost,
                        fee_rate, minimum_fee, 0.0, 0.0, 0.0)

        if active:
            mae, trade_peak, trade_drawdown = _observe(
                opens[i], units, entry_fill, entry_fee, exit_cost, fee_rate,
                minimum_fee, mae, trade_peak, trade_drawdown)
            reason = 0
            exit_mid = 0.0
            if opens[i] <= stop:
                reason, exit_mid = 1, opens[i]
            elif opens[i] >= target:
                reason, exit_mid = 2, opens[i]
            elif times[i] - entry_time >= max_days * 86400:
                reason, exit_mid = 3, opens[i]
            elif max_bars > 0 and i - entry_index >= max_bars:
                reason, exit_mid = 6, opens[i]
            elif existed_at_open and i > 0 and exits[i - 1]:
                reason, exit_mid = 7, opens[i]
            elif lows[i] <= stop:
                reason, exit_mid = 4, stop
            elif highs[i] >= target:
                mae, trade_peak, trade_drawdown = _observe(
                    lows[i], units, entry_fill, entry_fee, exit_cost, fee_rate,
                    minimum_fee, mae, trade_peak, trade_drawdown)
                reason, exit_mid = 5, target
            else:
                mae, trade_peak, trade_drawdown = _observe(
                    highs[i], units, entry_fill, entry_fee, exit_cost, fee_rate,
                    minimum_fee, mae, trade_peak, trade_drawdown)
                mae, trade_peak, trade_drawdown = _observe(
                    lows[i], units, entry_fill, entry_fee, exit_cost, fee_rate,
                    minimum_fee, mae, trade_peak, trade_drawdown)
                mae, trade_peak, trade_drawdown = _observe(
                    closes[i], units, entry_fill, entry_fee, exit_cost, fee_rate,
                    minimum_fee, mae, trade_peak, trade_drawdown)

            if reason:
                mae, trade_peak, trade_drawdown = _observe(
                    exit_mid, units, entry_fill, entry_fee, exit_cost, fee_rate,
                    minimum_fee, mae, trade_peak, trade_drawdown)
                exit_fill = max(0.0, exit_mid - exit_cost)
                exit_fee = max(minimum_fee, units * exit_fill * fee_rate)
                gross = units * (exit_fill - entry_fill)
                net = gross - entry_fee - exit_fee
                cash += units * exit_fill - exit_fee
                breach = 1.0 if max(-net, mae) > risk_limit + 1e-9 else 0.0
                rows.append((float(entry_index), float(i), float(entry_time), float(times[i]),
                             float(units), entry_mid, entry_fill, exit_mid, exit_fill,
                             entry_fee, exit_fee, gross, net, mae, trade_drawdown,
                             entry_equity, risk_limit, worst_case, float(reason), entry_notional,
                             cash_after_entry, cash, stop, target, breach))
                active = False

        if active:
            marked_fill = max(0.0, closes[i] - exit_cost)
            marked = cash + units * marked_fill - max(minimum_fee, units * marked_fill * fee_rate)
        else:
            marked = cash
        account_peak = max(account_peak, marked)
        account_drawdown = max(account_drawdown, (account_peak - marked) / account_peak)
        if save_curve:
            curve[i - first] = marked

    if active and last > first:
        i = last - 1
        exit_mid = closes[i]
        mae, trade_peak, trade_drawdown = _observe(
            exit_mid, units, entry_fill, entry_fee, exit_cost, fee_rate,
            minimum_fee, mae, trade_peak, trade_drawdown)
        exit_fill = max(0.0, exit_mid - exit_cost)
        exit_fee = max(minimum_fee, units * exit_fill * fee_rate)
        gross = units * (exit_fill - entry_fill)
        net = gross - entry_fee - exit_fee
        cash += units * exit_fill - exit_fee
        breach = 1.0 if max(-net, mae) > risk_limit + 1e-9 else 0.0
        rows.append((float(entry_index), float(i), float(entry_time), float(times[i]),
                     float(units), entry_mid, entry_fill, exit_mid, exit_fill,
                     entry_fee, exit_fee, gross, net, mae, trade_drawdown,
                     entry_equity, risk_limit, worst_case, 8.0, entry_notional,
                     cash_after_entry, cash, stop, target, breach))
        if save_curve:
            curve[-1] = cash
    return rows, curve, cash, account_drawdown, rejected, stale_rejected


_simulate_python = _simulate
if njit is not None:
    _simulate = njit(cache=True)(_simulate)


def _array(values: Any, name: str, length: int | None = None) -> np.ndarray:
    result = np.ascontiguousarray(values, dtype=np.float64)
    if result.ndim != 1 or (length is not None and len(result) != length):
        raise ValueError(f"{name} must be a one-dimensional matching array")
    return result


def _boolean(values: Any, name: str, length: int) -> np.ndarray:
    result = np.asarray(values)
    if result.ndim != 1 or len(result) != length:
        raise ValueError(f"{name} must be a one-dimensional matching array")
    if result.dtype != np.bool_:
        numeric = np.asarray(result, dtype=np.float64)
        if not np.all(np.isfinite(numeric)) or not np.all((numeric == 0) | (numeric == 1)):
            raise ValueError(f"{name} must contain boolean values")
    return np.ascontiguousarray(result, dtype=np.bool_)


def run_intraday_backtest(
    timestamps, opens, highs, lows, closes, entry_signals, stop_distances,
    target_distances, *, exit_signals=None, entry_allowed=None,
    max_holding_bars: int | None = None, max_holding_days: int = 5,
    initial_equity: float = 100_000.0, costs: CostModel = DEFAULT_COSTS,
    start_index: int = 0, end_index: int | None = None,
    include_trades: bool = True, include_equity_curve: bool = False,
    use_jit: bool = True, quote_kind: str = "mid",
    max_signal_age_seconds: int | None = None,
    ask_opens=None, observed_spread_multiplier: float = 1.0,
    book_source: str | None = None,
    unit_step: int = 1,
) -> dict[str, Any]:
    """Simulate causal arrays with a flat start and explicit sample-end exit.

    Epoch timestamps must be increasing integer seconds. ``quote_kind='mid'``
    interprets input OHLC as mid prices. For BID candles, use ``'bid'``: input
    OHLC is shifted by half the *configured assumed* spread before fills. Thus
    buy fills are raw BID + full spread + slippage, and sales raw BID - slippage.
    This inferred fixed-spread mid is not an observed mid quote; increasing the
    stress spread recomputes the shift. These are modeled executable prices.
    Signals and distances remain caller-derived from the original arrays;
    absolute distances are additive-shift invariant, percentage features may
    have a small difference. No actual variable spread is inferred or replaced.
    With ``quote_kind='bid', ask_opens=...``, aligned observed ASK opens replace
    the fixed-spread assumption. BID OHLC is kept unchanged: entry is the
    current ASK plus slippage; sale is the observed BID minus slippage. Stops
    and targets are anchored to entry BID, not a varying midpoint translation.
    ASK values must be finite, aligned and no lower than BID opens. Only the
    execution bar's ASK is used at entry; exit uses no future ASK observation.
    ``observed_spread_multiplier>=1`` stresses each actual entry spread; it
    must be declared before interpreting stress outcomes. ``book_source`` is
    caller-supplied provenance, which this numeric engine cannot authenticate.
    ``unit_step`` rounds exposure down to whole numeric lots (default one EUR
    unit). A research contract multiplier of five can use ``unit_step=5`` so
    five pricing units form one simulated lot. This remains a fully paid,
    nonnegative-price numeric model: it does not establish a derivatives
    variation-margin loss bound or authorize futures paper/live activation.
    Warm-up NaNs are allowed in distance arrays, but an entry needing one is
    rejected. Distances may also be positive scalars. Holding bars count the
    elapsed intervals since entry: ``max_holding_bars=1`` exits at next open.
    An explicit exit signal executes at next open after opening-gap stops,
    opening-gap targets, and mandatory expiry. No same-bar re-entry is allowed.
    New entries also require the signal-to-entry timestamp gap to be at most
    ``max_signal_age_seconds``. By default that bound is the modal positive
    input timestamp interval (smallest interval wins a frequency tie). Supply
    ``minutes * 60`` explicitly for native M5/M15 studies. Missing/weekend bars
    cannot carry a stale signal forward into a new position. Existing positions
    still receive their observed gap stop/target/expiry exits.
    """
    raw_times = _array(timestamps, "timestamps")
    n = len(raw_times)
    if (not np.all(np.isfinite(raw_times)) or np.any(raw_times != np.floor(raw_times))
            or np.any(np.abs(raw_times) > 2**53 - 1)):
        raise ValueError("timestamps must be finite, precisely representable integer epoch seconds")
    times = np.ascontiguousarray(raw_times, dtype=np.int64)
    if n > 1 and np.any(times[1:] <= times[:-1]):
        raise ValueError("timestamps must advance strictly")
    signal_age_inferred = max_signal_age_seconds is None
    if max_signal_age_seconds is None:
        if n > 1:
            intervals, counts = np.unique(np.diff(times), return_counts=True)
            max_signal_age_seconds = int(intervals[np.argmax(counts)])
        else:
            # A zero/one-bar input cannot generate a subsequent-bar entry.
            max_signal_age_seconds = 1
    elif (not isinstance(max_signal_age_seconds, int)
          or isinstance(max_signal_age_seconds, bool) or max_signal_age_seconds <= 0):
        raise ValueError("max_signal_age_seconds must be a positive integer")
    price_arrays = tuple(_array(values, name, n) for values, name in (
        (opens, "opens"), (highs, "highs"), (lows, "lows"), (closes, "closes")))
    op, hi, lo, cl = price_arrays
    if any(not np.all(np.isfinite(a)) or np.any(a < 0) for a in price_arrays):
        raise ValueError("OHLC prices must be finite and nonnegative")
    if np.any(lo > np.minimum(op, cl)) or np.any(hi < np.maximum(op, cl)) or np.any(lo > hi):
        raise ValueError("OHLC prices are inconsistent")
    if quote_kind not in ("mid", "bid"):
        raise ValueError("quote kind must be 'mid' or 'bid'")
    if (isinstance(observed_spread_multiplier, bool)
            or not math.isfinite(observed_spread_multiplier)
            or observed_spread_multiplier < 1):
        raise ValueError("observed spread multiplier must be finite and at least one")
    observed_book = ask_opens is not None
    if observed_book and quote_kind != "bid":
        raise ValueError("observed ASK opens require BID input candles")
    if not observed_book and observed_spread_multiplier != 1:
        raise ValueError("observed spread stress requires observed ASK opens")
    if book_source is not None and (not isinstance(book_source, str) or not book_source.strip()):
        raise ValueError("book source must be a nonempty provenance string")
    if observed_book:
        asks = _array(ask_opens, "ASK opens", n)
        if not np.all(np.isfinite(asks)) or np.any(asks < op):
            raise ValueError("observed ASK opens must be finite and at least their aligned BID opens")
        observed_spreads = asks - op
        modeled_spreads = observed_spreads * observed_spread_multiplier
        exit_cost = costs.slippage_pips * costs.pip_size
        entry_costs = np.ascontiguousarray(modeled_spreads + exit_cost)
        mid_offset = 0.0
    else:
        mid_offset = costs.spread_pips / 2 * costs.pip_size if quote_kind == "bid" else 0.0
        if mid_offset:
            op, hi, lo, cl = tuple(array + mid_offset for array in price_arrays)
        exit_cost = costs.side_price_cost
        entry_costs = np.full(n, costs.side_price_cost, dtype=np.float64)
    if (not math.isfinite(exit_cost) or not np.all(np.isfinite(entry_costs))
            or any(not np.all(np.isfinite(array)) for array in (op, hi, lo, cl))
            or np.any(~np.isfinite(op + entry_costs))):
        raise ValueError("modeled costs and fill prices must remain finite")
    entries = _boolean(entry_signals, "entry signals", n)
    exits = np.zeros(n, dtype=np.bool_) if exit_signals is None else _boolean(exit_signals, "exit signals", n)
    allowed = np.ones(n, dtype=np.bool_) if entry_allowed is None else _boolean(entry_allowed, "entry allowed", n)
    stops = _array(np.full(n, stop_distances) if np.isscalar(stop_distances) else stop_distances, "stop distances", n)
    targets = _array(np.full(n, target_distances) if np.isscalar(target_distances) else target_distances, "target distances", n)
    if isinstance(initial_equity, bool) or not math.isfinite(initial_equity) or initial_equity <= 0:
        raise ValueError("initial equity must be positive and finite")
    if not isinstance(unit_step, int) or isinstance(unit_step, bool) or unit_step <= 0:
        raise ValueError("unit step must be a positive integer")
    if (not isinstance(max_holding_days, int) or isinstance(max_holding_days, bool)
            or not 1 <= max_holding_days <= 5):
        raise ValueError("holding days must remain within the 5-day hard limit")
    if max_holding_bars is not None and (not isinstance(max_holding_bars, int)
                                       or isinstance(max_holding_bars, bool) or max_holding_bars <= 0):
        raise ValueError("holding bars must be a positive integer")
    if costs.carry_per_1000_per_day != 0:
        raise ValueError("fully funded research execution requires zero ongoing carry")
    end_index = n if end_index is None else end_index
    if (not isinstance(start_index, int) or isinstance(start_index, bool)
            or not isinstance(end_index, int) or isinstance(end_index, bool)
            or not 0 <= start_index <= end_index <= n):
        raise ValueError("sample indices must define a valid half-open range")
    simulator = _simulate if use_jit else _simulate_python
    raw_rows, curve, ending_equity, max_drawdown, rejected, stale_rejected = simulator(
        times, op, hi, lo, cl, entries, stops, targets, exits, allowed,
        start_index, end_index, float(initial_equity), entry_costs, float(exit_cost),
        float(costs.commission_bps / 10_000), float(costs.minimum_commission),
        max_holding_days, max_holding_bars or 0, max_signal_age_seconds, unit_step, include_equity_curve)
    rows = np.asarray(raw_rows, dtype=np.float64).reshape((-1, len(TRADE_COLUMNS)))
    natural = rows[rows[:, 18] != 8] if len(rows) else rows
    all_pnl = rows[:, 12]
    natural_pnl = natural[:, 12]
    wins = int(np.count_nonzero(natural_pnl > 0))
    losses = int(np.count_nonzero(natural_pnl < 0))
    positive = float(np.sum(np.maximum(all_pnl, 0)))
    negative = float(-np.sum(np.minimum(all_pnl, 0)))
    natural_positive = float(np.sum(np.maximum(natural_pnl, 0)))
    natural_negative = float(-np.sum(np.minimum(natural_pnl, 0)))
    def factor(profit: float, loss: float):
        return profit / loss if loss > 0 else (None if profit == 0 else "infinity")
    net_profit = float(np.sum(all_pnl))
    if observed_book and len(rows):
        entry_indices = rows[:, 0].astype(np.int64)
        observed_spread_cost = float(np.sum(rows[:, 4] * observed_spreads[entry_indices]))
        spread_cost = observed_spread_cost * observed_spread_multiplier
        bid_baseline_gross = float(np.sum(rows[:, 4] * (rows[:, 7] - rows[:, 5])))
        slippage_cost = float(np.sum(rows[:, 4] * (
            rows[:, 6] - rows[:, 5] - modeled_spreads[entry_indices]
            + rows[:, 7] - rows[:, 8])))
    else:
        observed_spread_cost = spread_cost = bid_baseline_gross = slippage_cost = 0.0
    # Summing trade PnL and the cash ledger must agree, including minimum fees.
    if not math.isclose(ending_equity - initial_equity, net_profit, rel_tol=1e-9, abs_tol=1e-6):
        raise RuntimeError("cash ledger does not reconcile with trade PnL")
    if observed_book:
        commission_cost = float(np.sum(rows[:, 9] + rows[:, 10])) if len(rows) else 0.0
        book_net = bid_baseline_gross - spread_cost - slippage_cost - commission_cost
        if not math.isclose(book_net, net_profit, rel_tol=1e-9, abs_tol=1e-6):
            raise RuntimeError("BID gross, observed spread, slippage and commissions do not reconcile")
    summary = {
        "initial_equity": float(initial_equity), "ending_equity": float(ending_equity),
        "net_profit": net_profit, "net_return": net_profit / initial_equity,
        "closed_trades": len(rows), "natural_closed_trades": len(natural),
        "eligible_trades": len(natural), "wins": wins, "losses": losses,
        "breakeven_trades": len(natural) - wins - losses,
        "win_rate": wins / len(natural) if len(natural) else 0.0,
        "net_profit_per_trade": net_profit / len(rows) if len(rows) else 0.0,
        "natural_net_profit": float(np.sum(natural_pnl)),
        "natural_net_profit_per_trade": float(np.mean(natural_pnl)) if len(natural) else 0.0,
        "mean_net_pips_per_trade": float(np.mean(natural_pnl / natural[:, 4] / costs.pip_size)) if len(natural) else 0.0,
        "profit_factor": factor(positive, negative),
        "natural_profit_factor": factor(natural_positive, natural_negative),
        "mean_winning_trade": float(np.mean(natural_pnl[natural_pnl > 0])) if wins else 0.0,
        "mean_losing_trade": float(np.mean(natural_pnl[natural_pnl < 0])) if losses else 0.0,
        "total_commission": float(np.sum(rows[:, 9] + rows[:, 10])) if len(rows) else 0.0,
        "total_carry": 0.0,
        "modeled_spread_slippage_cost": float(np.sum(rows[:, 4] * (rows[:, 6] - rows[:, 5] + rows[:, 7] - rows[:, 8]))) if len(rows) else 0.0,
        "max_account_drawdown_close_marks": float(max_drawdown),
        "max_trade_adverse_equity_fraction": float(np.max(rows[:, 13] / rows[:, 15])) if len(rows) else 0.0,
        "max_trade_peak_drawdown_equity_fraction": float(np.max(rows[:, 14] / rows[:, 15])) if len(rows) else 0.0,
        "max_funded_loss_equity_fraction": float(np.max(rows[:, 17] / rows[:, 15])) if len(rows) else 0.0,
        "risk_breaches": int(np.sum(rows[:, 24])) if len(rows) else 0,
        "terminal_liquidations": int(np.count_nonzero(rows[:, 18] == 8)) if len(rows) else 0,
        "rejected_entries": int(rejected), "bars": end_index - start_index,
        "first_epoch": int(times[start_index]) if start_index < end_index else None,
        "last_epoch": int(times[end_index - 1]) if start_index < end_index else None,
        "engine": "numba" if use_jit and njit is not None else "python",
        "quote_kind": quote_kind,
        "mid_model": "no_midpoint_bid_price_baseline" if observed_book else ("bid_plus_assumed_fixed_half_spread" if quote_kind == "bid" else "input_mid"),
        "quote_model": "observed_bid_ask_opens" if observed_book else "fixed_spread",
        "price_baseline": "bid" if observed_book else "mid",
        "assumed_spread_pips": None if observed_book else float(costs.spread_pips),
        "observed_book_source": (book_source or "caller_supplied_aligned_bid_and_ask_opens") if observed_book else None,
        "observed_spread_multiplier": float(observed_spread_multiplier) if observed_book else None,
        "total_observed_spread_cost": observed_spread_cost if observed_book else None,
        "total_spread_cost": spread_cost if observed_book else None,
        "total_slippage_cost": slippage_cost if observed_book else None,
        "bid_baseline_gross_profit": bid_baseline_gross if observed_book else None,
        "max_signal_age_seconds": max_signal_age_seconds,
        "signal_age_bound_inferred_from_native_interval": signal_age_inferred,
        "stale_signal_entries_rejected": int(stale_rejected),
        "unit_step": unit_step,
        "risk_model": "fully_paid_numeric_nonnegative_price_model",
        "derivative_variation_margin_bound_established": False,
    }
    trades = []
    if include_trades:
        for row in rows:
            trade = dict(zip(TRADE_COLUMNS, map(float, row)))
            for name in ("entry_index", "exit_index", "entry_time", "exit_time", "units"):
                trade[name] = int(trade[name])
            trade["reason"] = REASONS[int(trade.pop("reason_code"))]
            trade["risk_breach"] = bool(trade["risk_breach"])
            trade["trading_lots"] = trade["units"] // unit_step
            trade["carry"] = 0.0
            trade["total_fees"] = trade["entry_commission"] + trade["exit_commission"]
            trade["entry_quote"] = trade["entry_mid"] - mid_offset
            trade["exit_quote"] = trade["exit_mid"] - mid_offset
            if observed_book:
                entry_i = trade["entry_index"]
                trade["entry_bid"] = trade.pop("entry_mid")
                trade["exit_bid"] = trade.pop("exit_mid")
                trade["entry_mid"] = trade["exit_mid"] = None
                trade["entry_ask"] = float(asks[entry_i])
                trade["spread_at_entry"] = float(observed_spreads[entry_i])
                trade["modeled_spread_at_entry"] = float(modeled_spreads[entry_i])
                trade["modeled_entry_ask"] = trade["entry_bid"] + trade["modeled_spread_at_entry"]
                trade["bid_gross_pnl"] = trade["units"] * (trade["exit_bid"] - trade["entry_bid"])
                trade["spread_cost"] = trade["units"] * trade["modeled_spread_at_entry"]
                trade["slippage_cost"] = trade["bid_gross_pnl"] - trade["gross_pnl"] - trade["spread_cost"]
                trade["price_baseline"] = "bid"
            trades.append(trade)
    return {
        "summary": summary, "trades": trades,
        "equity_curve": ([{"time": int(times[start_index + i]), "equity": float(mark)}
                           for i, mark in enumerate(curve)] if include_equity_curve else []),
    }
