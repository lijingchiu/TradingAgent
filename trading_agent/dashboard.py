"""Two views of one reviewed snapshot: HTML monitor and private GitHub page."""

from dataclasses import asdict
from datetime import datetime, timezone
import json
from pathlib import Path

from .paper import atomic_json, new_account, paper_is_approved
from .risk import DEFAULT_COSTS


def metrics(summary: dict | None) -> dict:
    if not summary:
        return {}
    return {"trade_count": summary.get("eligible_trades"), "win_rate": summary.get("win_rate"),
        "net_profit": summary.get("net_profit"), "net_return_pct": summary.get("net_return", 0) * 100,
        "profit_factor": summary.get("profit_factor"),
        "max_drawdown_pct": summary.get("max_account_drawdown_close_marks", 0) * 100,
        "max_trade_loss_pct": summary.get("max_trade_adverse_equity_fraction", 0) * 100,
        "confidence_interval": summary.get("win_rate_wilson_95"),
        "risk_breaches": summary.get("risk_breaches"), "first_bar": summary.get("first_bar"),
        "last_bar": summary.get("last_bar"), "total_commission": summary.get("total_commission"),
        "terminal_liquidations": summary.get("terminal_liquidations")}


def read_json(path: Path, default: dict) -> dict:
    return json.loads(path.read_text()) if path.exists() else default


def build_snapshot(root: Path, state_dir: Path, web_dir: Path) -> dict:
    now = datetime.now(timezone.utc)
    account = read_json(state_dir / "account.json", new_account(now))
    selected = read_json(root / "artifacts/selected_strategy.json", {})
    report = read_json(root / "artifacts/backtest_report.json", {})
    preparation = read_json(root / "artifacts/research_before_holdout.json", {})
    if not report:
        report = preparation
    protocol = report.get("protocol", {})
    stages = protocol.get("research_stages", [])
    count = sum(stage.get("trials", 0) for stage in stages) or selected.get("candidate_count", 0)
    combined = read_json(root / "artifacts/research_summary.json", {})
    count = combined.get("cumulative_pair_timeframe_parameter_trials", count)
    final = report.get("final", {})
    validation = {"passed": paper_is_approved(selected),
        "final_metrics": metrics(final.get("summary") or selected.get("final_summary")),
        "train_metrics": metrics(report.get("development")),
        "validation_metrics": metrics(report.get("validation")),
        "stress_metrics": metrics(report.get("stress_2x_costs")),
        "candidate_count": count, "warnings": report.get("limitations", []) + selected.get("gate_reasons", []),
        "research_summary": combined,
        "periods": {"development": "2012–2018", "validation": "2019–2022",
                    "final": selected.get("final_start", "尚未評估") + " 起獨立資料"}}
    config = selected.get("config", {})
    position = account.get("position")
    plan = position["plan"] if position else {}
    curve = account.get("equity_curve", [])
    backtest_curve = [{"timestamp": row.get("time"), "equity": row.get("equity"), "segment": "final"}
                      for row in final.get("equity_curve", [])]
    # The two curves have independent starting capital and must never be joined.
    snapshot = {"generated_at": now.isoformat(), "mode": "paper", "status": account.get("status", {}),
        "account": {key: account.get(key) for key in ("initial_equity", "cash", "equity", "realized_pnl", "unrealized_pnl", "position")},
        "validation": validation,
        "strategy": {"name": config.get("name", "研究尚未完成"), "symbol": "EUR/USD",
                     "timeframe": str(config.get("bar_hours", 1)) + "h", "config": config},
        "market": account.get("market", {}),
        "risk": {"max_loss_ratio": 0.01, "max_notional_ratio": 0.008,
                 "worst_case_loss": plan.get("worst_case_loss"), "risk_budget": plan.get("risk_budget"),
                 "basis": "每筆入場時帳戶權益；持有已全額付款的 EUR，不借款、不放空"},
        "costs": selected.get("cost_model", asdict(DEFAULT_COSTS)),
        "trades": account.get("trades", []), "orders": account.get("orders", []), "equity_curve": curve,
        "backtest_trades": final.get("trades", []), "backtest_equity_curve": backtest_curve,
        "source_metadata": [
            {"source": "歷史開發資料：GitHub 鏡像", "url": "https://github.com/ejtraderLabs/historical-data",
             "date_range": "2012–2022", "data_quality": "原始券商與時區未確認；僅作策略研發，不作開盤時間假設"},
            {"source": "獨立驗證與即時資料：Yahoo Finance EURUSD=X 1h",
             "url": "https://finance.yahoo.com/quote/EURUSD=X/", "date_range": "2024–2026",
             "data_quality": "指示性公開報價；已排除空值與未完成 K 線。不是券商可成交報價。原生日線品質異常，停用。"}],
        "execution_notes": ["自行建立的現金外匯模擬帳戶，沒有送單至真實券商。",
            "排程每小時第 2 分鐘監控；GitHub 排程可能延遲。超出入場時窗就略過交易。",
            "回測 OHLC 的盤中停損假設與模擬盤定時觀察有差異；模擬盤按實際取得的報價成交，不補造錯過的成交。",
            "1% 是相對入場資金的損失上限；累積帳戶回撤及浮盈高點回撤另外揭露。"]}
    snapshot["account"]["trade_count"] = len(snapshot["trades"])
    web_dir.mkdir(parents=True, exist_ok=True)
    atomic_json(web_dir / "snapshot.json", snapshot)
    write_monitor(state_dir / "MONITOR.md", snapshot)
    return snapshot


def write_monitor(path: Path, s: dict) -> None:
    def money(value):
        return "尚無資料" if value is None else f"${value:,.2f}"
    a, v = s["account"], s["validation"]
    f = v["final_metrics"]
    timestamp = s["generated_at"]
    lines = ["# TradingAgent 模擬交易監控", "",
        f"**{s['status'].get('label', '等待驗證')}**", "", s["status"].get("reason", ""), "",
        f"更新時間：{timestamp}（UTC；台灣時間 +8 小時）。每小時自動更新；重新整理本頁可查看最新紀錄。", "",
        "> 本頁只顯示模擬交易。回測獲利不會加入模擬帳戶。", "",
        "| 模擬帳戶 | 數值 |", "|---|---:|",
        f"| 初始資金 | {money(a['initial_equity'])} USD |",
        f"| 目前權益 | {money(a['equity'])} USD |", f"| 現金 | {money(a['cash'])} USD |",
        f"| 已實現損益 | {money(a['realized_pnl'])} USD |", f"| 未實現損益 | {money(a['unrealized_pnl'])} USD |",
        f"| 已平倉模擬交易 | {a['trade_count']} |", "",
        "## 策略與驗證", "",
        f"策略：`{s['strategy']['name']}`；EUR/USD，{s['strategy']['timeframe']}。", "",
        f"完整搜尋紀錄：{v['candidate_count']} 組策略／標的／週期試驗。最終資料不參與挑選策略。", "",
        "| 獨立驗證 | 結果 |", "|---|---:|",
        f"| 自然平倉交易數 | {f.get('trade_count', '尚未評估')} |",
        f"| 扣成本後淨利 | {money(f.get('net_profit'))} USD |",
        f"| 勝率 | {f.get('win_rate') * 100:.2f}% |" if f.get("win_rate") is not None else "| 勝率 | 尚未評估 |",
        f"| 允許新增模擬部位 | {'是' if v['passed'] else '否'} |", "",
        "## 風控", "",
        "每筆入場投入本金上限為當時帳戶權益的 0.8%，加上最壞交易費用必须低於 1%。只持有已全額付款的 EUR，不借款、不放空；EUR 即使完全貶值也不超過單筆入場資金預算。這不是槓桿期貨或 CFD。", "",
        "1% 限制以入場資金為基準；累積帳戶回撤與浮盈高點回撤另計，不能混為同一個保證。", "",
        "成本模型：2 pip 完整買賣價差、每邊 0.2 pip 滑價、每邊 0.35 bps 佣金（最低 US$0.10）。全額付款的貨幣持有不計借款融資費。", "",
        "## 目前部位", ""]
    if a.get("position"):
        p = a["position"]
        plan = p["plan"]
        lines += [f"持有 {plan['units']} EUR；入場價 {plan['entry_fill']:.5f}；停損 {plan['stop_price']:.5f}；目標 {p['target_price']:.5f}。",
                  f"最壞本金加費用損失 {money(plan['worst_case_loss'])}；預算 {money(plan['risk_budget'])}。", ""]
    else:
        lines += ["沒有持倉。", ""]
    lines += ["## 最近模擬交易", "", "| 入場 | 出場 | 數量 EUR | 淨損益 USD | 出場原因 |", "|---|---|---:|---:|---|"]
    for t in reversed(s["trades"][-20:]):
        lines.append(f"| {t['entry_time']} | {t['exit_time']} | {t['units']} | {money(t['net_pnl'])} | {t['reason']} |")
    if not s["trades"]:
        lines += ["| — | — | — | 尚未成交 | — |"]
    lines += ["", "## 資料與限制", ""] + ["- " + note for note in s["execution_notes"]]
    lines += ["- " + warning for warning in v["warnings"]]
    lines += ["", "[完整 HTML 面板原始檔](../web/index.html) · [自動排程執行紀錄](https://github.com/lijingchiu/TradingAgent/actions/workflows/paper-trader.yml)", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines))
