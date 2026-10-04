# Direct UTC development and validation

No candidate passes the preregistered development and validation profit gate. No untouched holdout outcomes have been evaluated.

Costs: 2 pip complete spread, 0.2 pip slippage each side, 0.35 bps commission each side with $0.10 minimum. Initial equity $100,000; funded purchase cap 0.8% of entry equity; no leverage or ongoing carry. Signals use completed bars; entry must occur at the immediate next M15 opening with maximum signal age 900 seconds. Stop-first treatment resolves ambiguous intrabar stop/target order.

Development: 2015–2019; validation: 2020–2021. Natural trade counts and win rates exclude forced terminal sample-end exits. No development or validation trade count is represented as untouched final-test evidence.

Direct source: Dukascopy BID one-minute OHLC archives, aggregated to M15. The engine adds half the assumed fixed spread to model midpoints, then charges entry/exit fills consistently: buy at source bid plus full spread and slippage, sell at source bid less slippage. Actual ASK history was not downloaded.

| Symbol | Candidate | Dev trades | Dev net profit | Val trades | Val net win | Val net profit | Val net pips/trade | Positive months | Risk breaches |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| EURUSD | donchian12_trend192_t20_s25 | 1219 | $-542.22 | 491 | 52.14% | $-215.44 | -6.40 | 3/24 | 0 |
| EURUSD | donchian24_trend192_t30_s35 | 781 | $-362.86 | 290 | 52.41% | $-120.22 | -6.15 | 5/24 | 0 |
| EURUSD | expansion4_trend192_t20_s25 | 1290 | $-518.35 | 509 | 54.42% | $-185.45 | -5.32 | 3/24 | 0 |
| EURUSD | expansion8_trend192_t30_s35 | 831 | $-383.16 | 308 | 53.90% | $-107.00 | -5.11 | 5/24 | 0 |
| EURUSD | ema_pullback20_trend192_t20_s25 | 1389 | $-514.15 | 521 | 57.97% | $-134.90 | -3.85 | 5/24 | 0 |
| EURUSD | ema_pullback32_trend192_t30_s35 | 846 | $-297.64 | 300 | 60.00% | $-24.97 | -1.29 | 11/24 | 0 |
| EURUSD | reversal4_trend192_t20_s25 | 1411 | $-507.60 | 527 | 56.17% | $-167.10 | -4.64 | 4/24 | 0 |
| EURUSD | reversal8_trend192_t30_s35 | 1010 | $-380.50 | 357 | 55.74% | $-86.65 | -3.60 | 7/24 | 0 |

Closest direct-source candidate: EMA32 pullback, 30 pip target / 35 pip stop. Validation: 300 natural trades, 60.00% net wins, net loss $24.97, -1.286 net pips per trade. Development: 846 natural trades and net loss $297.64. It is rejected.

Some other validation cases exceed 500 trades and 50% win rate but lose after fees. Every direct-source candidate also has negative development profit, so none justifies consuming untouched 2022–2024 holdout evidence.
