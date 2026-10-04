# Cost-aware M15 model research

This bounded alternative is research only. It neither changes production
strategy selection nor sends orders. No prices after December 2021 are evaluated
by this runner. A profitable research candidate would still need a separately
frozen final evaluation, the user's 500-trade evidence, and a matching paper
implementation before enabling execution.

`artifacts/intraday/model/preregistration.json` was saved before candidate
outcomes. It declares two models, two symmetric pip barriers/holding horizons,
and three confidence thresholds: **12 model/barrier/threshold candidates per
symbol and data source**. Four untuned baseline configurations per source/symbol
are disclosed separately; these are not hidden selection attempts.

Training on 2015–2016 forecasts the 2017 development interval. A separately
refitted model trained on 2015–2017 forecasts the 2018–2021 validation interval.
The last 192 training observations are purged plus the next-open causal entry
bar; the first 192 evaluation observations are embargoed. All fitted labels remain inside
their training interval. A deterministic every-fourth-bar training sample
reduces overlapping labels, but does not make labels independent.

Features use completed price bars, return lags, volatility, ATR, candle shape,
normalized momentum and range location. They do not use hour, weekday, session,
future prices, or the next bar's open. Features are computed from raw BID data
when the source is BID. The shared engine's `quote_kind='bid'` prices an assumed
constant-spread conversion at BID + full spread + slippage on entry, and BID −
slippage on exit. Label price copies use the equivalent assumed mid offset,
including minimum commissions. This scenario does not claim synchronized ASK
observations or measured provider spreads. Unverified mirror data is explicitly
an indicative-mid assumption; its clock is used only for source-calendar order
and elapsed intervals, not UTC session filters.

Each candidate uses causal next-open entries, one fully paid long currency
position, actual modeled exit costs, stop-first OHLC ordering, maximum holding
bars and a five-calendar-day limit. Natural-close counts, net win rate and
expectancy are distinct from end-of-sample liquidation, which remains included
in the account ledger. Development and validation results include monthly,
yearly and source-calendar daily stability. Predicted confidence is a classifier
score, not a guaranteed or calibrated probability of profit.

Reproduction from the repository root:

```bash
PYTHONPATH=/workspace/analysis-deps:/workspace/TradingAgent \
NUMBA_NUM_THREADS=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 \
python -m research.intraday_model.run_research \
  --data data/intraday/mirror_eurusd_m15.csv --symbol EURUSD \
  --source 'UNKNOWN-timezone broker mirror; indicative-mid assumption' \
  --output-name mirror_devval

PYTHONPATH=/workspace/analysis-deps:/workspace/TradingAgent \
python -m unittest research.intraday_model.test_model -v
```

The four integrity checks prove completed features remain unchanged by future
price mutation, and cost-aware labels match the shared MID and BID single-trade
execution engine, verify stale-signal rejection, and require a prior dip before a completed rebound. Serialized model files stay research-only. Their source,
parameters, feature order and training boundary must be frozen with a source
hash before any final evaluation.
