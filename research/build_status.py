"""Create a reviewable research summary from saved evidence, without backtests.

Neither prices nor holdout outcomes are loaded here. Repaired evaluations are
counted once; source confirmations and operating-capital variants are explicit.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=ROOT/"artifacts/intraday"


def load(relative):
    return json.loads((BASE/relative).read_text())


def rows(report):
    for key in ("candidate_results","candidates","results"):
        if isinstance(report.get(key),list): return report[key]
    raise ValueError("Missing evaluated candidate records")


def summary(row,phase):
    value=row[phase]
    return value.get("summary",value)


def diagnostic(reports,currency="USD"):
    candidates=[(row,summary(row,"validation")) for report in reports for row in rows(report)
                if "validation" in row]
    enough=[(row,s) for row,s in candidates if s.get("eligible_trades",0)>=500]
    picked=max(enough or candidates,key=lambda pair:pair[1].get("win_rate",0)) if candidates else None
    if not picked:return None
    row,s=picked
    return dict(name=row.get("config",{}).get("name","參見明細"),
                trade_count=s["eligible_trades"],win_rate=s["win_rate"],net_profit=s["net_profit"],
                currency=currency,split="驗證期",initial_equity=s["initial_equity"],
                explanation="具代表性的高勝率診斷案例；未通過成本後獲利，並非選定策略")


def build():
    definitions=[
        ("布林區間回復","EUR/USD · GBP/USD",["15m"],48,
         ["mean_reversion/eurusd/development_report.json","mean_reversion/gbpusd/development_report.json","mean_reversion/authoritative_eurusd/development_report.json"],"USD"),
        ("跨貨幣相對回復","EUR/USD · GBP/USD",["15m"],64,
         ["mean_reversion/relative/eurusd/development_report.json","mean_reversion/relative/gbpusd/development_report.json"],"USD"),
        ("突破與趨勢延續","EUR/USD · GBP/USD",["15m"],16,
         ["breakout/eurusd_mirror_devval.json","breakout/gbpusd_mirror_devval.json","breakout/eurusd_dukascopy_devval.json"],"USD"),
        ("成本敏感分類模型","EUR/USD · GBP/USD",["15m"],24,
         ["model/eurusd_mirror_devval_age_fixed.json","model/gbpusd_mirror_devval_age_fixed.json","model/eurusd_direct_bid_devval.json"],"USD"),
        ("多週期趨勢深回撤","EUR/USD",["15m"],48,["model/pullback_direct_bid_devval.json"],"USD"),
        ("區間低點掃蕩回復","EUR/USD",["5m","15m"],48,["sweep/m5_development_validation.json","sweep/m15_development_validation.json"],"USD"),
        ("交易時段與前段回復","EUR/USD",["15m"],48,["mean_reversion/session_study/development_report.json","mean_reversion/session_study/capital_500000_development_report.json"],"USD"),
        ("交易時段順勢與完整尾部","EUR/USD",["15m"],18,["breakout/utc_flow_fixed_2pip.json"],"USD"),
        ("定價時點後回復","EUR/USD",["15m"],16,["sweep/fixing/development_validation.json"],"USD"),
        ("美元／日圓趨勢深回撤","USD/JPY",["15m"],24,["jpy/usdjpy_mirror_devval.json"],"JPY"),
    ]
    families=[]; source_count=0; evidence=[]
    for name,symbol,timeframes,variants,paths,currency in definitions:
        reports=[load(path) for path in paths]
        evaluations=sum(len(rows(r)) for r in reports)
        source_count+=evaluations
        evidence.extend(paths)
        families.append(dict(name=name,symbol=symbol,timeframes=timeframes,trials=variants,
                             source_evaluations=evaluations,status="未通過",
                             diagnostic=diagnostic(reports,currency),report_paths=paths,
                             note="參數與資金配置在評估前登記；最後保留期未用於選擇。"))
    partial="mean_reversion/session_study/measured_book_2015_diagnostic_report.json"
    observed=load(partial)
    best=max(observed["results"],key=lambda row:row["engine_summary"]["net_profit"])
    s=best["engine_summary"]
    paired_family=dict(name="實際買賣報價確認",symbol="EUR/USD",timeframes=["15m"],trials=0,
                         source_evaluations=0,status="等待完整資料",diagnostic=dict(
                             trade_count=s["eligible_trades"],win_rate=s["win_rate"],net_profit=s["net_profit"],
                             currency="USD",split="2015 年開發診斷",initial_equity=s["initial_equity"],
                             explanation="只有完整2015年的樣本獲利；少於500筆且尚無完整驗證，未選定。"),
                         report_paths=[partial],note="另有24次完整2015年報價診斷；不得稱為2015–2021完整驗證。")
    confirmation="fxcm_fixed_session/selection_report.json"
    if (BASE/confirmation).exists():
        confirmed=load(confirmation)
        chosen=next(r for r in rows(confirmed) if r["config"]["capital"]==500000)
        s=chosen["validation"]
        paired_family.update(source_evaluations=2,status="未通過",diagnostic=dict(
            name=chosen["config"]["name"],trade_count=s["eligible_trades"],win_rate=s["win_rate"],
            net_profit=s["net_profit"],currency="USD",split="2018–2021 選擇驗證",initial_equity=s["initial_equity"],
            explanation="原2015年獲利259筆的同一參數；FXCM多年報價確認未通過，沒有選定策略。"),
            report_paths=[partial,confirmation],note="完整多年度FXCM公開雙側報價來源確認；最低價差為Active Trader指示性價格，非一般帳戶成交證明。")
        evidence.append(confirmation);source_count+=2
    families.append(paired_family)
    evidence.append(partial)
    new_definitions=[
        ("RSI2止損模式篩選","EUR/USD",12,"fxcm_rsi2/selection_report.json"),
        ("RSI2止損／等待時間與反彈","EUR/USD",12,"fxcm_rsi2_tailguard/selection_report.json"),
        ("RSI2相同規則跨標的驗證","GBP/USD · NZD/USD",48,"fxcm_rsi2_cross_asset/selection_report.json"),
    ]
    new_final_untouched=True
    for name,symbol,variants,path in new_definitions:
        if not (BASE/path).exists():continue
        report=load(path);evaluations=len(rows(report))
        if evaluations!=variants:raise ValueError("New study evaluated count differs from registration")
        families.append(dict(name=name,symbol=symbol,timeframes=["5m","15m"],trials=variants,
            source_evaluations=evaluations,status="候選待保留期驗證" if report["selection_eligible_count"] else "未通過",
            diagnostic=diagnostic([report]),report_paths=[path],
            note="入場前特徵與止損／獲利逐筆檢討；只從2017年開發資料學習，規則鎖定後才做2018–2021選擇驗證。"))
        source_count+=evaluations;evidence.append(path)
        new_final_untouched &= str(report.get("final","")).startswith("UNTOUCHED")
    future_definitions=[
        ("微型標普均值回歸", "MES", "mean_reversion/futures_mes/development_report.json"),
        ("那斯達克均值回歸", "NQ", "nq/development_report.json"),
        ("微型標普趨勢與動量", "MES", "mean_reversion/futures_mes_momentum/development_report.json"),
        ("那斯達克趨勢與動量", "NQ", "nq_momentum/development_report.json"),
        ("微型標普雙向趨勢", "MES", "mean_reversion/futures_mes_directional/development_report.json"),
        ("那斯達克雙向趨勢", "NQ", "nq_directional/development_report.json"),
    ]
    futures_final_untouched=True
    for name,symbol,path in future_definitions:
        if not (BASE/path).exists(): continue
        report=load(path); candidates=rows(report)
        if not candidates: raise ValueError("Empty futures report")
        future_rows=[]
        operating=[row for row in candidates if row.get("cost_profile") in
                   ("flat2_operating_assumption","operating_fixed_5_per_side")]
        for row in operating or candidates:
            runs=row["runs"]
            dev=runs["development"]["engine_summary"]
            val=runs["validation"]["engine_summary"]
            natural=dev["eligible_trades"]+val["eligible_trades"]
            net=dev["natural_net_profit"]+val["natural_net_profit"]
            wins=dev["wins"]+val["wins"]
            future_rows.append((natural,dict(name=row["config"]["name"],trade_count=natural,
                win_rate=wins/natural if natural else 0,net_profit=net,currency="USD",
                split="開發＋選擇驗證（同一策略）",initial_equity=dev["initial_equity"],
                explanation=("交易最多的單一配置診斷，非選定策略；"+
                             (f"每口每側USD{'2' if symbol=='MES' else '5'}假設費用；" if operating else "原比例費用假設；")+
                             "期貨資料、費用及風險模型尚有未驗證限制。"),
                cost_profile=row.get("cost_profile","conservative_bps_proxy"))))
        eligible=sum(bool(row.get("financial_eligible",row.get("passes_financial_criteria",False))) for row in candidates)
        families.append(dict(name=name,symbol=symbol,timeframes=["5m"],trials=len(candidates),
            source_evaluations=len(candidates),status="候選待保留期驗證" if eligible else "未通過",
            diagnostic=max(future_rows,key=lambda item:item[0])[1],report_paths=[path],
            note="費用情境分開計数；同一策略交易不重複合計。原生5分鐘供應商成交資料，非已驗證買賣報價或合約轉倉證明。"))
        source_count+=len(candidates); evidence.append(path)
        futures_final_untouched &= str(report.get("final", "")).startswith("UNTOUCHED")
    provenance=json.loads((ROOT/"data/intraday/dukascopy_eurusd_bid_development_2015_2021_provenance.json").read_text())
    fxcm_sources=[]
    for symbol,label in (("eurusd","fixed_session_development_validation_2015_2021"),
                         ("gbpusd","development_validation_2017_2021"),("nzdusd","development_validation_2017_2021")):
        path=ROOT/f"data/intraday/fxcm_official/{symbol}_{label}_provenance.json"
        if path.exists():fxcm_sources.append((path,json.loads(path.read_text())))
    result=dict(updated_at=datetime.now(timezone.utc).isoformat(),status="no_edge_validated_source" if fxcm_sources else "no_edge_blocked_source",
                label="短週期策略尚未通過驗證",
                reason=("已取得FXCM多年度官方雙側分鐘報價，完成止損／獲利模式篩選、出場調整及跨標的驗證。尚未找到同時滿足至少500筆、淨勝率50%與扣成本獲利的已驗證策略；模擬入場保持關閉。" if fxcm_sources else "已完成多組真實5／15分鐘回測，尚未找到同時滿足至少500筆、淨勝率50%與扣成本獲利的已驗證策略。實際買賣報價確認仍缺完整年度資料。"),
                periods=dict(development="外匯2015–2017（部分至2019）；期貨2026-01-21至02-13",
                             validation="外匯2018–2021（部分2020–2021）；期貨2026-02-16至02-27",
                             final="外匯2022-04-01至2024-09-30；期貨2026年4月完整交易日；均尚未評估"),
                parameter_variant_count=sum(f["trials"] for f in families),source_evaluation_count=source_count,
                diagnostic_evaluation_count=29,untuned_control_count=30,
                count_note="策略／標的／週期／資金／費用情境組合計一次；相同組合的不同來源確認另計。期貨費用情境分開計數，修復後重跑不重複當作新參數。交易筆數與試驗數分開。",
                legacy_trial_count=608,final_untouched=futures_final_untouched and new_final_untouched,selected=None,paper_entry_allowed=False,
                families=families,sources=dict(provider="Dukascopy 官方1分鐘歷史檔，逐筆檢查後完整聚合；另有明確標示時區未知的鏡像研究",
                    quote_side="BID；實際ASK資料目前只有2015年完整",time_zone="官方資料UTC；未知鏡像禁止命名時段研究",
                    bid_m5_bars=provenance["aggregate_outputs"]["M5"]["rows"],
                    bid_m15_bars=provenance["aggregate_outputs"]["M15"]["rows"],
                    ask_status="2015完整，2016–2021不足；未補造價差。獨立公開FXCM鏡像有OHLC錯誤，未用於驗證。",
                    futures_status="MES／NQ原生M5供應商樣本；2026年1–2月選擇，4月保留。原生合約身分及實際買賣報價未獲完整證明。"),
                report_url="https://github.com/lijingchiu/TradingAgent/blob/main/artifacts/intraday/README.md",
                evidence_sha256={p:hashlib.sha256((BASE/p).read_bytes()).hexdigest() for p in evidence})
    if fxcm_sources:
        result["sources"].update(provider="Dukascopy官方BID研究；新取得FXCM官方UTC M1雙側指示性報價（完整分鐘才聚合）",
            quote_side="Dukascopy BID；FXCM同時提供BID／ASK",
            ask_status="FXCM多年度歷史雙側報價已取得，交錯ASK禁止入場、缺漏不補造。供應商說明為Active Trader最低價差的指示性資料，非一般帳戶可成交證明；舊FXCM鏡像OHLC錯誤仍被排除。",
            fxcm_paired_m5_bars=sum(p["outputs"]["m5"]["quality"]["complete_bars"] for _,p in fxcm_sources),
            fxcm_paired_m15_bars=sum(p["outputs"]["m15"]["quality"]["complete_bars"] for _,p in fxcm_sources),
            fxcm_periods="EUR/USD 2015–2021；GBP/USD、NZD/USD 2017–2021，標的各自計數且不重複年度資料")
        result["source_provenance_sha256"]={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest() for path,_ in fxcm_sources}
    if (BASE/"stop_review.json").exists():
        result["stop_review"]=load("stop_review.json")
        result["evidence_sha256"]["stop_review.json"]=hashlib.sha256((BASE/"stop_review.json").read_bytes()).hexdigest()
    (BASE/"research_status.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    lines=["# 5／15 分鐘策略研究", "",result["reason"],"",
           f"本輪評估{result['parameter_variant_count']}組策略／標的／週期／資金／費用情境配置；{result['source_evaluation_count']}次來源組合評估、24次完整2015年實際報價診斷及5次其後的保守成本驗證另列。另保留30組固定基準。技術修復重跑不重複當成新參數。前輪608組小時線試驗保留，未當作本輪短週期證據。","",
           "| 策略家族 | 配置數 | 代表樣本交易數 | 淨勝率 | 扣成本淨損益 | 資料角色 | 結論 |",
           "|---|---:|---:|---:|---:|---|---|"]
    for f in families:
        d=f["diagnostic"] or {}
        amount=f'{d["net_profit"]:+,.2f} {d["currency"]}' if "net_profit" in d else "參見明細"
        win=f'{100*d["win_rate"]:.2f}%' if "win_rate" in d else "—"
        lines.append(f'| {f["name"]} | {f["trials"]} | {d.get("trade_count","—")} | {win} | {amount} | {d.get("split","開發期")} | {f["status"]} |')
    lines.extend(["", "表中的高勝率案例是診斷例，不能視為選定策略。不同策略的交易不能合併湊成500笔。自然平倉筆數排除資料終點強制平倉，帳戶淨損益仍包含其費用與盈虧。",
                  "", "[止損與獲利逐筆檢討](stop_review.md)：新取得FXCM官方多年度雙側M1資料；增加72組RSI2規則／資金配置與2次原固定時段策略來源確認，全部未通過。只用2017年學習止損模式，模型鎖定後才做2018–2021選擇驗證；另外保留2015–2017固定時段開發。不是將虧損成交事後刪除；完整成交重跑及失敗都已留存。",
                  "", "期貨使用固定版本TopstepX／ProjectX來源的原生MES／NQ M5成交OHLC，排除所有三月、已知短交易日及不完整時段，單一整口、當日平倉。開發18個Globex交易日、選擇驗證9日；均值回歸登記四月10日，新動量研究因UTC三月排除亦排除不完整四月1日，保留9個完整日。實际策略績效均未評估。初始資金MES500萬／NQ8,000萬美元是數值研究情境，並非模擬帳戶餘額。",
                  "", "期貨價格按成交OHLC加成本模型處理，沒有宣稱實際BBO：完整價差2ticks、每側1tick滑價、原0.35bps每側費用；另在評估前登記每口每側MES2美元／NQ5美元費用情境。固定費用要求交易量恰為一口，沒有免除成本；比例費用在MES可能低於固定2美元，不能一概稱為更嚴成本壓力。佣金方案、K線標記起止約定與初始原生合約身分仍未完整驗證，不能據此啟用模擬交易。",
                  "", "雙向期貨使用獨立真實價格引擎，依已完成趨勢決定多／空；正數口數與真實價格不反轉。單口抵押保留額≤初始與當前權益較小者0.8%，費用另外扣除，實際跳空損失不截斷。保守OHLC風險包絡量測單筆入場損失及浮盈高點回撤，超過1%後停止新入場。抵押額不是最大損失：做空、負價格與變動保證金的實際期貨損失界線尚未建立。",
                  "", "[另段保留資料方案](futures_additional_reserved_protocol.json)在雙向候選績效前登記2026年7–8月Yahoo原生M5快照；僅做來源品質檢查。每日午夜缺漏及零成交量排除後，276根完整交易日只剩MES0日／NQ1日，不能聲稱取得廣泛500筆保留證據；沒有補造K線，也未計算此段策略結果。",
                  "", "既有Dukascopy官方BID開發資料包含523,528根M5及174,523根M15。使用真實1分鐘UTC BID OHLC，排除休市空成交量區塊，要求完整連續5／15筆才聚合；不以小時線補造。另有FXCM官方配對報價：EUR/USD 2015–2021及GBP/USD、NZD/USD 2017–2021完整分鐘聚合，原始檔與K線依供應商個人使用限制留在本地；來源、時間、缺漏及SHA-256存於data/intraday/fxcm_official/*_provenance.json。",
                  "", "固定基線含2點完整價差、每側0.2點滑價、每側0.35bps佣金與最低0.10美元。較大模擬資金變體保持相同費率，處理0.8%全額投入限制下的最低費用負擔。USD/JPY以JPY50,000,000起始、0.01JPY一點及JPY10最低每側費用獨立對帳，沒有把日圓淨利當成美元。",
                  "", "實際報價模式於現有ASK開盤價加滑價買入、BID扣滑價賣出；無ASK或報價交錯時禁止新增部位，保留BID退出行情。BID毛利減實際價差、滑價及佣金必須等於帳戶淨利。原2015年259筆獲利診斷不構成500筆驗證，週區塊信賴區間仍跨零；新取得FXCM多年度資料後，以同一NY08／6小時／40點止損與目標確認，USD500,000情境2018–2021的993筆虧USD415.51，沒有驗證跨年份優勢。",
                  "", "[時鐘出場修復紀錄](execution_clock_repair_receipt.json)保留修正前77次時段研究及16組定價時點研究，修正缺漏行情跨出場時間的處理後重算同一配置；全部樣本交易數與損益相同，合格候選仍為零。修正不是新策略試驗，也未開啟最終資料。",
                  "", "訊號只使用已完成K線，下一根實際開盤入場；缺漏及週末不能延用過期訊號。相同K線觸及停損／目標採停損優先；不裁切跳空損失。現金全額持有外幣、本金≤進場權益0.8%，本金和最壞費用≤1%；另外量測單筆浮盈高點回撤與帳戶累計回撤。",
                  "", "2022-04-01至2024-09-30為最後保留區間。其資料品質已查核，策略績效尚未評估。必須先凍結合格配置，才能評估並揭露至少500筆的實際樣本與成本壓力結果。模擬帳戶的本金／成交不受研究盈虧影響，新增交易門檻保持關閉。",
                  "", "重現研究：[安裝與固定研究命令](../../research/README.md)。官方下載程式為scripts/download_intraday_data.py；大型公開原始檔未納入Git，來源版本／檔案hash與結果記錄保留。",
                  "", "[機器可讀彙總](research_status.json) · [研究方法與統計定義](../../research/intraday_protocol.md) · [公開監控面板](https://lijingchiu.github.io/TradingAgent/)", ""])
    (BASE/"README.md").write_text("\n".join(lines))
    print(json.dumps({k:result[k] for k in ("parameter_variant_count","source_evaluation_count","diagnostic_evaluation_count","selected","final_untouched")}))


if __name__=="__main__":build()
