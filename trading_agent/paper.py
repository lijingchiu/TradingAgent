"""Persistent paper account. Never sends orders to a real broker."""

from dataclasses import asdict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
from pathlib import Path

from .backtest import jsonable, parse_time
from .execution import Bar, Position, evaluate_long, liquidation_pnl, open_long
from .market import MarketSnapshot, aggregate_bars, forex_is_open, next_weekly_open
from .risk import CostModel, PositionPlan, size_position
from .strategy import StrategyConfig, compute_features, entry_signal, trade_levels

UTC = timezone.utc


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(jsonable(value), ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def new_account(now: datetime, initial: float = 100_000.0) -> dict:
    return {"schema_version": 1, "mode": "paper", "initial_equity": initial,
            "cash": initial, "equity": initial, "realized_pnl": 0.0, "unrealized_pnl": 0.0,
            "position": None, "trades": [], "orders": [], "equity_curve": [],
            "created_at": now.isoformat(), "last_entry_hour": None,
            "status": {"code": "pending_validation", "label": "等待回測驗證", "reason": "尚未通過獨立驗證"}}


def paper_is_approved(selected: dict) -> bool:
    summary = selected.get("final_summary") or {}
    values = [summary.get("eligible_trades", 0), summary.get("win_rate", 0), summary.get("net_profit", 0)]
    if any(isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) for value in values):
        return False
    return bool(selected.get("paper_approved") and selected.get("selection_eligible")
                and summary.get("eligible_trades", 0) >= 30
                and summary.get("win_rate", 0) >= 0.5
                and summary.get("net_profit", 0) > 0
                and summary.get("risk_breaches", 1) == 0)


def restore_position(value: dict) -> Position:
    raw_plan = dict(value["plan"])
    raw_plan["cost_model"] = CostModel(**raw_plan["cost_model"])
    plan = PositionPlan(**raw_plan)
    pos = open_long(plan, parse_time(value["entry_time"]), value["target_price"],
                    parse_time(value["signal_time"]) if value.get("signal_time") else None)
    for name in ("max_adverse_excursion", "max_drawdown", "peak_liquidation_pnl"):
        amount = value.get(name, 0.0)
        if not math.isfinite(amount) or amount < 0:
            raise ValueError("持倉紀錄數值損壞")
        setattr(pos, name, amount)
    pos.last_bar_time = parse_time(value["last_bar_time"]) if value.get("last_bar_time") else None
    if value.get("closed"):
        raise ValueError("帳戶持倉不應是已平倉交易")
    return pos


def update_account(account: dict, selected: dict, market: MarketSnapshot, now: datetime) -> dict:
    """One quote observation; same sizing, signals and exits as research."""
    if account.get("mode") != "paper" or account.get("schema_version") != 1:
        raise ValueError("帳戶格式或模擬模式不符")
    for name in ("cash", "equity", "initial_equity"):
        if not math.isfinite(account[name]) or account[name] <= 0:
            raise ValueError("帳戶資金數值損壞")
    fresh = 0 <= (now - market.quote_time).total_seconds() <= 600
    is_open = forex_is_open(now)
    account["market"] = {"symbol": "EUR/USD", "mid": market.mid,
        "quote_time": market.quote_time.isoformat(), "fetched_at": market.fetched_at.isoformat(),
        "stale": not fresh, "source": "Yahoo Finance 1h indicative spot quotes",
        "source_url": market.source_url, "excluded_invalid": market.excluded_invalid,
        "excluded_null": market.excluded_null}
    account["status"]["next_session_at"] = next_weekly_open(now).isoformat() if not is_open else None
    position = restore_position(account["position"]) if account.get("position") else None
    if position and fresh and is_open and (position.last_bar_time is None or market.quote_time > position.last_bar_time):
        quote_bar = Bar(market.quote_time, market.mid, market.mid, market.mid, market.mid)
        trade = evaluate_long(position, quote_bar)
        if trade:
            costs = position.plan.cost_model
            account["cash"] += trade.units * trade.exit_fill - trade.exit_commission - trade.carry
            account["realized_pnl"] += trade.net_pnl
            row = jsonable(asdict(trade))
            row.update(total_fees=trade.total_fees, mae_pct=trade.max_adverse_excursion / trade.entry_equity * 100,
                       entry_price=trade.entry_fill, exit_price=trade.exit_fill)
            account["trades"].append(row)
            account["last_exit_hour"] = now.replace(minute=0, second=0, microsecond=0).isoformat()
            account["orders"].append({"id": "exit-" + trade.exit_time.isoformat(), "side": "sell",
                "time": trade.exit_time.isoformat(), "units": trade.units, "price": trade.exit_fill,
                "reason": trade.reason, "mode": "paper", "status": "filled"})
            position = None
            if trade.risk_breach:
                account["risk_halted"] = True
    # A fresh quote may mark an owned balance; stale prices are explicitly labelled.
    if position:
        liquidation = liquidation_pnl(position, market.quote_time, market.mid)
        account["equity"] = position.entry_equity + liquidation
        account["unrealized_pnl"] = liquidation
    else:
        account["equity"] = account["cash"]
        account["unrealized_pnl"] = 0.0

    approved = paper_is_approved(selected)
    config = StrategyConfig.from_dict(selected["config"]) if selected.get("config") else None
    fingerprint = hashlib.sha256(json.dumps(selected.get("config"), sort_keys=True).encode()).hexdigest()
    if selected.get("config") and account.get("strategy_fingerprint") not in (None, fingerprint):
        account["risk_halted"] = True
    if selected.get("config"):
        account["strategy_fingerprint"] = fingerprint
    if account.get("risk_halted"):
        code, label, reason = "risk_halted", "風控鎖定", "風險或策略版本異常，禁止新增部位"
    elif not approved:
        code, label, reason = "validation_failed", "回測未通過・禁止下單", "；".join(selected.get("gate_reasons", ["獨立驗證未達標"]))
    elif not is_open:
        code, label, reason = "market_closed", "市場休市・等待開盤", "外匯市場採紐約週日 17:00 至週五 17:00 的 24/5 監控"
    elif not fresh:
        code, label, reason = "stale_market", "行情過期・暫停新增交易", "報價超過 10 分鐘；保留持倉並等待可靠報價"
    elif market.excluded_invalid:
        code, label, reason = "invalid_market", "行情品質異常・禁止新增交易", "來源存在不一致 OHLC 價格"
    else:
        code, label, reason = "monitoring", "模擬監控中", "只使用已完成小時訊號；沒有符合條件就保持現金"
        bar_hours = getattr(config, "bar_hours", 1)
        hour = now.replace(hour=now.hour // bar_hours * bar_hours, minute=0, second=0, microsecond=0)
        key = hour.isoformat()
        signal_bars = aggregate_bars(market.bars, bar_hours)
        last_bar = signal_bars[-1] if signal_bars else None
        timing_ok = ((now - hour).total_seconds() <= 600
                     and last_bar is not None and last_bar.time + timedelta(hours=bar_hours) == hour
                     and market.quote_time >= hour)
        exit_bucket = parse_time(account["last_exit_hour"]) if account.get("last_exit_hour") else None
        if config and position is None and timing_ok and account.get("last_entry_hour") != key and (exit_bucket is None or exit_bucket < hour):
            # Record attempted session before any order; retries cannot duplicate it.
            account["last_entry_hour"] = key
            features = compute_features(signal_bars, config)
            if entry_signal(features[-1], config):
                costs = CostModel(**selected.get("cost_model", {}))
                stop, target = trade_levels(features[-1], config)
                plan = size_position(account["equity"], market.mid, stop, config.max_days, costs)
                position = open_long(plan, market.quote_time, market.mid + target, last_bar.time)
                account["cash"] -= plan.notional + plan.entry_commission
                account["orders"].append({"id": "entry-" + key, "side": "buy", "time": market.quote_time.isoformat(),
                    "units": plan.units, "price": plan.entry_fill, "stop": plan.stop_price,
                    "target": position.target_price, "mode": "paper", "status": "filled"})
                account["unrealized_pnl"] = liquidation_pnl(position, market.quote_time, market.mid)
                account["equity"] = plan.entry_equity + account["unrealized_pnl"]
    account["position"] = jsonable(asdict(position)) if position else None
    account["status"] = {"code": code, "label": label, "reason": reason,
        "last_success_at": now.isoformat(), "next_session_at": next_weekly_open(now).isoformat() if not is_open else None}
    account["updated_at"] = now.isoformat()
    if not account["equity_curve"] or account["equity_curve"][-1]["timestamp"] != now.isoformat():
        account["equity_curve"].append({"timestamp": now.isoformat(), "equity": account["equity"], "segment": "paper"})
    # Sampling is honest: no invented stops between missed quote observations.
    account["equity_curve"] = account["equity_curve"][-20_000:]
    return account


def tick(state_dir: Path, selected_path: Path, fetcher, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / ".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = state_dir / "account.json"
        account = json.loads(path.read_text()) if path.exists() else new_account(now)
        selected = json.loads(selected_path.read_text()) if selected_path.exists() else {"paper_approved": False, "gate_reasons": ["尚未完成獨立驗證"]}
        try:
            market = fetcher(now)
            # Financial transitions commit together; exceptions retain the
            # original balance, position and trades rather than a partial sale.
            working = deepcopy(account)
            account = update_account(working, selected, market, now)
        except Exception as error:
            # Do not swallow the failure or reset an existing ledger.
            account["status"] = {"code": "data_error", "label": "行情或帳戶異常・暫停",
                "reason": type(error).__name__ + ": " + str(error), "last_attempt_at": now.isoformat()}
            atomic_json(path, account)
            raise
        atomic_json(path, account)
        return account
