# Independent pre-outcome MES momentum audit

Audit scope: `research/intraday_mean_reversion/futures_mes_momentum.py`, its 11 synthetic fixtures, the shared numeric execution engine, and the new preregistration. No strategy outcomes from source data, April, or the reserved FX final sample were evaluated. Existing failed-family receipts were not changed.

Result: no blocking implementation finding in the inspected version.

- The 24 registered configurations are the complete horizon 6/24 × EMA 48/192 × momentum/pullback × stop/target 8/8, 8/12, 12/12 family. Two declared fee profiles produce 48 operating variants. Source and joint-protocol hashes were verified; the current runner and shared-engine hashes match the preregistration.
- Features use current or earlier completed closes only. EMA, momentum, prior decline, and recovery features reset within each split and at every non-300-second gap. Independent future-suffix perturbations preserved every feature and signal prefix for all 24 configurations.
- A native bar-start timestamp becomes available 300 seconds later. The allowed completed-signal window and next-open execution window agree at New York 18:30 through 16:15. Stale signals cannot open positions after a missing quote.
- Source preparation selects Globex session dates, includes the first session's previous evening, and accepts only exactly 276 native five-minute observations from 18:00 through 16:55. Both UTC March rows and March Globex dates are excluded before features. The entire April 1 session is explicitly excluded because its March prefix is unavailable under that policy.
- The raw 16:40 exit signal executes at the observed 16:45 open. Both adjacent observations are required. Independent constant-price synthetic executions confirmed this exact exit under both Python and Numba, under each fee profile; the exit is natural rather than a sample-end liquidation.
- Units must equal 5 and numeric lots must equal 1, representing exactly one MES contract. The operating profile uses zero proportional commission and exactly USD 2 on each side. The conservative profile retains 0.35 bps per side with its USD 0.10 minimum. Both retain two ticks assumed full spread and one tick slippage per side. Synthetic fills, whole-contract assertions, and the gross-to-net ledger reconcile.
- The runner refuses a final split, writes no final strategy evaluation, and sets paper approval to false. Financial eligibility checks both natural and total net profits, net wins, and observed adverse excursion and peak drawdown in each prior split. The count projection uses the clarified 36 total / 27 prior eligible sessions.

Validation: all 11 committed synthetic tests passed, plus the independent probes above. Synthetic executions verify mechanics and are not profitability evidence.

Limits remain explicit: vendor contract identity and last-trade provenance are unverified; last-trade OHLC is modeled as an execution midpoint, not an observed bid/ask book. Both fee profiles are simulation assumptions. A projected count is not 500 completed historical trades. Calendar-block confidence must be reported as insufficient when fewer than 14 calendar observations are available. The fully paid numeric price-floor model and historical 1% measurements do not establish a futures variation-margin loss bound or permit paper/live activation.

Audited runner SHA-256: `c4771fcdfa2d561e10ca49635ed19b070b713b5953f9cfcdc4d2ee62050a3a2e`.

Audited shared-engine SHA-256: `4d39faa9ad51be2b166e9485786aad72c4e174a53973cfc1cc64cb3a2944b8de`.
