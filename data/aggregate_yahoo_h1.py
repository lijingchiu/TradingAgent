"""Aggregate authentic hourly quotes into complete UTC daily sessions.

Never forward-fill missing quotes or relabel provider daily candles. An accepted
session has all 24 unique UTC hour starts, internally consistent OHLC, and has
ended as of the supplied observation time. Inputs are source observations;
outputs are derived bars, not new market observations.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import math
from collections import defaultdict
from pathlib import Path

UTC = dt.timezone.utc


def parse_timestamp(value: str) -> dt.datetime:
    result = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Hourly input timestamps must declare a timezone")
    return result.astimezone(UTC)


def aggregate_complete_utc_days(rows, as_of=None):
    """Return (completed_daily_bars, excluded_session_report).

    Missing weekend/holiday sessions remain absent. No candle can signal until
    its UTC day has fully ended. Source duplicates retain the last observation
    for that exact timestamp and are disclosed in the report.
    """
    as_of = as_of or dt.datetime.now(UTC)
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    as_of = as_of.astimezone(UTC)
    grouped = defaultdict(dict)
    issues = defaultdict(list)
    observed_dates = []
    for row in rows:
        timestamp = parse_timestamp(row["timestamp"])
        day = timestamp.date()
        observed_dates.append(day)
        if timestamp.minute != 0 or timestamp.second != 0 or timestamp.microsecond != 0:
            issues[day].append("supplemental_non_hour_start_quote_ignored")
            continue
        prices = {field: float(row[field]) for field in ("open", "high", "low", "close")}
        if (not all(math.isfinite(value) and value > 0 for value in prices.values())
            or prices["low"] > min(prices["open"], prices["close"]) + 1e-8
            or prices["high"] < max(prices["open"], prices["close"]) - 1e-8
            or prices["low"] > prices["high"]):
            issues[day].append(f"invalid_hour_{timestamp.hour:02d}_ignored")
            continue
        if timestamp.hour in grouped[day]:
            issues[day].append(f"duplicate_hour_{timestamp.hour:02d}_last_observation_used")
        grouped[day][timestamp.hour] = {**prices, "volume": float(row.get("volume", 0) or 0)}
    if not observed_dates:
        return [], []
    bars, report = [], []
    day = min(observed_dates)
    last_day = max(observed_dates)
    while day <= last_day:
        day_start = dt.datetime.combine(day, dt.time.min, tzinfo=UTC)
        hours = grouped.get(day, {})
        missing = [hour for hour in range(24) if hour not in hours]
        reasons = list(issues.get(day, []))
        if missing:
            reasons.append("missing_hourly_quotes")
        if day_start + dt.timedelta(days=1) > as_of:
            reasons.append("session_not_completed")
        accepted = not missing and day_start + dt.timedelta(days=1) <= as_of
        if accepted:
            bars.append({"timestamp": day_start.isoformat().replace("+00:00", "Z"),
                         "open": hours[0]["open"],
                         "high": max(bar["high"] for bar in hours.values()),
                         "low": min(bar["low"] for bar in hours.values()),
                         "close": hours[23]["close"],
                         "volume": sum(bar["volume"] for bar in hours.values()),
                         "spread_points": "", "source_bar_count": 24})
        if not accepted or reasons:
            report.append({"date_utc": day.isoformat(), "accepted": accepted,
                           "observed_hour_count": len(hours), "missing_hours_utc": missing,
                           "reasons": reasons})
        day += dt.timedelta(days=1)
    return bars, report


if __name__ == "__main__":
    directory = Path(__file__).resolve().parent
    source = directory / "eurusd_yahoo_h1.csv"
    rows = list(csv.DictReader(source.open()))
    bars, exclusions = aggregate_complete_utc_days(rows)
    target = directory / "eurusd_yahoo_h1_utc_d1.csv"
    with target.open("w", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=["timestamp", "open", "high", "low", "close", "volume", "spread_points", "source_bar_count"])
        writer.writeheader()
        writer.writerows(bars)
    (directory / "eurusd_yahoo_h1_utc_d1_exclusions.json").write_text(json.dumps(exclusions, indent=2))
    print(json.dumps({"accepted_daily_sessions": len(bars), "excluded_or_flagged_sessions": len(exclusions),
                      "first": bars[0]["timestamp"] if bars else None, "last": bars[-1]["timestamp"] if bars else None}))
