"""Position sizing for a fully paid, long-only EUR/USD paper account.

The loss guarantee is measured against equity at entry. It comes from limiting
the *entire purchase*, rather than assuming that a stop order fills at its price.
Owned EUR can lose all of its USD value without exhausting the 1% budget.
This account is not a leveraged FX, futures, CFD, or broker margin account.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, ROUND_FLOOR
import math


HARD_LOSS_FRACTION = 0.01
HARD_NOTIONAL_FRACTION = 0.008
HARD_HOLDING_DAYS = 5


def _number(value: float, label: str, *, positive: bool = False) -> float:
    if isinstance(value, bool) or not math.isfinite(value):
        raise ValueError(f"{label} must be a finite number")
    if value < 0 or (positive and value == 0):
        raise ValueError(f"{label} must be {'positive' if positive else 'nonnegative'}")
    return value


@dataclass(frozen=True)
class CostModel:
    """Conservative transaction costs, quoted against mid-market OHLC bars.

    ``spread_pips`` is the complete bid/ask spread: each side pays half.
    Slippage is applied on each side. Commission is charged separately.
    Zero carry reflects an owned, fully paid currency balance. Optional carry
    is available for sizing stress analysis; autonomous execution rejects it
    because outages would make an ongoing fee impossible to bound indefinitely.
    """

    spread_pips: float = 2.0
    slippage_pips: float = 0.2
    commission_bps: float = 0.35
    minimum_commission: float = 0.10
    carry_per_1000_per_day: float = 0.0
    pip_size: float = 0.0001

    def __post_init__(self) -> None:
        for name in ("spread_pips", "slippage_pips", "commission_bps",
                     "minimum_commission", "carry_per_1000_per_day"):
            _number(getattr(self, name), name)
        _number(self.pip_size, "pip_size", positive=True)
        if self.commission_bps >= 10_000:
            raise ValueError("commission must be below 100% to bound liquidation loss")

    @property
    def side_price_cost(self) -> float:
        return (self.spread_pips / 2.0 + self.slippage_pips) * self.pip_size

    def entry_fill(self, mid: float) -> float:
        return _number(mid, "entry mid", positive=True) + self.side_price_cost

    def exit_fill(self, mid: float) -> float:
        return max(0.0, _number(mid, "exit mid") - self.side_price_cost)

    def commission(self, notional: float) -> float:
        _number(notional, "commission notional")
        return max(self.minimum_commission, notional * self.commission_bps / 10_000)

    def carry(self, entry_notional: float, days: int) -> float:
        _number(entry_notional, "carry notional")
        if not isinstance(days, int) or isinstance(days, bool) or days < 0:
            raise ValueError("carry days must be a nonnegative integer")
        return entry_notional / 1000 * self.carry_per_1000_per_day * days


@dataclass(frozen=True)
class RiskConfig:
    max_loss_fraction: float = HARD_LOSS_FRACTION
    max_notional_fraction: float = HARD_NOTIONAL_FRACTION
    max_holding_days: int = HARD_HOLDING_DAYS

    def __post_init__(self) -> None:
        _number(self.max_loss_fraction, "max loss fraction", positive=True)
        _number(self.max_notional_fraction, "max notional fraction", positive=True)
        if self.max_loss_fraction > HARD_LOSS_FRACTION:
            raise ValueError("the 1% loss limit cannot be increased")
        if self.max_notional_fraction > HARD_NOTIONAL_FRACTION:
            raise ValueError("the 0.8% fully funded exposure cap cannot be increased")
        if (not isinstance(self.max_holding_days, int)
                or isinstance(self.max_holding_days, bool)
                or not 1 <= self.max_holding_days <= HARD_HOLDING_DAYS):
            raise ValueError("holding horizon must be between 1 and 5 calendar days")


@dataclass(frozen=True)
class PositionPlan:
    units: int
    entry_mid: float
    entry_fill: float
    notional: float
    entry_equity: float
    risk_budget: float
    worst_case_loss: float
    stop_price: float
    max_days: int
    entry_commission: float
    reserved_carry: float
    cost_model: CostModel = field(default_factory=CostModel)

    @property
    def worst_case_loss_fraction(self) -> float:
        return self.worst_case_loss / self.entry_equity


DEFAULT_COSTS = CostModel()
DEFAULT_RISK = RiskConfig()


def size_position(
    equity: float,
    entry_mid: float,
    stop_distance: float,
    max_days: int = HARD_HOLDING_DAYS,
    costs: CostModel = DEFAULT_COSTS,
    config: RiskConfig = DEFAULT_RISK,
) -> PositionPlan:
    """Round EUR units down while reserving the complete worst-case loss.

    Spread and slippage are already in ``entry_fill`` and must not be debited
    again as fees. At a zero liquidation price the exit commission is its
    minimum. A commission rate below 100% makes that the worst exit value.
    Decimal sizing avoids a floating-point round-up across the exposure cap.
    ``ValueError`` means the account cannot afford even one whole EUR safely.
    """
    _number(equity, "equity", positive=True)
    _number(entry_mid, "entry mid", positive=True)
    _number(stop_distance, "stop distance", positive=True)
    if stop_distance >= entry_mid:
        raise ValueError("stop distance must be smaller than the entry mid price")
    if (not isinstance(max_days, int) or isinstance(max_days, bool)
            or not 1 <= max_days <= config.max_holding_days):
        raise ValueError("max days exceeds the permitted holding horizon")

    dec = lambda number: Decimal(str(number))
    capital = dec(equity)
    fill = dec(entry_mid) + (
        dec(costs.spread_pips) / 2 + dec(costs.slippage_pips)
    ) * dec(costs.pip_size)
    budget = capital * dec(config.max_loss_fraction)
    minimum = dec(costs.minimum_commission)
    commission_rate = dec(costs.commission_bps) / 10_000
    carry_rate = dec(costs.carry_per_1000_per_day) * max_days / 1000

    # Both inequalities are required because entry commission is max(min, rate).
    maximum_notional = min(
        capital * dec(config.max_notional_fraction),
        (budget - 2 * minimum) / (1 + carry_rate),
        (budget - minimum) / (1 + carry_rate + commission_rate),
    )
    units = int((maximum_notional / fill).to_integral_value(rounding=ROUND_FLOOR))
    if units < 1:
        raise ValueError("equity cannot fund one whole EUR within the loss budget")
    notional = fill * units
    entry_commission = max(minimum, notional * commission_rate)
    reserved_carry = notional * carry_rate
    worst_case = notional + entry_commission + minimum + reserved_carry
    if worst_case > budget or worst_case > capital * Decimal("0.01"):
        raise ValueError("position exceeds the immutable loss budget")

    return PositionPlan(
        units=units,
        entry_mid=float(entry_mid),
        entry_fill=float(fill),
        notional=float(notional),
        entry_equity=float(equity),
        risk_budget=float(budget),
        worst_case_loss=float(worst_case),
        stop_price=float(dec(entry_mid) - dec(stop_distance)),
        max_days=max_days,
        entry_commission=float(entry_commission),
        reserved_carry=float(reserved_carry),
        cost_model=costs,
    )
