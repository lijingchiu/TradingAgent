# Authentic intraday foreign-exchange data

CSV schema: `timestamp,open,high,low,close,volume`. Prices use ordinary currency quotations. None of these files contains a strategy outcome, trade label, or invented market price.

- `mirror_*_m15.csv`: original M15 bars from `ejtraderLabs/historical-data`, pinned commit `fbd29b3cd85c0eea4f6e8b81c053f98fb3de22fd`. Original broker, quote side, and timestamp timezone are unknown. Timestamps intentionally have no timezone suffix. Do not infer UTC clock or session edges.
- `dukascopy_*_bid_*_m5.csv` / `_m15.csv`: aggregated from actual Dukascopy public UTC M1 archives. They are **bid** prices, not midpoint or ask prices. Execution needs a disclosed ask/spread model or synchronized ASK data, plus commission and slippage.
- `dukascopy_raw/`: original verified-HTTPS LZMA archives, cached by symbol, side, year, month, and day. Remote URL month is zero-based; local directory month is conventional one-based.
- `*_m1.csv.gz`: decoded UTC minute rows, retaining provider-reported zero-volume rows for inspection.
- `*_provenance.json`: request URLs, hashes, record counts, source exclusions and limitations.

M5/M15 aggregation requires all five or fifteen source minute records in the UTC bucket. It uses first open, maximum high, minimum low, last close and summed vendor volume. No local forward filling or upsampling is performed. An entire zero-volume block is excluded: Dukascopy supplies carried flat prices during market closure, including weekends. Ordinary FX Saturday UTC archives are deliberately skipped; active Sunday quotes are retained. Volume is a provider-specific activity measure, not exchange-cleared volume.

Development protocol: direct UTC EURUSD data from 2015–2021 is development/validation. Reserved final evaluation is 2022-04-01 00:00 UTC through 2024-10-01 exclusive; March 2022 can supply causal warmup and is excluded from final performance. Download and source-quality checks do not authorize fitting strategy parameters to reserved evaluation outcomes.

Daily historical `.bi5` files are not a near-real-time service: on 2026-10-04, the current date archive was unavailable and the previous Friday archive had been modified shortly after midnight the following day. Live M5/M15 execution requires a separately verified current quote/candle source. Historical prices, bid references, and cost-model fills must remain clearly distinguished.

The additional public FXCM/intrade `.qhs5` mirror was decoded locally with
`decode_fxcm_qhs.py` and the system Zstandard library. No downloaded executable
was run. Pinned blobs, source URLs and hashes are in
`fxcm_mirror_*_provenance.json`; large raw blobs and decoder dictionary headers
are excluded from Git. Roughly 8.7% of minute records violate strict OHLC
geometry. They were not repaired by extending extrema or dropping only losing
trades. Strict aggregation leaves extensive nonrandom gaps, so this source was
rejected for strategy certification. Accessing an independent mirror did not
resolve the missing complete official ASK validation dataset.

[Installation and exact development commands](../../research/README.md) explain
the optional research environment. The downloader imports ordinary installed
packages and does not depend on a particular agent's temporary dependency path.
