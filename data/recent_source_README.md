# MT5 broker market data — US500, EURUSD, XAUUSD

Public CSV export of broker-side market data captured from a MetaTrader 5
terminal connected to **FTMO-Server4**. Intended as a clean dataset for
strategy backtesting, microstructure research, and engine warm-up.

**Period covered:** 2025-01-02 → 2026-05-15 (498 calendar days, ≈16.4 months)

## Symbols

| Symbol       | Description                | Period            |
|--------------|----------------------------|-------------------|
| `US500.cash` | S&P 500 cash CFD           | 2025-01-02 → 2026-05-15 |
| `EURUSD`     | EUR / USD spot FX          | 2025-01-02 → 2026-05-15 |
| `XAUUSD`     | Gold spot (USD per ounce)  | 2025-01-02 → 2026-05-15 |

## Files

### OHLCV bars

Pattern: `<symbol>_<timeframe>.csv` — one file per (symbol, timeframe).

| Timeframe | Source                                        | Bar count (per symbol) |
|-----------|-----------------------------------------------|------------------------|
| **M1**    | Resampled from broker ticks (mid-price OHLC)  | 477k – 507k            |
| M10..D1   | Broker-native OHLC (MT5 `copy_rates_range`)   | 48k → 354              |

**M1 columns**: `datetime, open, high, low, close, volume`
- `datetime` is UTC, ISO format `YYYY-MM-DD HH:MM:SS`
- `open / high / low / close` are **mid-price** (= (bid+ask)/2) — for honest
  fill modeling, add half the spread on entry/exit (see `symbol_specs.csv` and
  `spreads_summary.csv`)
- `volume` is **tick count per minute** (the broker does not publish trade
  volume on CFDs/FX; tick count is the best available proxy for activity)

**M10..D1 columns**: `datetime, open, high, low, close, volume, spread`
- Same as M1 but `spread` is the broker-reported median spread for the bar,
  in points (`point` is in `symbol_specs.csv`)

Example (`US500.cash_m1.csv`):
```
datetime,open,high,low,close,volume
2025-01-02 01:05:00,5902.6,5902.685,5902.41,5902.685,9
2025-01-02 01:06:00,5902.65,5902.825,5902.34,5902.795,33
2025-01-02 01:07:00,5902.755,5902.945,5902.69,5902.85,38
```

### `symbol_specs.csv`

Broker-published specs (full MT5 `SymbolInfo` dump). Critical columns:

| Field                  | Meaning                                                                 |
|------------------------|-------------------------------------------------------------------------|
| `point`                | Smallest price increment (e.g. US500=0.01, EURUSD=0.00001, XAUUSD=0.01) |
| `digits`               | Decimal digits of price                                                 |
| `trade_contract_size`  | Lot multiplier (US500=1, EURUSD=100000, XAUUSD=100)                     |
| `trade_tick_value`     | Profit ($) per `trade_tick_size` price move per 1.0 lot                 |
| `trade_tick_size`      | Price granularity for `trade_tick_value`                                |
| **Dollar per point per lot** | `trade_tick_value / trade_tick_size` (US500=$1, EURUSD=$10/pip, XAUUSD=$1/cent) |
| `volume_min / max / step` | Lot bounds                                                           |
| `spread`               | Latest server-reported spread, in `point` units                         |
| `swap_long / short`    | Daily roll cost per 1.0 lot held overnight (in points, applied at broker midnight) |

### `spreads_summary.csv`

Hourly aggregate of the live per-minute spread distribution captured on the
real account during May 16-23, 2026 (8 trading days, ~184k minute snapshots).
Columns:

| Field          | Meaning                                                                       |
|----------------|-------------------------------------------------------------------------------|
| `symbol`       | Symbol name                                                                   |
| `hour_utc`     | Hour-of-day (0..23) in UTC                                                    |
| `samples`      | Number of minute-bars contributing                                            |
| `mean_spread`  | Mean spread for that hour, in points                                          |
| `p50, p75, p95, p99` | Spread percentiles for that hour, in points                              |
| `max`          | Observed max spread that hour (news-spike value), in points                   |

Use this to budget execution cost realistically by time of day.

## Cost model — how to use this for backtesting

**Round-trip cost = spread × volume × $/point per lot.**

| Symbol     | Median (calm) spread | Median round-trip on 1 lot |
|------------|----------------------|----------------------------|
| US500.cash | 0.55 pt              | $0.55                       |
| EURUSD     | 0.2 pips             | $2.00                       |
| XAUUSD     | 0.45 USD             | $0.45                       |

FTMO does NOT charge commission on indices/FX/metals — the spread IS the
cost. Slippage is captured implicitly in the spread distribution: p99 vs p50
gives a realistic tail-risk envelope for fills during news/illiquidity.

**Stop-loss model:** broker `trade_stops_level = 0` on all three symbols, so
the broker does not enforce a minimum SL distance — but practical broker
rejection still happens for stops inside the current spread. A safe rule is
`min_stop_distance = max(2 × current_spread, 1 tick)`.

**Weekend gap:** All three symbols close ~22:00 UTC Friday and reopen
~22:00–22:05 UTC Sunday. Stop orders held over the gap fill at the next
session open price with no slippage guarantee.

## Notes on data quality

- Source is a single MT5 broker (FTMO) — for execution realism this is the
  right ground truth, but for cross-validation against consolidated quotes
  (CME for ES, ICE for cable, COMEX for gold) you'd want a parallel source.
- US500.cash and XAUUSD have a daily session break (typically 21:00–22:05
  UTC) — the M1 file has no rows in that window; verify your engine handles
  the gap correctly.
- EURUSD trades roughly 24/5 with very thin Asian session (~22:00–06:00 UTC).
- Mid-price OHLC was chosen for M1 to be neutral; for tighter realism,
  reconstruct from bid/ask separately (the source dump has 25M-60M ticks
  per symbol; this CSV resample preserves the bar shape but loses the
  intra-bar bid/ask split).

## License

Market data is broker-published and not subject to a redistribution license
beyond that of the broker's terms of service. The author of this repo
publishes the CSV transformations under MIT for the format/code; the
underlying data remains the property of the data provider.
