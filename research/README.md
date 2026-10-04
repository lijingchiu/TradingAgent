# Intraday research reproduction

The research uses native M5/M15 observations and retains rejected candidates.
Research profits never credit the durable paper account. See
[the protocol](intraday_protocol.md) and
[current evidence](../artifacts/intraday/README.md) for the sample roles,
costs, risk measurements and results. A report with 500 losing trades does
not satisfy the profitability requirement.

## Install and check

From the repository root, with Python 3.12:

```bash
uv venv .venv --python python3
uv pip install --python .venv/bin/python -r requirements-research.txt
python3 -m unittest discover -s tests -v
NUMBA_NUM_THREADS=4 .venv/bin/python scripts/check_research.py
.venv/bin/python -m research.intraday_mean_reversion.session_study self-check
.venv/bin/python -m research.intraday_mean_reversion.session_study book-self-check
```

The research integrity checks use synthetic fixtures and compare numeric/JIT
execution with the production Decimal accounting engine. They neither download
prices nor inspect reserved strategy outcomes. Production monitoring requires
only the standard library; research dependencies are checked separately in
`research-checks.yml`, rather than installed in every five-minute monitoring job.

## Prices and source limits

Large FX CSVs and daily archives are excluded from Git; their URLs, pinned
source revisions, hashes and exclusions remain in `data/intraday`. To rebuild
the official BID development/selection data, use:

```bash
.venv/bin/python scripts/download_intraday_data.py --provider dukascopy --symbols EURUSD --side BID --start 2015-01-01 --end 2022-01-01 --label development_2015_2021 --workers 2
```

The end date is exclusive. The downloader validates HTTPS, archive decoding,
OHLC and complete UTC minute buckets before producing M5/M15. Rebuilding
requires the provider to be available. Failed daily downloads remain explicit;
do not treat partial coverage as a complete study. The full ASK download was
blocked by upstream connection failures during this research. Do not retry a
rate-limited endpoint aggressively, invent missing ASK prices, or infer that
2015's complete bid/ask sample proves profitability in later years.

FX mirrors have unknown source quote side and broker timezone. They permit
chronological diagnostic research, not named UTC/London/NY sessions. The
independent FXCM-format mirror failed strict OHLC checks and was excluded from
certification. See [data definitions](../data/intraday/README.md).

Native MES/NQ CSVs are retained under their study `source` directories, pinned
to public repository `axb0306/cme-futures-ohlc` revision
`60abd3fb6369c6ce0b6a4a65b0f2562fc96b1264`. Valid native bars do not prove the
initial contract identity, timestamp start/end convention or executable bid/ask.
The studies disclose their bar-start convention, exclude March and incomplete
sessions, and model costs against vendor-reported last-trade OHLC. They use one
whole contract with fixed fees only when the one-contract assertion holds.
MES USD5m and NQ USD80m initial research equity are numerical sizing scenarios,
not deposits into the paper account. The fully funded numerical model does not
prove actual futures variation-margin or negative-price loss bounds.

## Fixed development and selection runs

Read the immutable preregistration and existing report before reproducing a
run. Preserve old reports outside their output paths. Several commands refuse
to recreate an existing preregistration; this prevents registering a candidate
list after observing its outcomes. Do not remove those guards or receipts.

```bash
.venv/bin/python -m research.intraday_mean_reversion.develop --symbol EURUSD --data data/intraday/dukascopy_eurusd_bid_development_2015_2021_m15.csv --quote-kind bid --source-timezone UTC --out-dir /tmp/eurusd-m15-reproduction
.venv/bin/python -m research.intraday_sweep.study --data data/intraday/dukascopy_eurusd_bid_development_2015_2021_m5.csv --minutes 5
.venv/bin/python -m research.intraday_mean_reversion.futures_mes --develop
.venv/bin/python -m research.intraday_nq.study evaluate-selection
```

These commands evaluate development/selection observations, not April futures
or the 2022–2024 FX final. The remaining fixed families have CLI help and their
own preregistrations under `artifacts/intraday`; model-specific commands and
feature/label semantics are in [model instructions](intraday_model/README.md).
Do not run a reserved final candidate until one winner across eligible families
has been frozen with source, code, parameters, costs and selection evidence.
If no candidate qualifies, retain the untouched final and closed paper gate.

Regenerate presentation from saved reports without running strategies:

```bash
python3 research/build_status.py
python3 -m trading_agent.cli dashboard
```

The summary lists parameter/source/cost trials separately from diagnostic
confirmations and control baselines. Its evidence hashes allow checking that
the panel refers to those exact reports. It is not an execution approval.
