# MES M5 directional development and validation

All 24 fixed directional configurations failed in both fee profiles (48 strategy-cost variants). No configuration had positive net profit in either chronological split. No candidate was frozen, and the April reserved final strategy features, counts and outcomes remain **UNTOUCHED**. Paper activation is blocked.

The preregistered single rule can trade both directions; it preserves actual source quote levels, a positive $5 contract multiplier, exactly one MES contract, and signed P&L. Entries use only the previous completed, natively adjacent 5-minute bar. Features reset at source gaps and split boundaries. The dataset supplies 18 development and 9 validation complete 276-bar Globex sessions. Both UTC March and March session dates are excluded, including warmup; April 1 is excluded as an incomplete eligible session. All positions close by the verified adjacent 16:40 signal / 16:45 quote pair.

Initial virtual capital is $5,000,000 to fit one contract within the fixed 0.8% notional allocation. The operating assumption charges $2 per contract per side, a full two-tick spread, and one tick slippage per side. The original 0.35-bps profile is separately reported as fee sensitivity; it is cheaper than the $2 profile at these quote levels and is not a higher-cost stress. Both profiles are unverified simulation charges.

## Highest natural trade count with one unchanged configuration

`mes_directional_h6_ema48_momentum_stop8_target8` produced 936 actual natural trades. This achieves the user's literal 500-trade count but fails the profitability and win-rate requirements. Trades from different strategies or fee profiles were not pooled.

| Split | Natural trades | Net wins | Source quote gross | Spread + slippage | Fees | Net profit | Long / short |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| development | 656 | 46.04% | $-818.75 | $3,280.00 | $2,624.00 | $-6,722.75 | 309 / 347 |
| validation | 280 | 41.07% | $-862.50 | $1,400.00 | $1,120.00 | $-3,382.50 | 150 / 130 |

The least-negative minimum split mean was `mes_directional_h6_ema48_pullback_stop12_target12`; it also lost in both splits. Its development/validation natural means were $-9.1905 / $-8.8543 per trade. These are diagnostic results, not a selected trading strategy.

## Evidence and limitations

No observed 1% per-trade adverse-loss or conservative peak-drawdown breach occurred. This is a measurement of the supplied sample, not a proof that futures losses are bounded. Short futures prices can rise without bound; negative prices, variation margin, outages and gaps also prevent treating futures collateral as cash ownership. No production or paper-trading authorization is implied.

The public pinned source is a third-party TopstepX/ProjectX root-symbol CSV containing LAST_TRADE OHLCV, modeled as a midpoint proxy. The source does not establish exchange-native contract identity through the historical backfill, roll cleanliness, or executable BID/ASK quotes. The native M5/M15 source consistency checks and literal March exclusion mitigate some concerns but do not resolve these limitations.

Independent audit passed the new genuine directional engine/statistics before source-strategy P&L. The enforced preregistration hashes freeze the source, strategy, engine, statistics, shared calendar helpers and joint protocols. Synthetic feature, cash, fee, native-causality and daily-flat tests passed. Every signed quote/fill/cost/net row reconciles.

Daily realized-return confidence uses a 7-calendar-day moving-block bootstrap, including inactive days. The validation period contains fewer than 14 calendar observations and is explicitly marked insufficient for that confidence calculation. Short coverage and repeated family selection further limit any inference; this failed family cannot establish positive expectancy.

Full candidate and raw trade ledgers are in `development_report.json`; `candidate_split_summary.csv` contains all 96 split summaries. `preregistration.json`, `source_quality_receipt.json`, and `engine_audit_readiness_receipt.json` preserve the pre-outcome evidence. Earlier research reports and receipts remain unchanged.
