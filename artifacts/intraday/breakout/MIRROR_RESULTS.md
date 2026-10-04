# Mirror development and validation

No candidate passes the preregistered development and validation profit gate. No untouched holdout outcomes have been evaluated.

Costs: 2 pip complete spread, 0.2 pip slippage each side, 0.35 bps commission each side with $0.10 minimum. Initial equity $100,000; funded purchase cap 0.8% of entry equity; no leverage or ongoing carry. Signals use completed bars; entry must occur at the immediate next M15 opening with maximum signal age 900 seconds. Stop-first treatment resolves ambiguous intrabar stop/target order.

Development: 2015–2019; validation: 2020–2021. Natural trade counts and win rates exclude forced terminal sample-end exits. No development or validation trade count is represented as untouched final-test evidence.

Timestamp timezone and quote side are undocumented. These runs assume midpoint quotes, provide chronological research evidence, and do not claim a UTC session edge.

| Symbol | Candidate | Dev trades | Dev net profit | Val trades | Val net win | Val net profit | Val net pips/trade | Positive months | Risk breaches |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| EURUSD | donchian12_trend192_t20_s25 | 1210 | $-535.09 | 503 | 52.49% | $-215.63 | -6.31 | 3/24 | 0 |
| EURUSD | donchian24_trend192_t30_s35 | 777 | $-378.01 | 298 | 51.68% | $-133.59 | -6.61 | 4/24 | 0 |
| EURUSD | expansion4_trend192_t20_s25 | 1284 | $-549.64 | 515 | 54.95% | $-178.02 | -5.05 | 3/24 | 0 |
| EURUSD | expansion8_trend192_t30_s35 | 825 | $-389.35 | 314 | 52.55% | $-126.23 | -5.91 | 4/24 | 0 |
| EURUSD | ema_pullback20_trend192_t20_s25 | 1406 | $-526.27 | 525 | 58.29% | $-127.36 | -3.61 | 5/24 | 0 |
| EURUSD | ema_pullback32_trend192_t30_s35 | 850 | $-285.88 | 301 | 60.13% | $-14.77 | -0.81 | 13/24 | 0 |
| EURUSD | reversal4_trend192_t20_s25 | 1404 | $-513.01 | 539 | 56.59% | $-161.39 | -4.41 | 5/24 | 0 |
| EURUSD | reversal8_trend192_t30_s35 | 1001 | $-381.23 | 351 | 56.41% | $-77.42 | -3.29 | 9/24 | 0 |
| GBPUSD | donchian12_trend192_t20_s25 | 1233 | $-493.58 | 647 | 54.56% | $-238.90 | -6.18 | 1/24 | 0 |
| GBPUSD | donchian24_trend192_t30_s35 | 933 | $-312.66 | 446 | 55.61% | $-120.98 | -4.61 | 6/24 | 0 |
| GBPUSD | expansion4_trend192_t20_s25 | 1354 | $-548.56 | 688 | 54.36% | $-256.39 | -6.25 | 0/24 | 0 |
| GBPUSD | expansion8_trend192_t30_s35 | 1051 | $-319.99 | 479 | 53.03% | $-176.12 | -6.24 | 5/24 | 0 |
| GBPUSD | ema_pullback20_trend192_t20_s25 | 1573 | $-582.67 | 697 | 56.38% | $-220.93 | -5.36 | 3/24 | 0 |
| GBPUSD | ema_pullback32_trend192_t30_s35 | 1055 | $-347.66 | 448 | 54.24% | $-143.64 | -5.47 | 5/24 | 0 |
| GBPUSD | reversal4_trend192_t20_s25 | 1517 | $-620.54 | 695 | 52.23% | $-301.11 | -7.27 | 2/24 | 0 |
| GBPUSD | reversal8_trend192_t30_s35 | 1265 | $-530.32 | 546 | 52.38% | $-216.60 | -6.68 | 5/24 | 0 |
