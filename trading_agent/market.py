"""Public indicative prices, with freshness and completed-bar safeguards."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import math
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

from .execution import Bar

UTC = timezone.utc
NEW_YORK = ZoneInfo("America/New_York")


@dataclass
class MarketSnapshot:
    bars: list[Bar]
    mid: float
    quote_time: datetime
    fetched_at: datetime
    source_url: str
    excluded_null: int = 0
    excluded_invalid: int = 0
    symbol: str = "EURUSD=X"


def forex_is_open(now: datetime) -> bool:
    local = now.astimezone(NEW_YORK)
    day = local.weekday()
    return day < 4 or (day == 4 and local.hour < 17) or (day == 6 and local.hour >= 17)


def next_weekly_open(now: datetime) -> datetime:
    local = now.astimezone(NEW_YORK)
    days = (6 - local.weekday()) % 7
    opening = (local + timedelta(days=days)).replace(hour=17, minute=0, second=0, microsecond=0)
    if opening <= local:
        opening += timedelta(days=7)
    return opening.astimezone(UTC)


def parse_chart(payload: dict, now: datetime, source_url: str) -> MarketSnapshot:
    chart = payload.get("chart", {})
    if chart.get("error") or not chart.get("result"):
        raise ValueError("行情來源未回傳有效資料")
    result = chart["result"][0]
    meta = result["meta"]
    if meta.get("dataGranularity") != "1h":
        raise ValueError("行情來源未遵守 1h 頻率，禁止使用")
    if meta.get("symbol") != "EURUSD=X":
        raise ValueError("行情標的不符 EURUSD=X")
    quote_time = datetime.fromtimestamp(meta["regularMarketTime"], UTC)
    mid = float(meta["regularMarketPrice"])
    if not math.isfinite(mid) or mid <= 0:
        raise ValueError("報價不是有效正值")
    if quote_time > now + timedelta(seconds=60):
        raise ValueError("報價時間位於未來")
    prices = result["indicators"]["quote"][0]
    bars = []
    nulls = invalid = 0
    for i, stamp in enumerate(result.get("timestamp", [])):
        time = datetime.fromtimestamp(stamp, UTC)
        if stamp % 3600 or time + timedelta(hours=1) > now:
            continue
        values = [prices[key][i] for key in ("open", "high", "low", "close")]
        if any(value is None for value in values):
            nulls += 1
            continue
        try:
            bar = Bar(time, *(float(value) for value in values))
            if min(values) <= 0:
                raise ValueError("nonpositive price")
        except (ValueError, TypeError):
            invalid += 1
            continue
        if bars and time <= bars[-1].time:
            raise ValueError("行情時間重複或沒有依序排列")
        bars.append(bar)
    if not bars:
        raise ValueError("沒有已完成的小時行情")
    return MarketSnapshot(bars, mid, quote_time, now, source_url, nulls, invalid)


def aggregate_bars(bars: list[Bar], hours: int = 1) -> list[Bar]:
    """Aggregate complete, consecutive UTC blocks; never fill missing hours."""
    if hours not in (1, 4):
        raise ValueError("Only hourly or four-hour research is supported")
    if hours == 1:
        return bars
    groups = {}
    for bar in bars:
        start = bar.time.replace(hour=bar.time.hour // hours * hours, minute=0, second=0, microsecond=0)
        groups.setdefault(start, []).append(bar)
    result = []
    for start, group in sorted(groups.items()):
        if len(group) != hours or any(bar.time != start + timedelta(hours=i) for i, bar in enumerate(group)):
            continue
        result.append(Bar(start, group[0].open, max(bar.high for bar in group),
                          min(bar.low for bar in group), group[-1].close))
    return result


def fetch_market(now: datetime | None = None, history_days: int = 180) -> MarketSnapshot:
    now = now or datetime.now(UTC)
    query = urllib.parse.urlencode({
        "period1": int((now - timedelta(days=history_days)).timestamp()),
        "period2": int((now + timedelta(seconds=1)).timestamp()),
        "interval": "1h",
    })
    url = "https://query1.finance.yahoo.com/v8/finance/chart/EURUSD=X?" + query
    request = urllib.request.Request(url, headers={"User-Agent": "TradingAgent/0.1", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    return parse_chart(payload, now, url)
