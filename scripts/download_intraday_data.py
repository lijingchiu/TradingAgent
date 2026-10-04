#!/usr/bin/env python3
"""Download authentic FX candles without substituting generated prices.

Dukascopy publishes UTC daily LZMA .bi5 archives with 24-byte big-endian
(seconds, open, close, low, high, vendor volume) minute candle records.
EURUSD/GBPUSD/AUDUSD/USDCAD/USDCHF integer prices divide by 100000.
Provider zero-volume closed-market candles are preserved in raw archives but
excluded as complete zero-volume aggregated M5/M15 bars. TLS stays verified.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import csv
import datetime as dt
import gzip
import hashlib
import json
import lzma
import math
import pathlib
import struct
import time
import threading
import urllib.error
import urllib.request
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parents[1] / 'data' / 'intraday'
UTC = dt.timezone.utc
FIELDS = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
USER_AGENT = 'TradingAgentHistoricalResearch/1.0'
MIRROR_COMMIT = 'fbd29b3cd85c0eea4f6e8b81c053f98fb3de22fd'
try:
    import requests
except ImportError:
    requests = None
_THREAD = threading.local()


def verified_get(url, attempts=3):
    for attempt in range(attempts):
        try:
            if requests is not None:
                if not hasattr(_THREAD, 'session'):
                    _THREAD.session = requests.Session()
                    _THREAD.session.headers.update({'User-Agent': USER_AGENT})
                # requests preserves TLS verification and respects the injected
                # REQUESTS_CA_BUNDLE; every worker owns one persistent session.
                response = _THREAD.session.get(url, timeout=(12, 35))
                _THREAD.last_response_url = response.url
                if response.status_code in (404, 410):
                    return b'', response.status_code
                if response.status_code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                    response.close()
                    time.sleep(2 ** attempt)
                    continue
                response.raise_for_status()
                return response.content, response.status_code
            request = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
            with urllib.request.urlopen(request, timeout=35) as response:
                return response.read(), response.status
        except urllib.error.HTTPError as error:
            if error.code in (404, 410):
                return b'', error.code
            if error.code not in (429, 500, 502, 503, 504) or attempt + 1 == attempts:
                raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt + 1 == attempts:
                raise
        except Exception as error:
            if requests is None or not isinstance(error, (requests.Timeout, requests.ConnectionError)) or attempt + 1 == attempts:
                raise
        time.sleep(2 ** attempt)
    raise RuntimeError('Unreachable request state')


def write_csv(path, rows):
    temporary = path.with_suffix(path.suffix + '.part')
    with temporary.open('w', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def mirror(symbol):
    ROOT.mkdir(parents=True, exist_ok=True)
    url = f'https://raw.githubusercontent.com/ejtraderLabs/historical-data/{MIRROR_COMMIT}/{symbol}/{symbol}m15.csv'
    raw, status = verified_get(url)
    if status != 200:
        raise RuntimeError(f'Mirror unavailable: {symbol}: HTTP {status}')
    stem = f'mirror_{symbol.lower()}_m15'
    (ROOT / f'{stem}_raw.csv').write_bytes(raw)
    rows, invalid = [], []
    for index, record in enumerate(csv.DictReader(raw.decode().splitlines())):
        values = {key: float(record[key]) / 100000 for key in ('open', 'high', 'low', 'close')}
        if (not all(math.isfinite(value) and value > 0 for value in values.values())
            or values['low'] > min(values['open'], values['close']) + 1e-8
            or values['high'] < max(values['open'], values['close']) - 1e-8):
            invalid.append(index)
            continue
        rows.append({'timestamp': record['Date'].replace(' ', 'T'), **values, 'volume': record['tick_volume']})
    target = ROOT / f'{stem}.csv'
    write_csv(target, rows)
    timestamps = [row['timestamp'] for row in rows]
    metadata = {'provider': 'ejtraderLabs public broker-history mirror', 'repository': 'https://github.com/ejtraderLabs/historical-data',
                'pinned_commit': MIRROR_COMMIT, 'source_url': url, 'retrieved_at_utc': dt.datetime.now(UTC).isoformat(),
                'symbol': symbol, 'timeframe': 'M15', 'quote_side': 'UNKNOWN', 'timezone': 'UNKNOWN; timestamps intentionally naive',
                'price_divisor': 100000, 'rows': len(rows), 'invalid_row_indices_excluded': invalid,
                'duplicate_timestamps': len(timestamps) - len(set(timestamps)),
                'unsorted_transitions': sum(b <= a for a, b in zip(timestamps, timestamps[1:])),
                'first': timestamps[0], 'last': timestamps[-1], 'raw_sha256': hashlib.sha256(raw).hexdigest(),
                'normalized_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
                'limitations': ['Original broker and timezone unknown: do not infer UTC session edges.', 'Actual M15 bars; not upsampled H1 candles.', 'No authenticated bid/ask spread or trade-fill path.']}
    (ROOT / f'{stem}_provenance.json').write_text(json.dumps(metadata, indent=2))
    print(json.dumps({'stage': 'mirror_ready', 'symbol': symbol, 'file': str(target), 'rows': len(rows), 'first': timestamps[0], 'last': timestamps[-1]}), flush=True)


def day_fetch(job):
    symbol, side, day = job
    relative = pathlib.Path(symbol) / side / f'{day.year:04d}' / f'{day.month:02d}' / f'{day.day:02d}.bi5'
    path = ROOT / 'dukascopy_raw' / relative
    url = f'https://datafeed.dukascopy.com/datafeed/{symbol}/{day.year}/{day.month - 1:02d}/{day.day:02d}/{side}_candles_min_1.bi5'
    cached = path.exists()
    fetched_url = url
    if cached:
        raw = path.read_bytes()
        status = 200
        sidecar = path.with_suffix('.provenance.json')
        if sidecar.exists():
            cached_metadata = json.loads(sidecar.read_text())
            if cached_metadata['sha256'] != hashlib.sha256(raw).hexdigest():
                raise ValueError(f'Cached archive differs from its recorded checksum: {path}')
            fetched_url = cached_metadata.get('fetched_url', url)
    else:
        raw, status = verified_get(url)
        fetched_url = getattr(_THREAD, 'last_response_url', url)
        if status == 200:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix('.part')
            temporary.write_bytes(raw)
            temporary.replace(path)
            path.with_suffix('.provenance.json').write_text(json.dumps({
                'url': url, 'fetched_url': fetched_url, 'retrieved_at_utc': dt.datetime.now(UTC).isoformat(),
                'sha256': hashlib.sha256(raw).hexdigest()}, indent=2))
    if status != 200:
        return {'date': day.isoformat(), 'url': url, 'fetched_url': fetched_url, 'status': status, 'rows': [], 'invalid_records': [], 'cached': cached}
    decoded = lzma.decompress(raw) if raw else b''
    if len(decoded) % 24:
        raise ValueError(f'Invalid 24-byte candle payload: {url}: {len(decoded)} bytes')
    rows, invalid, zero_volume, seen = [], [], 0, set()
    for index, (seconds, opening, closing, low, high, volume) in enumerate(struct.iter_unpack('>5If', decoded)):
        if (seconds >= 86400 or seconds % 60 or seconds in seen
            or not 0 < low <= min(opening, closing) <= max(opening, closing) <= high
            or not math.isfinite(volume) or volume < 0):
            invalid.append(index)
            continue
        seen.add(seconds)
        zero_volume += int(volume == 0)
        timestamp = dt.datetime.combine(day, dt.time.min, UTC) + dt.timedelta(seconds=seconds)
        rows.append({'timestamp': timestamp.isoformat().replace('+00:00', 'Z'), 'open': opening / 100000,
                     'high': high / 100000, 'low': low / 100000, 'close': closing / 100000, 'volume': volume})
    return {'date': day.isoformat(), 'url': url, 'fetched_url': fetched_url, 'status': status, 'raw_bytes': len(raw),
            'sha256': hashlib.sha256(raw).hexdigest(), 'raw_record_count': len(decoded) // 24,
            'valid_record_count': len(rows), 'zero_volume_record_count': zero_volume,
            'invalid_records': invalid, 'rows': rows, 'cached': cached}


def aggregate_minutes(rows, minutes):
    buckets = defaultdict(list)
    for row in rows:
        timestamp = dt.datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
        slot = timestamp.replace(minute=(timestamp.minute // minutes) * minutes, second=0, microsecond=0)
        buckets[slot].append(row)
    result, skipped_missing, skipped_zero_volume = [], [], 0
    for slot, components in sorted(buckets.items()):
        components.sort(key=lambda row: row['timestamp'])
        expected = [(slot + dt.timedelta(minutes=i)).isoformat().replace('+00:00', 'Z') for i in range(minutes)]
        if [row['timestamp'] for row in components] != expected:
            skipped_missing.append({'timestamp': slot.isoformat().replace('+00:00', 'Z'), 'observed_minutes': len(components)})
            continue
        volume = sum(row['volume'] for row in components)
        if volume <= 0:
            skipped_zero_volume += 1
            continue
        result.append({'timestamp': slot.isoformat().replace('+00:00', 'Z'), 'open': components[0]['open'],
                       'high': max(row['high'] for row in components), 'low': min(row['low'] for row in components),
                       'close': components[-1]['close'], 'volume': volume})
    return result, skipped_missing, skipped_zero_volume


def dukascopy(symbols, start, end, workers, side, label, export_minute=False):
    ROOT.mkdir(parents=True, exist_ok=True)
    days = []
    day = start
    while day <= end:
        if day.weekday() != 5:  # UTC Saturday is closed for ordinary FX.
            days.append(day)
        day += dt.timedelta(days=1)
    jobs = [(symbol, side, day) for symbol in symbols for day in days]
    print(json.dumps({'stage': 'download_start', 'jobs': len(jobs), 'symbols': symbols, 'side': side,
                      'start': start.isoformat(), 'end': end.isoformat(), 'workers': workers,
                      'estimated_compressed_megabytes': round(len(jobs) * .012, 1)}), flush=True)
    by_symbol = {symbol: [] for symbol in symbols}
    started = time.monotonic()
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {executor.submit(day_fetch, job): job for job in jobs}
        for count, future in enumerate(concurrent.futures.as_completed(future_map), 1):
            symbol, _, day = future_map[future]
            try:
                by_symbol[symbol].append(future.result())
            except Exception as error:
                failures.append({'symbol': symbol, 'date': day.isoformat(), 'error': type(error).__name__, 'detail': str(error)[:200]})
                print(json.dumps({'stage': 'archive_download_failed', 'symbol': symbol, 'date': day.isoformat(),
                                  'error': type(error).__name__, 'detail': str(error)[:200]}), flush=True)
            if count % 100 == 0 or count == len(jobs):
                print(json.dumps({'stage': 'download_progress', 'done': count, 'total': len(jobs),
                                  'failures': len(failures), 'elapsed_seconds': round(time.monotonic() - started, 1)}), flush=True)
    for symbol in symbols:
        records = sorted(by_symbol[symbol], key=lambda record: record['date'])
        minute_rows = [row for record in records for row in record['rows']]
        stem = f'dukascopy_{symbol.lower()}_{side.lower()}_{label}'
        minute_path = ROOT / f'{stem}_m1.csv.gz'
        if export_minute:
            minute_temporary = minute_path.with_suffix(minute_path.suffix + '.part')
            with gzip.open(minute_temporary, 'wt', newline='', compresslevel=3) as output:
                writer = csv.DictWriter(output, fieldnames=FIELDS)
                writer.writeheader()
                writer.writerows(minute_rows)
            minute_temporary.replace(minute_path)
        manifest = [{key: value for key, value in record.items() if key != 'rows'} for record in records]
        symbol_failures = [failure for failure in failures if failure['symbol'] == symbol]
        metadata = {'provider': 'Dukascopy Bank SA public historical datafeed', 'source_domain': 'https://datafeed.dukascopy.com',
                    'symbol': symbol, 'quote_side': side, 'timezone': 'UTC', 'binary_format': '>5If (seconds,open,close,low,high,vendor_volume)',
                    'binary_record_bytes': 24, 'price_divisor': 100000, 'compression': 'LZMA',
                    'retrieved_at_utc': dt.datetime.now(UTC).isoformat(), 'date_start_inclusive': start.isoformat(),
                    'date_end_inclusive': end.isoformat(), 'requested_day_count': len(days), 'received_day_count': len(records),
                    'http_unavailable_dates': [{'date': record['date'], 'status': record['status']} for record in records if record['status'] != 200],
                    'download_failures': symbol_failures, 'minute_rows': len(minute_rows),
                    'invalid_minute_record_count': sum(len(record['invalid_records']) for record in records),
                    'zero_vendor_volume_minutes': sum(record.get('zero_volume_record_count', 0) for record in records),
                    'per_archive_provenance': manifest, 'aggregate_outputs': {},
                    'limitations': ['BID OHLC is a bid reference, not mid-price or executable ask quotes.' if side == 'BID' else 'ASK OHLC is an ask reference, not mid-price or executable bid quotes.',
                                    'Minutes with zero vendor volume can be provider-carried flat quotes, especially market closure.',
                                    'No M5/M15 bar is created if all component minutes have zero vendor volume.',
                                    'Complete aggregation requires every expected actual source minute; no local imputation.',
                                    'Saturday UTC archives skipped because ordinary FX is closed; Sunday live quotes are retained.',
                                    'OHLC does not reveal tick-order within a candle; stop-first treatment is conservative.',
                                    'Historical public feed is not a licensed real-time broker execution feed.']}
        for minutes in (15, 5):
            bars, incomplete, flat = aggregate_minutes(minute_rows, minutes)
            target = ROOT / f'{stem}_m{minutes}.csv'
            write_csv(target, bars)
            metadata['aggregate_outputs'][f'M{minutes}'] = {'file': target.name, 'rows': len(bars),
                'first': bars[0]['timestamp'] if bars else None, 'last': bars[-1]['timestamp'] if bars else None,
                'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'incomplete_blocks_excluded': incomplete,
                'zero_volume_blocks_excluded': flat}
            print(json.dumps({'stage': 'dataset_ready', 'symbol': symbol, 'timeframe': f'M{minutes}',
                              'file': str(target), 'rows': len(bars), 'first': bars[0]['timestamp'] if bars else None,
                              'last': bars[-1]['timestamp'] if bars else None}), flush=True)
        (ROOT / f'{stem}_provenance.json').write_text(json.dumps(metadata, indent=2))
    if failures:
        (ROOT / f'download_failures_{label}.json').write_text(json.dumps(failures, indent=2))
        raise RuntimeError(f'{len(failures)} daily downloads failed; inspect provenance and retry cached job after diagnosis.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', choices=['mirror', 'dukascopy'], required=True)
    parser.add_argument('--symbols', nargs='+', default=['EURUSD'])
    parser.add_argument('--start')
    parser.add_argument('--end')
    parser.add_argument('--workers', type=int, default=12)
    parser.add_argument('--side', choices=['BID', 'ASK'], default='BID')
    parser.add_argument('--label', default='history')
    parser.add_argument('--export-minute', action='store_true', help='Also export decoded M1 gzip CSV; originals are always cached')
    args = parser.parse_args()
    if not 1 <= args.workers <= 12:
        parser.error('Use between 1 and 12 workers')
    if any(symbol not in {'EURUSD', 'GBPUSD', 'AUDUSD', 'USDCHF', 'USDCAD'} for symbol in args.symbols):
        parser.error('This decoder currently supports the listed 100000-scale FX instruments only')
    if args.provider == 'mirror':
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, args.workers)) as executor:
            list(executor.map(mirror, args.symbols))
    else:
        if not args.start or not args.end:
            parser.error('Dukascopy requires --start YYYY-MM-DD and --end YYYY-MM-DD')
        dukascopy(args.symbols, dt.date.fromisoformat(args.start), dt.date.fromisoformat(args.end), args.workers, args.side, args.label, args.export_minute)

if __name__ == '__main__':
    main()
