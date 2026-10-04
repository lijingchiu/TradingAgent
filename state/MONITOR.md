# TradingAgent 模擬交易監控

**回測未通過・禁止下單**

No candidate passed development and validation requirements；Final holdout has fewer than 30 naturally closed trades

更新時間：2026-10-04T12:37:51.697713+00:00（UTC；台灣時間 +8 小時）。每小時自動更新；重新整理本頁可查看最新紀錄。

> 本頁只顯示模擬交易。回測獲利不會加入模擬帳戶。

| 模擬帳戶 | 數值 |
|---|---:|
| 初始資金 | $100,000.00 USD |
| 目前權益 | $100,000.00 USD |
| 現金 | $100,000.00 USD |
| 已實現損益 | $0.00 USD |
| 未實現損益 | $0.00 USD |
| 已平倉模擬交易 | 0 |

## 策略與驗證

策略：`rsi5_ema100_stop2_target1`；EUR/USD，4h。

完整搜尋紀錄：608 組策略／標的／週期試驗。最終資料不參與挑選策略。

| 獨立驗證 | 結果 |
|---|---:|
| 自然平倉交易數 | 25 |
| 扣成本後淨利 | $8.62 USD |
| 勝率 | 76.00% |
| 允許新增模擬部位 | 否 |

## 風控

每筆入場投入本金上限為當時帳戶權益的 0.8%，加上最壞交易費用必须低於 1%。只持有已全額付款的 EUR，不借款、不放空；EUR 即使完全貶值也不超過單筆入場資金預算。這不是槓桿期貨或 CFD。

1% 限制以入場資金為基準；累積帳戶回撤與浮盈高點回撤另計，不能混為同一個保證。

成本模型：2 pip 完整買賣價差、每邊 0.2 pip 滑價、每邊 0.35 bps 佣金（最低 US$0.10）。全額付款的貨幣持有不計借款融資費。

## 目前部位

沒有持倉。

## 最近模擬交易

| 入場 | 出場 | 數量 EUR | 淨損益 USD | 出場原因 |
|---|---|---:|---:|---|
| — | — | — | 尚未成交 | — |

## 資料與限制

- 自行建立的現金外匯模擬帳戶，沒有送單至真實券商。
- 排程每小時第 2 分鐘監控；GitHub 排程可能延遲。超出入場時窗就略過交易。
- 回測 OHLC 的盤中停損假設與模擬盤定時觀察有差異；模擬盤按實際取得的報價成交，不補造錯過的成交。
- 1% 是相對入場資金的損失上限；累積帳戶回撤及浮盈高點回撤另外揭露。
- Past profitability does not establish future profitability
- Validation was reused to develop cost-aware families; all 440 trials are disclosed
- Public FX observations are not independently authenticated executable quotes
- OHLC execution conservatively gives stop priority when both thresholds touch
- Win-rate confidence intervals ignore serial trade dependence
- Very small fully funded positions limit profits and absolute losses
- Realized and close-mark account drawdown can accumulate across separate trades
- Old mirror timezone and executable-price provenance are unknown; four-hour alignment is exploratory
- No candidate passed development and validation requirements
- Final holdout has fewer than 30 naturally closed trades

[完整 HTML 面板原始檔](../web/index.html) · [自動排程執行紀錄](https://github.com/lijingchiu/TradingAgent/actions/workflows/paper-trader.yml)
