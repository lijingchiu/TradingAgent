# USD/JPY M15 research (JPY account)

The pinned public mirror contains actual M15 records. Original broker,
executable quote side and timestamp timezone remain unverified, so this family
uses no UTC/session/hour filters. Raw publisher points are divided by 1,000;
the 2015–2021 research quotes range from 99.586 to 125.767 JPY per USD. The
scaling assumption and raw/normalized hashes are saved in
`artifacts/intraday/jpy/source_provenance.json`.

A JPY 50,000,000 virtual cash account pays for integer USD currency units in
full. Its funding cap is JPY 400,000 at initial entry (0.8% of JPY equity),
not USD 400,000. Every principal, fee, realized PnL and drawdown amount is in
JPY. One USD/JPY pip is JPY 0.01 per USD; modeled full spread is 2 pips,
each-side slippage 0.2 pips, each-side commission 0.35 bps with JPY 10 minimum.
The complete worst-case funded loss must fit below 1% of entry JPY equity;
observed peak-to-trough trade drawdown is checked separately.

Before inspecting family outcomes, `preregistration.json` declared 24 of the
same multiday bullish-regime/deep-RSI2-dip/completed-rebound configurations used
in the separate EUR/USD hypothesis. Barriers and costs are converted using
JPY pip units. No parameters were tuned using USD/JPY validation results.
Six untuned always-long controls use the same exit policies. Development is
2015–2017 and selection validation is 2018–2021. All 2022 price observations
are filtered before any feature or outcome evaluation.

Every declared candidate produced negative development and validation net
PnL. For dip10/rebound20/target20/stop80, development had 535 natural trades
and 78.69% net winners, yet lost JPY 50,671. Validation had 487 natural trades,
67.76% net winners and lost JPY 90,790: its average winner was JPY 605, versus
average absolute loser JPY 1,849. Win rate alone did not supply positive
expectancy. All 24 candidate and 6 baseline cashledgers and natural payoff
reconciliations passed, with no observed funded-loss or peak-drawdown violations.

No strategy qualified, no final outcomes were evaluated, and no production or
paper account was changed. Authentic USD/JPY quote-side/timezone data was not
requested after this negative provisional screen.

Reproduce from the repository root:

```bash
PYTHONPATH=/workspace/analysis-deps:/workspace/TradingAgent \
NUMBA_NUM_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
python -m research.intraday_jpy.run_research
```
