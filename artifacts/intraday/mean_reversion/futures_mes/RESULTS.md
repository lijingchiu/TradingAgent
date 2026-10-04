# MES M5 independent research result

**Rejected: all 24 configurations lost money after modeled costs in both development and validation.** No configuration was frozen for final testing. April strategy outcomes remain untouched, and no paper orders are authorized.

The native-interval third-party TopstepX/ProjectX mirror contains 16,816 M5 and 5,606 M15 bars from January 20 to April 15, 2026. All 5,605 complete shared M15 buckets reconcile exactly to actual M5 OHLC and volume; the study uses native M5, not upsampling. Source QA found no duplicate, unsorted, invalid OHLC, off-quarter-tick or zero-volume bars. The tracked updater requests `MES.M26`, but the initial January/February backfill has no raw API receipt or per-row expiry identifier. It is a vendor MES claim, not independently proved native contract identity.

The preregistered family buys completed bullish candles after a six- or twelve-bar negative z-score dip, optionally above EMA96, with equal four-, six- or eight-point stop and target distances. Signals execute at the next observed five-minute open. Features reset for each split. The March calendar month is excluded for uncertain roll provenance. Known shortened Globex session dates February 16 and April 3 are excluded. Positions hold at most 12 bars and close each Globex session at the observed 16:50 New York quote using the completed 16:45 bar; both quotes and their 300-second adjacency were verified on all allowed 18 development and 9 validation sessions.

Paper capital is USD 5 million to fit one MES notional under the unchanged 0.8% principal-allocation cap. Numeric units are constrained to multiples of five, corresponding to whole contracts at the USD 5/point multiplier. Assumed costs are a two-tick spread, one-tick slippage per side and 0.35 basis points commission per side, minimum USD 0.10. Each modeled fill is on the actual 0.25-point price grid. The proportional fee is a conservative study proxy; an actual all-in brokerage/exchange fee schedule was not freshly verified. Historical last-trade candles are treated as a midpoint model, not an observed order book.

Development spans January 21–February 13; validation February 17–27; the reserved final is April 1–15. The user requirement is 500 total naturally closed backtest trades, not 500 mandatory final trades. Pre-final density was projected using 18/9/10 session counts without inspecting any April strategy outcomes. The maximum actual development-plus-validation natural count was **349**, projecting **478.26** for the complete declared study. This is below 500 and is a projection, not a claimed final count.

The highest-frequency configuration `mes_m5_w12_z1_none_stop4_target4` had:

| Split | Natural trades | Net win rate | Gross reference USD | Spread/slippage USD | Commission USD | Net USD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Development | 251 | 50.20% | +165.00 | 1,255.00 | 609.50 | -1,699.50 |
| Validation | 98 | 50.00% | +21.25 | 490.00 | 236.06 | -704.81 |

Its after-cost average development winner was USD 12.43 versus USD 26.13 average loser. Meeting a 50% winning proportion does not establish positive expectancy. The prespecified seven-session bootstrap is too short to produce a validation confidence claim from nine sessions; the report explicitly records that insufficiency.

Across all configurations, the maximum measured trade peak drawdown was **0.001575% of entry equity**, and there were zero observed 1% violations. Those measurements do not prove an unconditional futures variation-margin liability or peak-drawdown bound. The cash-currency ownership risk proof does not transfer automatically to futures. Production activation stays blocked regardless of these research measurements.

The independent audit tightened the closing-quote guard to require both signal and execution bars. The unchanged family reproduced all prior results exactly; the earlier report is preserved as `development_report_before_complete_exit_clock_guard.json`. Execution-integrity reruns are not additional parameter hypotheses. Thirteen synthetic signal/calendar/integrity checks pass, including future-prefix invariance, missing scheduled-signal rejection, DST-aware session masks and a development entrypoint that refuses final evaluation.

All candidate results follow. Each natural count excludes sample-end liquidation; this dataset produced none in either split.

| Configuration | Dev trades | Dev net wins | Dev net USD | Val trades | Val net wins | Val net USD |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| mes_m5_w6_z1_none_stop4_target4 | 122 | 49.18% | -851.87 | 48 | 39.58% | -526.89 |
| mes_m5_w6_z1_none_stop6_target6 | 117 | 45.30% | -802.15 | 47 | 34.04% | -745.72 |
| mes_m5_w6_z1_none_stop8_target8 | 114 | 42.11% | -904.86 | 46 | 39.13% | -644.57 |
| mes_m5_w6_z1_above_ema96_stop4_target4 | 54 | 51.85% | -276.85 | 22 | 31.82% | -290.56 |
| mes_m5_w6_z1_above_ema96_stop6_target6 | 51 | 49.02% | -128.25 | 22 | 27.27% | -406.80 |
| mes_m5_w6_z1_above_ema96_stop8_target8 | 50 | 44.00% | -87.05 | 22 | 31.82% | -416.80 |
| mes_m5_w6_z1.5_none_stop4_target4 | 1 | 0.00% | -27.42 | 1 | 0.00% | -27.42 |
| mes_m5_w6_z1.5_none_stop6_target6 | 1 | 0.00% | -37.42 | 1 | 0.00% | -37.42 |
| mes_m5_w6_z1.5_none_stop8_target8 | 1 | 0.00% | -47.42 | 1 | 0.00% | -47.42 |
| mes_m5_w6_z1.5_above_ema96_stop4_target4 | 1 | 0.00% | -27.42 | 1 | 0.00% | -27.42 |
| mes_m5_w6_z1.5_above_ema96_stop6_target6 | 1 | 0.00% | -37.42 | 1 | 0.00% | -37.42 |
| mes_m5_w6_z1.5_above_ema96_stop8_target8 | 1 | 0.00% | -47.42 | 1 | 0.00% | -47.42 |
| mes_m5_w12_z1_none_stop4_target4 | 251 | 50.20% | -1699.50 | 98 | 50.00% | -704.81 |
| mes_m5_w12_z1_none_stop6_target6 | 227 | 46.26% | -1863.60 | 92 | 44.57% | -889.10 |
| mes_m5_w12_z1_none_stop8_target8 | 212 | 42.92% | -2225.91 | 85 | 44.71% | -913.52 |
| mes_m5_w12_z1_above_ema96_stop4_target4 | 72 | 54.17% | -361.86 | 31 | 41.94% | -329.78 |
| mes_m5_w12_z1_above_ema96_stop6_target6 | 67 | 46.27% | -554.66 | 28 | 39.29% | -398.78 |
| mes_m5_w12_z1_above_ema96_stop8_target8 | 60 | 41.67% | -556.32 | 26 | 42.31% | -383.96 |
| mes_m5_w12_z1.5_none_stop4_target4 | 77 | 53.25% | -420.71 | 25 | 52.00% | -165.25 |
| mes_m5_w12_z1.5_none_stop6_target6 | 76 | 47.37% | -499.52 | 24 | 37.50% | -315.33 |
| mes_m5_w12_z1.5_none_stop8_target8 | 74 | 40.54% | -678.41 | 24 | 41.67% | -269.08 |
| mes_m5_w12_z1.5_above_ema96_stop4_target4 | 25 | 56.00% | -84.72 | 9 | 44.44% | -86.70 |
| mes_m5_w12_z1.5_above_ema96_stop6_target6 | 25 | 48.00% | -105.97 | 8 | 37.50% | -136.78 |
| mes_m5_w12_z1.5_above_ema96_stop8_target8 | 24 | 37.50% | -107.27 | 8 | 50.00% | -90.53 |

Reproduce development and validation with:

```sh
PYTHONPATH=/workspace/analysis-deps python -m research.intraday_mean_reversion.futures_mes --develop
```

Inspect `preregistration.json`, `source_quality_receipt.json` and `development_report.json` for pinned source and code hashes, complete trades, all costs, expectancy decomposition and confidence limitations. The source, contract identity and short independent interval prevent a verified profitable-futures claim. No final sample was spent to force a trade count or an apparent success.
