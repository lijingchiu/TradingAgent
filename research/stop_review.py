"""Summarize saved entry-time stop diagnostics; never open price/final data."""
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts/intraday"
LABELS={"atr_pips":"入場前波動幅度（ATR14，點）",
        "atr_fast_slow_ratio":"短期／長期波動比（ATR14／ATR96）",
        "ema_slope_atr":"長期趨勢斜率（以波動標準化）",
        "distance_from_ema_atr":"價格離長期均線距離（以波動標準化）",
        "completed_bar_body_fraction":"已完成K線實體／全幅",
        "current_quote_spread_pips":"入場時買賣價差（點）",
        "current_quote_hour_utc":"入場時刻（UTC小時）"}


def read_rows(path):
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def finite_values(rows,key):
    result=[]
    for row in rows:
        if row[key]:
            value=float(row[key])
            if value==value and abs(value)!=float("inf"):
                result.append(value)
    return result


def mean(rows,key):
    values=finite_values(rows,key)
    return math.fsum(values)/len(values) if values else None


def median(rows,key):
    values=finite_values(rows,key)
    if not values:
        return None
    values.sort()
    middle=len(values)//2
    return values[middle] if len(values)%2 else (values[middle-1]+values[middle])/2


def build():
    case_specs=[]
    for minutes in (5,15):
        case_specs.append(("EURUSD",minutes,BASE/f"fxcm_rsi2/rsi2_m{minutes}_usd500000_unfiltered_development_trade_features.csv"))
        for symbol in ("GBPUSD","NZDUSD"):
            case_specs.append((symbol,minutes,BASE/f"fxcm_rsi2_cross_asset/{symbol.lower()}_rsi2_m{minutes}_usd500000_unfiltered_development_trade_features.csv"))
    cases=[]
    for symbol,minutes,path in case_specs:
        rows=read_rows(path)
        stops=[r for r in rows if r["stopped"]=="True"]
        wins=[r for r in rows if r["won"]=="True"]
        export=BASE/"stop_review"/f"{symbol.lower()}_m{minutes}_2017_stops.csv"
        export.parent.mkdir(exist_ok=True)
        with export.open("w",newline="") as handle:
            writer=csv.DictWriter(handle,fieldnames=list(rows[0]) if rows else [])
            writer.writeheader();writer.writerows(stops)
        case=dict(symbol=symbol,minutes=minutes,period="2017 開發期",initial_equity_usd=500000,
                  natural_trades=len(rows),stopped_trades=len(stops),winning_trades=len(wins),
                  mean_stopped_net_pips=mean(stops,"net_pips"),mean_winning_net_pips=mean(wins,"net_pips"),
                  winning_median_holding_bars=median(wins,"holding_seconds")/(minutes*60) if wins else None,
                  feature_medians=[dict(feature=key,label=label,stops=median(stops,key),wins=median(wins,key)) for key,label in LABELS.items()],
                  stop_trace_path=str(export.relative_to(ROOT)),stop_trace_sha256=hashlib.sha256(export.read_bytes()).hexdigest(),
                  source_feature_path=str(path.relative_to(ROOT)),source_feature_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        cases.append(case)
    reference=next(case for case in cases if case["symbol"]=="EURUSD" and case["minutes"]==15)
    base_report=json.loads((BASE/"fxcm_rsi2/selection_report.json").read_text())
    names=[("原始RSI2", "rsi2_m15_usd500000_unfiltered"),
           ("依開發期波動模式過濾", "rsi2_m15_usd500000_stop_pattern_tree_depth1"),
           ("5分鐘深度2模式過濾", "rsi2_m5_usd500000_stop_pattern_tree_depth2")]
    validation=[]
    for label,name in names:
        row=next(r for r in base_report["candidates"] if r["config"]["name"]==name)
        s=row["validation"];stats=row["validation_statistics"]
        validation.append(dict(label=label,config=name,period="2018–2021 選擇驗證",initial_equity_usd=500000,
                               natural_trades=s["eligible_trades"],win_rate=s["win_rate"],net_profit_usd=s["net_profit"],
                               mean_net_pnl_usd=stats["mean_net_pnl_per_natural_trade"],
                               average_net_winner_usd=stats["average_net_winner"],average_absolute_net_loser_usd=stats["average_absolute_net_loser"],
                               passed=bool(row["selection_eligible"])))
    lock=json.loads((BASE/"fxcm_rsi2/development_pattern_lock.json").read_text())
    model=lock["models"]["rsi2_m15_usd500000_stop_pattern_tree_depth1"]
    leaves=model["leaf_training_diagnostics"]
    ratio_pattern=dict(feature="atr_fast_slow_ratio",threshold=model["nodes"][0]["threshold"],
                       below=leaves["1"],above=leaves["2"],population="Original 460 development trades, not reexecuted filtered trades",
                       validation_result="Failed: filtered actual validation trades still have negative net expectancy")
    result=dict(updated_at_utc=datetime.now(timezone.utc).isoformat(),reference_case=reference,cases=cases,
                title="止損與獲利模式檢討",learning_period="2017 開發資料；參數先鎖定再驗證",
                summary="開發期止損損失遠大於平均獲利；波動收縮時止損較多。但避開這些模式及縮小止損後，另一段資料仍未得到正向期望。",
                development_pattern=ratio_pattern,validation_comparisons=validation,
                entry_feature_note="只使用已完成K線的趨勢、波動及實體；價差與時刻在取得入場報價時可知。點數以pip＝0.0001計算，全部已扣價差、滑價及佣金。",
                report_url="https://github.com/lijingchiu/TradingAgent/blob/main/artifacts/intraday/stop_review.md",
                independence_note="2018–2021用於選擇驗證且有既有研究歷史；2022-04至2024-09最終策略績效仍未檢視。",
                outcome="No qualified positive-expectancy strategy. All paper entries remain disabled.")
    (BASE/"stop_review.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    lines=["# 止損與獲利模式檢討","",result["summary"],"",
           "本次先逐筆分析2017年開發期的入場特徵，再鎖定篩選模型，才回測2018–2021年。三個標的、5／15分鐘、USD100,000／500,000兩個資金情境各自計算；不同策略的成交不能合併為500筆。下表每列使用USD500,000研究帳戶，並不是前向模擬帳戶的餘額。","",
           "| 標的／週期 | 自然平倉 | 止損筆數 | 獲利筆數 | 止損平均淨點數 | 獲利平均淨點數 | 贏家持有時間中位數（分鐘） | 每筆止損 |",
           "|---|---:|---:|---:|---:|---:|---:|---|"]
    for case in cases:
        link=str(Path(case["stop_trace_path"]).relative_to("artifacts/intraday"))
        lines.append(f'| {case["symbol"]} M{case["minutes"]} | {case["natural_trades"]} | {case["stopped_trades"]} | {case["winning_trades"]} | {case["mean_stopped_net_pips"]:+.2f} | {case["mean_winning_net_pips"]:+.2f} | {case["winning_median_holding_bars"]*case["minutes"]:.0f} | [CSV]({link}) |')
    lines.extend(["","點數以pip＝0.0001計算。以EUR/USD M15為例，61筆止損平均−28.89點，293筆贏家平均+8.71點。全額購入的外幣本金上限仍為進場權益0.8%，觀測到的兩種單筆回撤均低於1%；大量小贏不足以覆蓋較大的虧損與交易成本。","",
                  "| 入場前特徵（EUR/USD M15） | 止損交易中位數 | 獲利交易中位數 |","|---|---:|---:|"])
    for item in reference["feature_medians"]:
        lines.append(f'| {item["label"]} | {item["stops"]:.3f} | {item["wins"]:.3f} |')
    lines.extend(["","時刻為UTC，台灣時間加8小時。ATR是價格波動幅度；資料沒有交易量欄位，沒有把低ATR稱為低成交量。","",
                  f'開發期樹模型將ATR14／ATR96約{ratio_pattern["threshold"]:.3f}以下的161筆交易分成一群：止損率{100*ratio_pattern["below"]["stop_rate"]:.2f}%，平均淨值−2.95點；其餘299筆止損率{100*ratio_pattern["above"]["stop_rate"]:.2f}%，平均+1.52點。這只是開發期的關聯；凍結規則後必須重新成交回測，不能把刪除虧損交易當成策略收益。',"",
                  "| 固定規則 | 另一段資料的自然平倉 | 淨勝率 | 扣成本淨損益（USD） | 每筆平均淨損益（USD） |","|---|---:|---:|---:|---:|"])
    for row in validation:
        lines.append(f'| {row["label"]} | {row["natural_trades"]} | {100*row["win_rate"]:.2f}% | {row["net_profit_usd"]:+.2f} | {row["mean_net_pnl_usd"]:+.4f} |')
    lines.extend(["","M15過濾後總虧損較少，主要因為成交變少；平均每筆仍為負，不能說產生正向期望。M5深度2模式雖完成759筆且淨勝率60.21%，平均贏家約USD2.15、平均輸家約USD3.82，每筆期望仍約−USD0.23。","",
                  "另依2017年的贏家歷史不利波動與持有時間，先登記2ATR止損、12根最長持有、反彈確認與避免波動收縮的固定版本；三個標的均未通過成本後驗證。這些失敗也已完整保留，沒有只報開發期獲利版本。","",
                  "先前2015年259筆NY08時段診斷也以同一參數確認多年FXCM報價：USD500,000情境開發761筆、+USD422.28，但2018–2021的993筆只有46.73%淨勝率、−USD415.51。原來的一年獲利沒有跨年份驗證。","",
                  "價差使用當時實際資料中的ASK買入與BID賣出，另外每側0.2點滑價、0.35bps佣金及最低USD0.10費用；不是零成本結果。FXCM說明這些是Active Trader最低價差的指示性報價，尚不能認定一般帳戶可成交。原始報價留在本地，未重新散布。","",
                  "本輪增加72組固定／學習配置和2次既有策略來源確認。全部未通過開發與選擇驗證，沒有選定策略；最終保留期策略績效仍未開啟。研究盈虧不計入前向帳戶，模擬入場保持關閉。","",
                  "[完整彙總](README.md) · [原始策略與樹模型鎖定紀錄](fxcm_rsi2/development_pattern_lock.json) · [縮小止損規則登記](fxcm_rsi2_tailguard/preregistration.json) · [跨標的驗證](fxcm_rsi2_cross_asset/selection_report.json) · [固定時段來源確認](fxcm_fixed_session/selection_report.json)",""])
    (BASE/"stop_review.md").write_text("\n".join(lines))
    print(json.dumps({"cases":len(cases),"stops_per_case":[c["stopped_trades"] for c in cases],"outcome":result["outcome"]}))
    return result


if __name__=="__main__":build()
