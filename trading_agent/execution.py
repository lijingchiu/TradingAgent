"""Deterministic paper fills shared by historical and scheduled execution.

No broker API exists here: this is a fully paid currency-conversion simulator.
Stop fills respect opening gaps; touching stop and target in one unknown OHLC
path resolves to the stop. Realized losses are never truncated to a risk limit.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math

from .risk import CostModel, PositionPlan, HARD_LOSS_FRACTION, HARD_NOTIONAL_FRACTION


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must be timezone-aware datetimes")
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class Bar:
    time: datetime
    open: float
    high: float
    low: float
    close: float

    def __post_init__(self) -> None:
        object.__setattr__(self, "time", _utc(self.time))
        prices = (self.open, self.high, self.low, self.close)
        if any(isinstance(p, bool) or not math.isfinite(p) or p < 0 for p in prices):
            raise ValueError("bar prices must be finite and nonnegative")
        if self.low > min(self.open, self.close) or self.high < max(self.open, self.close):
            raise ValueError("OHLC prices are inconsistent")
        if self.low > self.high:
            raise ValueError("bar low exceeds high")

    @property
    def timestamp(self) -> datetime:
        return self.time


@dataclass
class Position:
    plan: PositionPlan
    entry_time: datetime
    target_price: float
    signal_time: datetime | None = None
    max_adverse_excursion: float = 0.0
    max_drawdown: float = 0.0
    peak_liquidation_pnl: float = 0.0
    last_bar_time: datetime | None = None
    closed: bool = False

    @property
    def entry_equity(self) -> float:
        return self.plan.entry_equity

    @property
    def units(self) -> int:
        return self.plan.units

    @property
    def entry_fill(self) -> float:
        return self.plan.entry_fill

    @property
    def stop_price(self) -> float:
        return self.plan.stop_price

    @property
    def max_days(self) -> int:
        return self.plan.max_days


@dataclass(frozen=True)
class Trade:
    entry_time: datetime
    exit_time: datetime
    units: int
    entry_mid: float
    entry_fill: float
    exit_mid: float
    exit_fill: float
    entry_commission: float
    exit_commission: float
    carry: float
    gross_pnl: float
    net_pnl: float
    reason: str
    max_adverse_excursion: float
    max_drawdown: float
    entry_equity: float
    risk_limit: float
    worst_case_loss: float
    risk_breach: bool

    @property
    def total_fees(self) -> float:
        return self.entry_commission + self.exit_commission + self.carry

    @property
    def return_fraction(self) -> float:
        return self.net_pnl / self.entry_equity


def _costs(position: Position, costs: CostModel | None) -> CostModel:
    actual = position.plan.cost_model
    if costs is not None and costs != actual:
        raise ValueError("execution costs must match the funded position plan")
    return actual


def open_long(
    plan: PositionPlan,
    time: datetime,
    target_price: float,
    signal_time: datetime | None = None,
) -> Position:
    """Open a funded long at the next observed bar's opening mid price.

    The caller must allow at most one open position and use ``size_position``
    on the actual next-open quote. Giving a signal timestamp enforces causality.
    """
    entry_time = _utc(time)
    signal = _utc(signal_time) if signal_time is not None else None
    if signal is not None and entry_time <= signal:
        raise ValueError("entry must occur after the completed signal bar")
    if not math.isfinite(target_price) or target_price <= plan.entry_mid:
        raise ValueError("long target must be finite and above entry mid")
    if plan.cost_model.carry_per_1000_per_day != 0:
        raise ValueError("autonomous fully funded trading requires zero ongoing carry")
    # Revalidate plans loaded from storage or manually constructed by callers.
    if not isinstance(plan.units, int) or isinstance(plan.units, bool) or plan.units <= 0:
        raise ValueError("a position must contain positive whole EUR units")
    expected_fill = plan.cost_model.entry_fill(plan.entry_mid)
    expected_notional = plan.units * expected_fill
    expected_commission = plan.cost_model.commission(expected_notional)
    expected_worst = expected_notional + expected_commission + plan.cost_model.minimum_commission
    if (not math.isfinite(plan.entry_equity) or plan.entry_equity <= 0
            or expected_notional > plan.entry_equity * HARD_NOTIONAL_FRACTION + 1e-9
            or not math.isfinite(plan.risk_budget) or plan.risk_budget <= 0
            or plan.risk_budget > plan.entry_equity * HARD_LOSS_FRACTION + 1e-9
            or expected_worst > plan.risk_budget + 1e-9
            or not isinstance(plan.max_days, int) or isinstance(plan.max_days, bool)
            or not 1 <= plan.max_days <= 5
            or plan.reserved_carry != 0
            or not 0 < plan.stop_price < plan.entry_mid):
        raise ValueError("position plan violates the immutable funding limits")
    for value, expected in (
        (plan.entry_fill, expected_fill), (plan.notional, expected_notional),
        (plan.entry_commission, expected_commission), (plan.worst_case_loss, expected_worst),
    ):
        if not math.isfinite(value) or not math.isclose(value, expected, rel_tol=1e-12, abs_tol=1e-9):
            raise ValueError("position plan contains inconsistent funding amounts")
    position = Position(plan=plan, entry_time=entry_time, target_price=target_price, signal_time=signal)
    # Immediate roundtrip liquidation includes spread, slippage and both fees.
    _observe_price(position, entry_time, plan.entry_mid)
    return position


def _carry_days(position: Position, time: datetime) -> int:
    seconds = max(0.0, (_utc(time) - position.entry_time).total_seconds())
    return math.ceil(seconds / 86400) if seconds else 0


def liquidation_pnl(position: Position, time: datetime, mid: float) -> float:
    costs = position.plan.cost_model
    fill = costs.exit_fill(mid)
    return (
        position.units * (fill - position.entry_fill)
        - position.plan.entry_commission
        - costs.commission(position.units * fill)
        - costs.carry(position.plan.notional, _carry_days(position, time))
    )


def _observe_price(position: Position, time: datetime, mid: float) -> None:
    pnl = liquidation_pnl(position, time, mid)
    position.max_adverse_excursion = max(position.max_adverse_excursion, -pnl, 0.0)
    position.peak_liquidation_pnl = max(position.peak_liquidation_pnl, pnl)
    position.max_drawdown = max(position.max_drawdown, position.peak_liquidation_pnl - pnl)


def force_close(
    position: Position,
    time: datetime,
    mid: float,
    reason: str = "manual_close",
    costs: CostModel | None = None,
) -> Trade:
    """Close at an observed quote, retaining actual costs and risk breaches."""
    if position.closed:
        raise ValueError("position is already closed")
    exit_time = _utc(time)
    if exit_time < position.entry_time or (
        position.last_bar_time is not None and exit_time < position.last_bar_time
    ):
        raise ValueError("exit timestamp precedes previously processed market data")
    actual = _costs(position, costs)
    _observe_price(position, exit_time, mid)
    exit_fill = actual.exit_fill(mid)
    exit_commission = actual.commission(position.units * exit_fill)
    carry = actual.carry(position.plan.notional, _carry_days(position, exit_time))
    gross = position.units * (exit_fill - position.entry_fill)
    net = gross - position.plan.entry_commission - exit_commission - carry
    breach = max(-net, position.max_adverse_excursion) > position.plan.risk_budget + 1e-9
    position.closed = True
    return Trade(
        entry_time=position.entry_time, exit_time=exit_time, units=position.units,
        entry_mid=position.plan.entry_mid, entry_fill=position.entry_fill,
        exit_mid=mid, exit_fill=exit_fill,
        entry_commission=position.plan.entry_commission, exit_commission=exit_commission,
        carry=carry, gross_pnl=gross, net_pnl=net, reason=reason,
        max_adverse_excursion=position.max_adverse_excursion, max_drawdown=position.max_drawdown,
        entry_equity=position.entry_equity, risk_limit=position.plan.risk_budget,
        worst_case_loss=position.plan.worst_case_loss, risk_breach=breach,
    )


def evaluate_long(
    position: Position,
    bar: Bar,
    costs: CostModel | None = None,
) -> Trade | None:
    """Apply gap/stop/target/expiry rules to the next observed OHLC bar.

    Signals come from earlier completed bars. Entry at a bar's open can be
    followed by exit inside that bar. Once an exit occurs, later extremes of
    that bar are not used to invent post-exit MAE. For surviving bars the high
    then low ordering deliberately overestimates drawdown when path is unknown.
    Expiry uses the first available quote, never an invented historical fill.
    """
    if position.closed:
        raise ValueError("position is already closed")
    _costs(position, costs)
    if bar.time < position.entry_time:
        raise ValueError("bar precedes the entry")
    if position.last_bar_time is not None and bar.time <= position.last_bar_time:
        raise ValueError("bars must advance strictly in time")
    position.last_bar_time = bar.time
    _observe_price(position, bar.time, bar.open)
    if bar.open <= position.stop_price:
        return force_close(position, bar.time, bar.open, "stop_gap", costs)
    if bar.open >= position.target_price:
        return force_close(position, bar.time, bar.open, "target_gap", costs)
    elapsed = (bar.time - position.entry_time).total_seconds() / 86400
    if elapsed >= position.max_days:
        return force_close(position, bar.time, bar.open, "expiry", costs)
    if bar.low <= position.stop_price:
        return force_close(position, bar.time, position.stop_price, "stop", costs)
    if bar.high >= position.target_price:
        # Record the worst price that could precede the target under unknown
        # OHLC ordering. The stop branch above rules out a prior stop touch.
        _observe_price(position, bar.time, bar.low)
        return force_close(position, bar.time, position.target_price, "target", costs)
    _observe_price(position, bar.time, bar.high)
    _observe_price(position, bar.time, bar.low)
    _observe_price(position, bar.time, bar.close)
    return None
