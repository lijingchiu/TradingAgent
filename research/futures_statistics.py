"""Signed genuine-contract research statistics; frozen FX helpers are reused.

No source prices or quantities are negated to adapt futures shorts to an FX
model. LAST_TRADE quotes remain observed source values; their midpoint use is
a declared execution proxy. Real BID/ASK and a futures loss guarantee have not
been established. This module never fetches data or evaluates strategies.
"""

from __future__ import annotations

import math
from typing import Any, Iterable

from .statistics import (
    _row, _finite, summarize_trades as _summarize_generic,
    wilson_interval, daily_realized_returns, moving_block_bootstrap_mean,
    acceptance_assessment,
)


def summarize_trades(trades: Iterable[Any], terminal_reason: str = "sample_end") -> dict[str, Any]:
    rows = [_row(value) for value in trades]
    sanitized = []
    source_gross = fill_gross = spread_cost = slippage_cost = fees = 0.0
    for row in rows:
        direction = _finite(row["direction"], "direction")
        quantity = _finite(row["contracts"], "contracts")
        multiplier = _finite(row["contract_multiplier"], "contract multiplier")
        units = _finite(row["units"], "units")
        if direction not in (-1, 1) or quantity != 1 or multiplier <= 0 or units <= 0:
            raise ValueError("futures rows require direction +/-1, exactly one contract and positive pricing units")
        if not math.isclose(units, multiplier * quantity, rel_tol=1e-12, abs_tol=1e-12):
            raise ValueError("positive pricing units do not reconcile genuine contract quantity and multiplier")
        entry, exited = (_finite(row[name], name) for name in ("entry_quote", "exit_quote"))
        entry_fill, exit_fill = (_finite(row[name], name) for name in ("entry_fill", "exit_fill"))
        expected_source = direction * units * (exited - entry)
        expected_fill = direction * units * (exit_fill - entry_fill)
        actual_source = _finite(row["source_last_trade_gross_pnl"], "source gross PnL")
        actual_fill = _finite(row["gross_pnl"], "fill gross PnL")
        spread = _finite(row["spread_cost"], "spread cost")
        slip = _finite(row["slippage_cost"], "slippage cost")
        commission = math.fsum(_finite(row[key], key) for key in ("entry_commission", "exit_commission", "carry"))
        net = _finite(row["net_pnl"], "net PnL")
        if spread < 0 or slip < 0 or commission < 0:
            raise ValueError("futures execution costs must be nonnegative")
        if direction * (entry_fill - entry) < -1e-10 or direction * (exited - exit_fill) < -1e-10:
            raise ValueError("futures fills violate the declared adverse side-price model")
        for actual, expected, name in (
            (actual_source, expected_source, "signed source quote PnL"),
            (actual_fill, expected_fill, "signed fill PnL"),
            (actual_source - spread - slip, actual_fill, "source/spread/slippage reconciliation"),
            (actual_fill - commission, net, "fill/fee/net reconciliation"),
        ):
            if not math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-7):
                raise ValueError(name + " failed")
        if "cash_after_exit" in row:
            delta = _finite(row["cash_after_exit"], "exit cash") - _finite(row["entry_equity"], "entry equity")
            if not math.isclose(delta, net, rel_tol=1e-10, abs_tol=1e-7):
                raise ValueError("futures collateral/cash ledger does not reconcile net PnL")
        source_gross += actual_source
        fill_gross += actual_fill
        spread_cost += spread
        slippage_cost += slip
        fees += commission
        # The frozen generic helper still supplies expectancy, Wilson and risk
        # measurements. Suppress its long-only midpoint calculation, then add
        # the independently verified genuine directional source baseline.
        sanitized.append({**row, "entry_mid": None, "exit_mid": None})
    summary = _summarize_generic(sanitized, terminal_reason)
    summary.update({
        "gross_mid_profit": None, "gross_bid_profit": None,
        "gross_source_last_trade_profit": source_gross,
        "source_baseline_gross_profit": source_gross,
        "gross_after_price_friction_before_fees": fill_gross,
        "price_baseline": "source_last_trade_as_mid_proxy",
        "spread_slippage_friction": spread_cost + slippage_cost,
        "modeled_spread_cost": spread_cost, "modeled_slippage_cost": slippage_cost,
        "explicit_commission_and_carry": fees,
        "directional_contract_reconciliation_complete": True,
        "mid_quotes_observed": False,
        "derivative_loss_bound_established": False,
        "paper_activation_authorized": False,
        "long_trades": sum(row["direction"] == 1 for row in rows),
        "short_trades": sum(row["direction"] == -1 for row in rows),
    })
    return summary


# Explicit name for genuine futures callers; the short name is also available.
summarize_futures_trades = summarize_trades
