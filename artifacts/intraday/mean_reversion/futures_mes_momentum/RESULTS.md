# MES M5 momentum research

**All 48 strategy/fee variants failed: every configuration lost money in both development and validation under both frozen fee profiles.** No candidate was selected for April. The final interval remains untouched and paper orders remain blocked.

The new family was frozen after the earlier MES z-score family was rejected. Its 24 configurations combine return horizons six/twenty-four bars, EMA48/192, momentum/pullback entry and fixed stop/target pairs 8/8, 8/12, 12/12 points. Both styles require the completed close above its rising EMA; momentum additionally requires a positive horizon return, while pullback requires a prior one-bar decline followed by a current recovery. No strategy parameter or cost was changed after these outcomes.

Features reset at each non-300-second gap. Completed signal availability is the native bar-start timestamp plus five minutes, accepted from 18:30 through 16:15 New York; fills use only the actual adjacent next-bar open. A completed 16:40 bar closes any position at the observed 16:45 quote. Both exact adjacent quotes and every expected native bar are required. Maximum hold is twelve bars. The new study uses complete Globex session-date intervals, including the January 20 evening prefix of January 21; it does not revise the previous rejected z-score results.

Only 18 complete development sessions (January 21–February 13, 4,968 bars) and nine validation sessions (February 17–27, 2,484 bars) were used. All raw UTC March and March Globex dates are excluded before feature construction. February 16 and April 3 are known shortened sessions. The April 1 session is excluded entirely because its March 31 UTC prefix conflicts with the literal March prohibition. Nine final sessions were predeclared for density projection, but no April indicators, strategy counts or outcomes were calculated. Required total count is 500 natural closes in the same strategy, without pooling different configurations or fee scenarios.

Capital stays USD 5 million, with exactly one whole MES contract: five numeric units at USD 5 per point. All fills stay on the 0.25-point grid. Both profiles assume two ticks full spread and one tick slippage per side, giving a 0.50-point modeled price offset per side. The original proportional fee is 0.35 basis points per side, minimum USD 0.10. The separately preregistered operating scenario charges exactly USD 2 per contract per side; exact one-contract and fee assertions are enforced. These are unverified simulation charges, not measured brokerage/exchange fees. Vendor LAST_TRADE OHLC is treated as a hypothetical midpoint for fills, not observed BBO.

The maximum actual development-plus-validation count is **466**. The maximum projection is **621.33**, using the frozen 36/27-session ratio; it is not an achieved count. The highest-frequency signal was `mes_momentum_h6_ema48_momentum_stop8_target8`:

| Fee scenario | Split | Natural trades | Net wins | Gross LAST_TRADE reference USD | Spread/slippage USD | Commission USD | Net USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| proportional_conservative | development | 314 | 46.82% | -388.75 | 1570.00 | 762.53 | -2721.28 |
| proportional_conservative | validation | 152 | 40.13% | -522.50 | 760.00 | 366.85 | -1649.35 |
| flat2_operating_assumption | development | 314 | 44.90% | -388.75 | 1570.00 | 1256.00 | -3214.75 |
| flat2_operating_assumption | validation | 152 | 40.13% | -522.50 | 760.00 | 608.00 | -1890.50 |

The highest-frequency original-fee configuration lost money even before spread/slippage and commission, so transaction-cost removal would not establish an edge there. All 48 complete ledgers reconcile LAST_TRADE gross minus modeled friction and explicit commissions to net PnL. Development includes inactive calendar days in its seven-calendar-day block-bootstrap diagnostics. Validation has fewer than the required fourteen calendar observations and explicitly reports insufficient blocks, rather than inventing a confidence bound.

There were no observed 1% entry-equity loss or peak-drawdown breaches. Maximum measured peak drawdown across the family was **0.002325% of entry equity**. The fully reserved numeric nonnegative-price model is not a proof of actual futures variation-margin liability or a universal drawdown guarantee. Historical native contract identity also remains unverified: the updater names MES.M26, but the initial backfill has no raw API/expiry receipts. These limits persist regardless of whether a research sample profits.

Eleven synthetic tests pass. Two independent reviews found no blockers and verified all 24 signal prefixes against future shocks, complete clocks, native-gap reset, Python/Numba 16:45 execution, one-contract sizing, exact flat fees and ledger reconciliation. The audit and preregistration record exact study, engine, calendar-protocol and data fingerprints. Final evaluation is refused by this development entrypoint.

| Configuration | Fee profile | Dev natural trades | Dev net wins | Dev net USD | Val natural trades | Val net wins | Val net USD |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mes_momentum_h6_ema48_momentum_stop8_target8 | proportional_conservative | 314 | 46.82% | -2721.28 | 152 | 40.13% | -1649.35 |
| mes_momentum_h6_ema48_momentum_stop8_target8 | flat2_operating_assumption | 314 | 44.90% | -3214.75 | 152 | 40.13% | -1890.50 |
| mes_momentum_h6_ema48_momentum_stop8_target12 | proportional_conservative | 265 | 41.51% | -1807.63 | 134 | 35.07% | -1620.88 |
| mes_momentum_h6_ema48_momentum_stop8_target12 | flat2_operating_assumption | 265 | 38.87% | -2223.75 | 134 | 33.58% | -1833.50 |
| mes_momentum_h6_ema48_momentum_stop12_target12 | proportional_conservative | 232 | 46.55% | -1423.97 | 118 | 41.53% | -1268.57 |
| mes_momentum_h6_ema48_momentum_stop12_target12 | flat2_operating_assumption | 232 | 43.10% | -1788.00 | 118 | 38.98% | -1455.75 |
| mes_momentum_h6_ema48_pullback_stop8_target8 | proportional_conservative | 231 | 46.32% | -1954.07 | 110 | 43.64% | -1053.06 |
| mes_momentum_h6_ema48_pullback_stop8_target8 | flat2_operating_assumption | 231 | 42.42% | -2316.50 | 110 | 40.91% | -1227.50 |
| mes_momentum_h6_ema48_pullback_stop8_target12 | proportional_conservative | 210 | 41.90% | -1610.64 | 102 | 40.20% | -932.50 |
| mes_momentum_h6_ema48_pullback_stop8_target12 | flat2_operating_assumption | 210 | 38.10% | -1940.00 | 102 | 37.25% | -1094.25 |
| mes_momentum_h6_ema48_pullback_stop12_target12 | proportional_conservative | 187 | 45.99% | -1452.47 | 93 | 43.01% | -842.11 |
| mes_momentum_h6_ema48_pullback_stop12_target12 | flat2_operating_assumption | 187 | 41.71% | -1745.50 | 93 | 39.78% | -989.50 |
| mes_momentum_h6_ema192_momentum_stop8_target8 | proportional_conservative | 102 | 47.06% | -869.09 | 52 | 40.38% | -563.10 |
| mes_momentum_h6_ema192_momentum_stop8_target8 | flat2_operating_assumption | 102 | 47.06% | -1029.25 | 52 | 40.38% | -645.50 |
| mes_momentum_h6_ema192_momentum_stop8_target12 | proportional_conservative | 85 | 41.18% | -611.51 | 46 | 36.96% | -419.87 |
| mes_momentum_h6_ema192_momentum_stop8_target12 | flat2_operating_assumption | 85 | 41.18% | -745.00 | 46 | 34.78% | -492.75 |
| mes_momentum_h6_ema192_momentum_stop12_target12 | proportional_conservative | 75 | 46.67% | -746.08 | 37 | 45.95% | -236.92 |
| mes_momentum_h6_ema192_momentum_stop12_target12 | flat2_operating_assumption | 75 | 45.33% | -863.75 | 37 | 43.24% | -295.50 |
| mes_momentum_h6_ema192_pullback_stop8_target8 | proportional_conservative | 84 | 38.10% | -1278.03 | 46 | 34.78% | -804.82 |
| mes_momentum_h6_ema192_pullback_stop8_target8 | flat2_operating_assumption | 84 | 35.71% | -1409.75 | 46 | 32.61% | -877.75 |
| mes_momentum_h6_ema192_pullback_stop8_target12 | proportional_conservative | 76 | 36.84% | -1031.12 | 42 | 30.95% | -713.91 |
| mes_momentum_h6_ema192_pullback_stop8_target12 | flat2_operating_assumption | 76 | 34.21% | -1150.25 | 42 | 28.57% | -780.50 |
| mes_momentum_h6_ema192_pullback_stop12_target12 | proportional_conservative | 64 | 43.75% | -745.77 | 34 | 38.24% | -423.41 |
| mes_momentum_h6_ema192_pullback_stop12_target12 | flat2_operating_assumption | 64 | 40.62% | -846.00 | 34 | 35.29% | -477.25 |
| mes_momentum_h24_ema48_momentum_stop8_target8 | proportional_conservative | 289 | 48.10% | -2075.91 | 124 | 40.32% | -1210.79 |
| mes_momentum_h24_ema48_momentum_stop8_target8 | flat2_operating_assumption | 289 | 46.37% | -2529.75 | 124 | 39.52% | -1407.25 |
| mes_momentum_h24_ema48_momentum_stop8_target12 | proportional_conservative | 238 | 43.28% | -1415.86 | 108 | 34.26% | -1035.84 |
| mes_momentum_h24_ema48_momentum_stop8_target12 | flat2_operating_assumption | 238 | 41.18% | -1789.50 | 108 | 33.33% | -1207.00 |
| mes_momentum_h24_ema48_momentum_stop12_target12 | proportional_conservative | 206 | 45.15% | -1182.06 | 92 | 38.04% | -934.77 |
| mes_momentum_h24_ema48_momentum_stop12_target12 | flat2_operating_assumption | 206 | 43.69% | -1505.25 | 92 | 36.96% | -1080.50 |
| mes_momentum_h24_ema48_pullback_stop8_target8 | proportional_conservative | 176 | 45.45% | -1407.90 | 90 | 40.00% | -1094.88 |
| mes_momentum_h24_ema48_pullback_stop8_target8 | flat2_operating_assumption | 176 | 43.18% | -1684.00 | 90 | 36.67% | -1237.50 |
| mes_momentum_h24_ema48_pullback_stop8_target12 | proportional_conservative | 156 | 41.03% | -1096.88 | 85 | 36.47% | -1124.04 |
| mes_momentum_h24_ema48_pullback_stop8_target12 | flat2_operating_assumption | 156 | 39.10% | -1341.50 | 85 | 34.12% | -1258.75 |
| mes_momentum_h24_ema48_pullback_stop12_target12 | proportional_conservative | 141 | 45.39% | -788.10 | 77 | 36.36% | -1217.29 |
| mes_momentum_h24_ema48_pullback_stop12_target12 | flat2_operating_assumption | 141 | 42.55% | -1009.00 | 77 | 33.77% | -1339.25 |
| mes_momentum_h24_ema192_momentum_stop8_target8 | proportional_conservative | 67 | 41.79% | -676.66 | 38 | 36.84% | -609.23 |
| mes_momentum_h24_ema192_momentum_stop8_target8 | flat2_operating_assumption | 67 | 41.79% | -781.75 | 38 | 34.21% | -669.50 |
| mes_momentum_h24_ema192_momentum_stop8_target12 | proportional_conservative | 54 | 35.19% | -630.11 | 35 | 34.29% | -489.49 |
| mes_momentum_h24_ema192_momentum_stop8_target12 | flat2_operating_assumption | 54 | 35.19% | -714.75 | 35 | 31.43% | -545.00 |
| mes_momentum_h24_ema192_momentum_stop12_target12 | proportional_conservative | 44 | 31.82% | -664.59 | 29 | 48.28% | -225.05 |
| mes_momentum_h24_ema192_momentum_stop12_target12 | flat2_operating_assumption | 44 | 31.82% | -733.50 | 29 | 44.83% | -271.00 |
| mes_momentum_h24_ema192_pullback_stop8_target8 | proportional_conservative | 53 | 28.30% | -1115.09 | 31 | 29.03% | -688.61 |
| mes_momentum_h24_ema192_pullback_stop8_target8 | flat2_operating_assumption | 53 | 26.42% | -1198.25 | 31 | 25.81% | -737.75 |
| mes_momentum_h24_ema192_pullback_stop8_target12 | proportional_conservative | 51 | 25.49% | -1084.01 | 30 | 26.67% | -638.69 |
| mes_momentum_h24_ema192_pullback_stop8_target12 | flat2_operating_assumption | 51 | 23.53% | -1164.00 | 30 | 23.33% | -686.25 |
| mes_momentum_h24_ema192_pullback_stop12_target12 | proportional_conservative | 41 | 31.71% | -761.05 | 23 | 39.13% | -316.85 |
| mes_momentum_h24_ema192_pullback_stop12_target12 | flat2_operating_assumption | 41 | 26.83% | -825.25 | 23 | 34.78% | -353.25 |

Reproduce the fixed development/validation experiment:

```sh
PYTHONPATH=/workspace/analysis-deps python -m research.intraday_mean_reversion.futures_mes_momentum --develop
```

Inspect `preregistration.json`, `source_quality_receipt.json`, `development_report.json` and `audit.md` for the complete evidence. The previous z-score family and all of its negative results remain preserved. No failed fallback was tested on April to force a count or claim a profit.
