# Intraday EUR/USD research protocol

This is a new M5/M15 research round. It must not overwrite the previous
`artifacts/holdout_evaluation_receipt.json`, selected strategy, trial history,
or negative results. The earlier round tested 608 pair/timeframe/parameter
combinations; its EUR/USD final observations and warmup from October 2024
onward are already seen. They are not an untouched test for this round.

## Data separation, before selecting a strategy

| Role | Interval | Permitted use |
|---|---|---|
| Development | Available history through 2017-12-31 | Design features, strategy family, cost assumptions and parameters |
| Selection validation | 2018-01-01 through the available mirror's March 2022 endpoint | Rank the declared candidates; report that these dates were used previously |
| Reserved final test | 2022-04-01 00:00 UTC to 2024-10-01 00:00 UTC, end exclusive | Evaluate one frozen winner exactly once |
| Already seen recent observations | 2024-10-01 onward | Later monitoring or explicitly labeled diagnostic replay; never a new final test |

Use the mirror only for chronological research until its source, price side,
scaling and timezone are verified. A naive mirror timestamp is not evidence
of UTC. Do not apply a UTC/NY/London session filter to that source. If a strategy
needs clock time, obtain authoritative UTC development and validation data
before selection; never invent a timezone conversion. Reserve authoritative
UTC EUR/USD data, such as the original provider's Dukascopy observations, for
the new final interval. Bid OHLC is not mid OHLC: convert using synchronized
bid and ask, or execute with the correct side-specific cost model.

Downloading final prices, checking checksums, timestamps, side conventions,
OHLC validity, duplicates, missingness and coverage is permitted before
freezing. No candidate P&L, signal hit rate, optimized trading hours or visual
strategy inspection of that interval is permitted before freezing. If a
participant already evaluates strategy outcomes there, disclose it and reserve
a different interval; renaming a file does not restore independence.

Keep missing bars missing. Construct M15 from consecutive M5 observations
only when all three component bars exist; otherwise omit that M15 block.
Completed bars end no later than the observation time. Do not synthesize
weekend bars or fill prices across market gaps. Report coverage and exclusions.

## Freeze record

Before the first final strategy evaluation, save a separate machine-readable
intraday preregistration and immutable selection record containing:

- Exact source URLs/provider, repository revision when relevant, raw and cleaned
  file SHA-256 hashes, timestamp timezone, price side, conversion rule and data
  exclusions; calendar bounds and warmup bounds for all three splits.
- Every declared candidate, its M5/M15 interval and complete parameters;
  all development/validation attempts including rejected families. Persist the
  candidate list before their evaluation, not after selecting a winner.
- Indicator warmup, one-position rule, entry timing, maximum holding time,
  minimum units, exit priority, gap handling and sample-end liquidation rule.
- Baseline spread, each-side slippage, commission, minimum commission, any
  financing, position-sizing limits and the exact stress scenarios.
- Selection ranking and tie-breaker, selected parameters, software commit/hash,
  initial account capital and the statistics/bootstrap settings below.

Rank candidates using development and selection-validation results only, with
positive after-cost net P&L, net win rate at least 50% and zero risk violations
in both splits. Prefer the maximum of the minimum development/validation net
return; use validation net return and a stable candidate name as tie-breakers.
Log the precise rule used rather than changing it after final results arrive.
Freeze the winner before inspecting final outcomes. Evaluate baseline plus
predeclared stress costs for that same winner; never select a different winner
using final or stress-final results. Record a failed final honestly and leave
the paper-entry gate closed. A rerun is allowed only to reproduce the same
frozen config/data/code, or to repair a documented engine/data defect; a repair
and its effect on independence must remain visible in the receipt.

## Execution and costs

Signals use only completed bars. Enter at the first subsequent available
bar open/observed quote, not the signal bar's known close. At most one position
may be open. Do not close and reopen within the same signal interval. Opening
gaps fill at observed prices. If stop and target both appear inside an OHLC
bar with unknown ordering, use the stop first. Do not truncate losses to 1%.
Use the same signal, sizing and exit functions in backtest and paper execution.
Report that a periodically sampled paper quote can miss an intrabar exit;
OHLC simulation alone does not validate that different sampling process.

Retain the account's fully funded, long-only EUR conversion model if it remains
the execution model: no borrowing, shorts, leveraged FX contracts or real
broker orders. Recompute units against actual entry equity and entry price.
The entire principal plus worst-case liquidation costs must fit within 1%
of entry equity, with principal exposure capped at 0.8%. Stops are operational
exit rules, not a mathematical guarantee of their fill prices.

Measure both adverse excursion from entry equity and peak-to-trough drawdown
while the position is open. Check both against the requested 1% threshold in
observed backtest and paper records; do not confuse a proven bound on original
funded principal loss with a guarantee on all possible drawdowns of floating
gains. Preserve the raw breach and halt entries on an observed violation.

Use actual price side and fees consistently. Show mid-price gross P&L,
spread/slippage friction, explicit commissions/carry and final net P&L
separately. In the existing engine `gross_pnl` already uses friction-adjusted
fills, so it must not be labeled gross P&L before spread/slippage. Never debit
spread twice. Stress the frozen strategy at 1.5x and 2x baseline transaction
costs and disclose both results. Include measured provider spread variation
when available; a cost assumption is not an executable broker quote.

## Evidence and acceptance

The user's minimum is 500 closed trades in the tested strategy, a net winning
trade proportion of at least 50%, positive profit after fees and commissions,
and compliance with the 1% rule. Report development, validation and final
natural-close counts separately. Our preferred final evidence target is 500
natural closes in the reserved final interval; do not describe 500 pooled
training/validation trades as 500 independent final trades. If final has fewer
than 500, say so explicitly even if 500 total satisfies the literal count.

Exclude artificial `sample_end` liquidations from the natural-close win rate,
payoff and count, but include their fees/P&L in total account profitability.
For natural closes report positive, negative and exactly zero net P&L counts,
average net winner, average absolute net loser, net payoff ratio, net profit
factor and the per-trade decomposition:

`mean net P&L = winning fraction * mean winner - losing fraction * mean loser`.

The losing fraction is not automatically `1 - winning fraction` when breakeven
trades exist. Win rate alone does not establish positive expectancy. Show
Wilson's 95% interval for the observed net win rate, labeled as ignoring serial
dependence. Include every actual cost and a full cash/equity reconciliation.

For dependence-aware evidence, form UTC daily realized account returns from
all final exits, with zero-P&L calendar days retained. A daily return uses the
previous day's realized equity as its denominator. This is realized-return
evidence; do not label it intraday marked-to-market equity risk. Use a circular
moving-block bootstrap with 7-calendar-day blocks, 10,000 replications and
fixed seed 20261004. Report the mean daily return and both the one-sided 95%
lower confidence bound and two-sided 95% interval. Prespecified 14- and 28-day
blocks are sensitivity diagnostics; do not choose the block giving the nicest
bound. Weekly clustering retains adjacent winning/losing sessions and the
inactive-day pattern more honestly than independently shuffling trades.

Positive sample net profit meets the profitability observation; a positive
bootstrap lower bound supplies stronger evidence of positive expected return.
If the bound includes zero, say the sample was profitable but the estimated
edge remains uncertain. This diagnostic is not an additional user instruction
and must not conceal whether the user's explicit criteria passed. Bootstrap
intervals still cannot eliminate structural change, provider artifacts,
parameter-selection bias or future execution costs. Disclose the cumulative
number of trials and keep the final selection independent.

Only enable new paper entries for a frozen, qualified strategy and preserve
the separate paper ledger. Research profits never enter the paper account.
Use the same frozen parameters thereafter; changes require a new version and
new disclosed validation. The monitoring panel must identify research results,
paper fills, observed breaches and data freshness separately.
