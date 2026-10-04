"""Official paired FXCM minute archives: acquisition and price-quality checks.

No strategy features or outcomes are computed here. Raw FXCM archives and
derived candles stay ignored because the provider specifies personal use.
Download a bounded week list with TLS verification; do not retry rate limits.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "data/intraday/fxcm_official"
DOCS_COMMIT = "924393dd545fab187527d95ef8b1178284b274b6"
DOCS_BLOB = "eaab97d15b8596c52c83ba52f25678e7fbec02a8"
DOCS_URL = f"https://github.com/fxcm/MarketData/blob/{DOCS_COMMIT}/README.md"
COLUMNS = [prefix + field for prefix in ("Bid", "Ask")
           for field in ("Open", "High", "Low", "Close")]


def read_archive(raw: bytes) -> tuple[pd.DataFrame, dict]:
    frame = pd.read_csv(io.BytesIO(gzip.decompress(raw)))
    if list(frame.columns) != ["DateTime"] + COLUMNS or frame.empty:
        raise ValueError("Unexpected FXCM minute schema or empty archive")
    times = pd.to_datetime(frame.pop("DateTime"), format="%m/%d/%Y %H:%M:%S.%f", utc=True)
    if not times.is_monotonic_increasing or times.duplicated().any():
        raise ValueError("Minute timestamps must be sorted and unique within an archive")
    if (times.astype("int64") % 60_000_000_000 != 0).any():
        raise ValueError("Minute timestamps must lie exactly on the UTC minute grid")
    prices = frame[COLUMNS].to_numpy(float)
    bad = ~np.isfinite(prices).all(axis=1) | (prices <= 0).any(axis=1)
    for offset in (0, 4):
        op, hi, lo, cl = prices[:, offset:offset+4].T
        bad |= (lo > np.minimum(op, cl)) | (hi < np.maximum(op, cl)) | (lo > hi)
    # Keep valid BID observations when a corresponding indicative ASK crosses.
    # A crossed ASK open prohibits new entry. Future ASK closes do not gate entry.
    crossed_open = frame.AskOpen < frame.BidOpen
    crossed_close = frame.AskClose < frame.BidClose
    quality = {"rows": len(frame), "invalid_ohlc_rows": int(bad.sum()),
               "crossed_open_rows": int(crossed_open.sum()),
               "crossed_close_rows": int(crossed_close.sum()),
               "first_utc": times.iloc[0].isoformat(), "last_utc": times.iloc[-1].isoformat()}
    frame.insert(0, "time", times)
    return frame.loc[~bad].reset_index(drop=True), quality


def fetch_week(symbol: str, year: int, week: int, cache: Path = CACHE) -> dict:
    if symbol not in ("EURUSD", "GBPUSD", "NZDUSD") or not 1 <= week <= 53:
        raise ValueError("Bounded supported instrument and week required")
    cache.mkdir(parents=True, exist_ok=True)
    path = cache / f"{symbol}_{year}_week{week:02d}.csv.gz"
    url = f"https://candledata.fxcorporate.com/m1/{symbol}/{year}/{week}.csv.gz"
    cached = path.exists()
    if cached:
        raw, status = path.read_bytes(), 200
    else:
        response = requests.get(url, timeout=30, headers={"User-Agent": "TradingAgent-research/1.0"})
        status, raw = response.status_code, response.content
        if status == 429:
            raise RuntimeError("Provider returned HTTP 429; stop acquisition without retry")
        if status not in (200, 404):
            raise RuntimeError(f"Official archive HTTP {status}; stop and diagnose before retry")
    row = {"symbol": symbol, "year_label": year, "week_label": week,
           "url": url, "http_status": status, "cache_hit": cached}
    if status == 200:
        _, quality = read_archive(raw)
        if not cached:
            path.write_bytes(raw)
        row.update(sha256=hashlib.sha256(raw).hexdigest(), bytes=len(raw), quality=quality)
    return row


def aggregate_minutes(frame: pd.DataFrame, minutes: int) -> tuple[pd.DataFrame, dict]:
    if minutes not in (5, 15):
        raise ValueError("Only native complete M5/M15 blocks are supported")
    if not frame.time.is_monotonic_increasing or frame.time.duplicated().any():
        raise ValueError("Aggregation requires sorted unique minutes")
    epoch = (frame.time.astype("int64") // 1_000_000_000).to_numpy(np.int64)
    if (epoch % 60 != 0).any():
        raise ValueError("All minute timestamps must be on-grid")
    grouped = frame.assign(bucket=frame.time.dt.floor(f"{minutes}min")).groupby("bucket", sort=True)
    rules = {prefix+field: operation for prefix in ("Bid", "Ask")
             for field, operation in (("Open", "first"), ("High", "max"), ("Low", "min"), ("Close", "last"))}
    result = grouped.agg(rules)
    count = grouped.size()
    # With unique exact minute timestamps, count == minutes inside an aligned
    # block proves every constituent minute is present. Never forward-fill.
    result = result.loc[count == minutes].reset_index(names="time")
    spread = result.AskOpen - result.BidOpen
    valid = spread >= 0
    quality = {"minutes": minutes, "input_minutes": len(frame), "complete_bars": len(result),
               "incomplete_blocks_omitted": int((count != minutes).sum()),
               "crossed_open_bars_kept_but_entry_blocked": int((~valid).sum()),
               "valid_spread_pips_median": float((spread[valid]/0.0001).median()),
               "valid_spread_pips_p95": float((spread[valid]/0.0001).quantile(.95)),
               "volume": "NOT PROVIDED; no synthetic volume added"}
    return result, quality


def build(symbol: str, years: list[int], label: str, cache: Path = CACHE) -> dict:
    specs = [(symbol, year, week) for year in years for week in range(1, 54)]
    records, frames = [], []
    # Bounded, modest concurrency. map preserves manifest order. No retry loop.
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending = [pool.submit(fetch_week, *spec, cache) for spec in specs[:2]]
        index = 2
        while pending:
            job = pending.pop(0)
            try:
                record = job.result()
            except BaseException:
                for other in pending:
                    other.cancel()
                raise
            records.append(record)
            if len(records) % 25 == 0:
                print(json.dumps({"acquired_weeks": len(records), "requested_weeks": len(specs)}), flush=True)
            if index < len(specs):
                pending.append(pool.submit(fetch_week, *specs[index], cache))
                index += 1
    for record in records:
        if record["http_status"] == 200:
            path = cache / f'{symbol}_{record["year_label"]}_week{record["week_label"]:02d}.csv.gz'
            if hashlib.sha256(path.read_bytes()).hexdigest() != record["sha256"]:
                raise ValueError("Raw archive changed after acquisition")
            frame, _ = read_archive(path.read_bytes())
            frames.append(frame)
    if not frames:
        raise ValueError("No usable official minute archives")
    merged = pd.concat(frames, ignore_index=True).sort_values("time", kind="stable")
    duplicated = merged.time.duplicated(keep=False)
    if duplicated.any():
        if (merged.loc[duplicated].groupby("time")[COLUMNS].nunique(dropna=False) > 1).any().any():
            raise ValueError("Overlapping archives contain conflicting quotes")
    duplicate_rows = int(merged.time.duplicated().sum())
    merged = merged.drop_duplicates("time").reset_index(drop=True)
    # Archive label years are not used as timestamp bounds. The actual UTC
    # dates define the study, including weeks that straddle calendar years.
    merged = merged.loc[(merged.time >= pd.Timestamp(f"{min(years)}-01-01", tz="UTC"))
                        & (merged.time < pd.Timestamp(f"{max(years)+1}-01-01", tz="UTC"))].reset_index(drop=True)
    outputs = {}
    for minutes in (5, 15):
        bars, quality = aggregate_minutes(merged, minutes)
        path = cache / f"{symbol.lower()}_{label}_m{minutes}.csv"
        bars.to_csv(path, index=False, lineterminator="\n")
        outputs[f"m{minutes}"] = {"path": str(path.relative_to(ROOT)), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "quality": quality}
    report = {"source": "FXCM official public paired BID/ASK indicative M1 candles",
              "docs_url": DOCS_URL, "docs_commit": DOCS_COMMIT, "docs_blob": DOCS_BLOB,
              "timestamp_timezone": "UTC", "downloaded_at_utc": datetime.now(timezone.utc).isoformat(),
              "archive_records": records, "missing_week_urls": [r["url"] for r in records if r["http_status"] == 404],
              "usable_unique_minutes": len(merged), "identical_overlap_rows_removed": duplicate_rows,
              "outputs": outputs, "strategy_outcomes_evaluated": False,
              "limitations": ["Provider says indicative lowest-spread Active Trader quotes, not verified executable broker fills",
                              "Provider specifies personal use; raw archives and candle CSVs are not published",
                              "Crossed ASK opens block entry; valid BID exit bars are retained",
                              "Missing minutes and archives are not fabricated; incomplete M5/M15 blocks are omitted"]}
    path = cache / f"{symbol.lower()}_{label}_provenance.json"
    path.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps({"provenance": str(path.relative_to(ROOT)), "minutes": len(merged), "outputs": outputs}), flush=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", choices=("EURUSD", "GBPUSD", "NZDUSD"), default="EURUSD")
    parser.add_argument("--years", nargs="+", type=int, required=True)
    parser.add_argument("--label", required=True)
    args = parser.parse_args()
    build(args.symbol, args.years, args.label)


if __name__ == "__main__":
    main()
