# UTC local-flow continuation — fixed 2 pip stress

All 18 configurations were declared before evaluation. No configuration meets positive net profit and net win rate at least 50% in both splits. No final untouched period has been evaluated.

Native M15 Dukascopy BID data; exact local 08:00 London / New York entry with IANA daylight saving rules. Fully paid long positions, $500,000 virtual starting equity, 0.8% entire purchase cap, 2 pip full spread, 0.2 pip slippage each side and 0.35 bps / minimum $0.10 commission each side. Stop and target both 80 pips. Clock holds 4, 6, or 8 hours; entries require a fresh immediate prior M15 candle.

| Candidate | Dev trades | Dev net win | Dev profit | Val trades | Val net win | Val profit | Val net pips/trade | Val positive months |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| london08_unconditional_hold4h_s80_t80 | 778 | 42.29% | $-1478.95 | 1038 | 42.49% | $-1334.55 | -3.728 | 8/48 |
| london08_unconditional_hold6h_s80_t80 | 778 | 43.96% | $-1576.35 | 1038 | 44.51% | $-1245.02 | -3.486 | 14/48 |
| london08_unconditional_hold8h_s80_t80 | 778 | 44.47% | $-1425.39 | 1038 | 44.99% | $-1623.90 | -4.598 | 12/48 |
| london08_up_1h_hold4h_s80_t80 | 380 | 42.89% | $-749.12 | 474 | 41.14% | $-670.18 | -4.089 | 9/48 |
| london08_up_1h_hold6h_s80_t80 | 380 | 45.53% | $-781.85 | 474 | 45.78% | $-617.64 | -3.768 | 15/48 |
| london08_up_1h_hold8h_s80_t80 | 380 | 44.47% | $-666.80 | 474 | 44.73% | $-915.99 | -5.649 | 16/48 |
| london08_up_6h_hold4h_s80_t80 | 414 | 42.75% | $-817.63 | 493 | 42.80% | $-724.42 | -4.292 | 15/48 |
| london08_up_6h_hold6h_s80_t80 | 414 | 43.72% | $-988.71 | 493 | 45.64% | $-723.42 | -4.302 | 15/48 |
| london08_up_6h_hold8h_s80_t80 | 414 | 43.96% | $-952.39 | 493 | 43.61% | $-1095.61 | -6.562 | 13/48 |
| new_york08_unconditional_hold4h_s80_t80 | 778 | 50.00% | $-334.77 | 1038 | 43.83% | $-1230.04 | -3.500 | 9/48 |
| new_york08_unconditional_hold6h_s80_t80 | 778 | 49.23% | $-104.11 | 1038 | 44.70% | $-1158.64 | -3.287 | 13/48 |
| new_york08_unconditional_hold8h_s80_t80 | 778 | 49.61% | $176.89 | 1038 | 44.22% | $-1082.38 | -3.088 | 14/48 |
| new_york08_up_1h_hold4h_s80_t80 | 345 | 48.41% | $-370.33 | 484 | 41.74% | $-662.61 | -3.978 | 13/48 |
| new_york08_up_1h_hold6h_s80_t80 | 345 | 48.99% | $-174.76 | 484 | 43.80% | $-536.30 | -3.197 | 16/48 |
| new_york08_up_1h_hold8h_s80_t80 | 345 | 47.83% | $-106.78 | 484 | 43.39% | $-471.96 | -2.811 | 19/48 |
| new_york08_up_6h_hold4h_s80_t80 | 360 | 50.00% | $-236.17 | 486 | 42.18% | $-690.69 | -4.126 | 12/48 |
| new_york08_up_6h_hold6h_s80_t80 | 360 | 50.00% | $-24.45 | 486 | 43.21% | $-626.75 | -3.732 | 12/48 |
| new_york08_up_6h_hold8h_s80_t80 | 360 | 48.33% | $29.26 | 486 | 43.42% | $-541.12 | -3.193 | 14/48 |

Development: 2015–2017. Validation: 2018–2021. Statistical uncertainty intervals and monthly stability are included in the JSON artifact as diagnostics, not extra user acceptance rules. Combined development/validation counts are not independent final-test counts.

The lowest validation shortfall is NY08 up-1h, hold-8h: -2.811 net pips/trade, 484 trades, 43.39% net wins. Merely replacing a fixed 2 pip spread with smaller observed positive spread appears insufficient to eliminate that shortfall; observed ASK source confirmation remains a separately preregistered unchanged-config protocol.

This $500,000 virtual capital assumption is specific to this new family and does not change the existing production account or the rejected generic breakout artifacts.
