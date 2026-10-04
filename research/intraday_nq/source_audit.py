"""Source-only NQ audit. Never constructs strategy signals or outcomes.

The retained CSV is the exact native M5 file at the pinned public commit. The
downloaded updater is inspected as text, never imported or executed. April is
inspected only for source validity and calendar coverage. March remains outside
all strategy splits under the predetermined whole-roll-month exclusion.
"""
from __future__ import annotations

from collections import Counter
import csv
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/intraday/nq"
SOURCE = OUT / "source/NQ_5min_20260120_20260415.csv"
COMMIT = "60abd3fb6369c6ce0b6a4a65b0f2562fc96b1264"
SHA256 = "053a99028da0675d828141e5082af9bfadc9c2c24cbc2052077fdc3df3525005"
BASE_URL = f"https://raw.githubusercontent.com/axb0306/cme-futures-ohlc/{COMMIT}"
NY = ZoneInfo("America/New_York")
STEP = timedelta(minutes=5)
COLUMNS = ["datetime", "open", "high", "low", "close", "volume"]
SPLITS = {
    "development": (date(2026, 1, 21), date(2026, 2, 13)),
    "validation": (date(2026, 2, 16), date(2026, 2, 27)),
    "reserved_source_only": (date(2026, 4, 1), date(2026, 4, 15)),
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def session_date(ts: datetime) -> date:
    local = ts.astimezone(NY)
    return local.date() + timedelta(days=local.hour >= 18)


def profile(rows: list[dict], stamps: list[datetime]) -> dict:
    failures = Counter()
    nulls = {column: sum(not row.get(column, "").strip() for row in rows)
             for column in COLUMNS}
    for row in rows:
        try:
            prices = [Decimal(row[column]) for column in COLUMNS[1:5]]
        except (InvalidOperation, KeyError):
            failures["price_parse_failure_rows"] += 1
            continue
        if not all(p.is_finite() for p in prices):
            failures["nonfinite_price_rows"] += 1
        else:
            op, hi, lo, cl = prices
            failures["nonpositive_price_rows"] += any(p <= 0 for p in prices)
            failures["invalid_ohlc_geometry_rows"] += not (lo <= min(op, cl) <= max(op, cl) <= hi)
            failures["off_quarter_point_tick_rows"] += any(p * 4 != (p * 4).to_integral_value() for p in prices)
        try:
            volume = Decimal(row["volume"])
        except (InvalidOperation, KeyError):
            failures["volume_parse_failure_rows"] += 1
            continue
        if not volume.is_finite():
            failures["nonfinite_volume_rows"] += 1
        else:
            failures["negative_volume_rows"] += volume < 0
            failures["noninteger_volume_rows"] += volume != volume.to_integral_value()
            failures["zero_volume_rows"] += volume == 0
    keys = Counter(stamps)
    exact = Counter(tuple(row.get(c) for c in COLUMNS) for row in rows)
    return {
        "rows": len(rows), "columns": COLUMNS, "null_counts": nulls,
        "first_timestamp_utc": min(stamps).isoformat() if stamps else None,
        "last_timestamp_utc": max(stamps).isoformat() if stamps else None,
        "exact_duplicate_rows_excess": sum(n - 1 for n in exact.values() if n > 1),
        "duplicate_timestamp_rows_excess": sum(n - 1 for n in keys.values() if n > 1),
        "duplicate_timestamp_keys": sum(n > 1 for n in keys.values()),
        "nonincreasing_adjacent_pairs": sum(b <= a for a, b in zip(stamps, stamps[1:])),
        "off_native_five_minute_grid_rows": sum(t.minute % 5 != 0 or t.second != 0 or t.microsecond != 0 for t in stamps),
        **{key: failures[key] for key in (
            "price_parse_failure_rows", "nonfinite_price_rows", "nonpositive_price_rows",
            "invalid_ohlc_geometry_rows", "off_quarter_point_tick_rows",
            "volume_parse_failure_rows", "nonfinite_volume_rows", "negative_volume_rows",
            "noninteger_volume_rows", "zero_volume_rows")},
    }


def observed_gaps(stamps: list[datetime]) -> list[dict]:
    result = []
    for previous, following in zip(stamps, stamps[1:]):
        if following - previous <= STEP:
            continue
        a, b = previous.astimezone(NY), following.astimezone(NY)
        if a.time() == time(16, 55) and b.time() == time(18) and a.date() == b.date():
            category = "ordinary_daily_maintenance_closure"
        elif a.weekday() == 4 and a.time() == time(16, 55) and b.weekday() == 6 and b.time() == time(18):
            category = "ordinary_weekend_closure_including_dst_when_applicable"
        elif a.date() == date(2026, 2, 16) and a.time() == time(12, 55) and b.time() == time(18):
            category = "presidents_day_shaped_short_session_calendar_not_independently_verified"
        elif a.date() == date(2026, 4, 3) and a.time() == time(9, 10) and b.weekday() == 6 and b.time() == time(18):
            category = "good_friday_shaped_short_session_calendar_not_independently_verified"
        elif a.date() == date(2026, 3, 18) and a.time() == time(17) and b.time() == time(18):
            category = "maintenance_after_extra_1700_bar_in_excluded_march"
        else:
            category = "unclassified_requires_investigation"
        delta = int((following - previous).total_seconds())
        result.append({"previous_bar_utc": previous.isoformat(),
                       "next_bar_utc": following.isoformat(),
                       "previous_bar_new_york": a.isoformat(),
                       "next_bar_new_york": b.isoformat(),
                       "elapsed_seconds": delta,
                       "absent_grid_slots_between_observed_bars": delta // 300 - 1,
                       "classification": category})
    return result


def split_coverage(rows: list[dict], stamps: list[datetime], start: date, end: date) -> dict:
    # Both date conventions are recorded; strategy code must choose and freeze
    # its own explicitly. This function assesses source coverage only.
    selected = [(row, ts) for row, ts in zip(rows, stamps) if start <= session_date(ts) <= end]
    source_stamps = {ts for _, ts in selected}
    sessions = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            previous_date = day - timedelta(days=1)
            first = datetime.combine(previous_date, time(18), NY).astimezone(timezone.utc)
            last_exclusive = datetime.combine(day, time(17), NY).astimezone(timezone.utc)
            expected = set()
            current = first
            while current < last_exclusive:
                expected.add(current)
                current += STEP
            observed = {ts for ts in source_stamps if session_date(ts) == day}
            missing = sorted(expected - observed)
            extra = sorted(observed - expected)
            sessions.append({
                "session_date": day.isoformat(), "rows": len(observed),
                "ordinary_session_expected_native_slots": len(expected),
                "present_ordinary_session_native_slots": len(expected & observed),
                "absent_ordinary_session_native_slots": len(missing),
                "outside_ordinary_session_native_slots": len(extra),
                "first_observed_utc": min(observed).isoformat() if observed else None,
                "last_observed_utc": max(observed).isoformat() if observed else None,
                "scheduled_1650_new_york_quote_present": datetime.combine(day, time(16, 50), NY).astimezone(timezone.utc) in observed,
                "missing_native_slots_utc": [ts.isoformat() for ts in missing],
                "outside_native_slots_utc": [ts.isoformat() for ts in extra],
            })
        day += timedelta(days=1)
    utc_selected = [(row, ts) for row, ts in zip(rows, stamps) if start <= ts.date() <= end]
    return {
        "inclusive_session_dates": [start.isoformat(), end.isoformat()],
        "session_date_definition": "America/New_York 18:00 assigns the next calendar date; normal session ends before 17:00",
        "ordinary_session_calendar_assumption": "Weekday session: previous local day 18:00 through local day 16:55 inclusive (276 M5 slots). Holidays are retained and explicitly marked partial; no holiday-adjusted completeness claim.",
        "globex_session_date_profile": profile([r for r, _ in selected], [t for _, t in selected]),
        "utc_calendar_date_profile": profile([r for r, _ in utc_selected], [t for _, t in utc_selected]),
        "ordinary_weekday_session_count": len(sessions),
        "complete_ordinary_sessions": sum(s["absent_ordinary_session_native_slots"] == 0 for s in sessions),
        "partial_ordinary_session_dates": [s["session_date"] for s in sessions if s["absent_ordinary_session_native_slots"]],
        "ordinary_session_missing_slots": sum(s["absent_ordinary_session_native_slots"] for s in sessions),
        "missing_scheduled_1650_quote_session_dates": [s["session_date"] for s in sessions if not s["scheduled_1650_new_york_quote_present"]],
        "sessions": sessions,
    }


def main() -> None:
    if sha256(SOURCE) != SHA256:
        raise ValueError("Pinned exact raw NQ M5 source hash changed")
    with SOURCE.open(newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != COLUMNS:
            raise ValueError("Unexpected CSV schema")
        rows = list(reader)
    # The source text omits a suffix. Attach UTC because the pinned README
    # explicitly declares UTC and the updater uses/stores UTC timestamps.
    parsed = [datetime.fromisoformat(row["datetime"]) for row in rows]
    if any(ts.tzinfo is not None for ts in parsed):
        raise ValueError("Timestamp lexical schema changed from documented naive UTC strings")
    stamps = [ts.replace(tzinfo=timezone.utc) for ts in parsed]
    readme = OUT / "source/source_repository_README.md"
    updater = OUT / "source/source_repository_update_data.py"
    if 'All timestamps are in UTC.' not in readme.read_text() or '"NQ":  "CON.F.US.ENQ.M26"' not in updater.read_text():
        raise ValueError("Retained source provenance text does not match inspected declarations")
    gaps = observed_gaps(stamps)
    receipt = {
        "scope": "Source-only audit, including reserved April source QA; no signals, trading outcomes, strategy selection, or P&L computed.",
        "source_commit": COMMIT,
        "instrument": "NQ / E-mini Nasdaq-100; actual NQ source, not MNQ. Tick size checked at 0.25 index points.",
        "source_url": BASE_URL + "/NQ/NQ_5min_20260120_20260415.csv",
        "source_path": str(SOURCE.relative_to(ROOT)), "m5_sha256": SHA256,
        "source_bytes": SOURCE.stat().st_size,
        "download_transport": "curl --fail --location --proto '=https' --tlsv1.2; normal certificate and hostname verification retained; no insecure flag used.",
        "raw_csv_preserved_exactly": True,
        "schema": {"datetime": "ISO8601 text without timezone suffix; audited datetime64-style UTC semantics", "open": "decimal-compatible positive numeric text", "high": "decimal-compatible positive numeric text", "low": "decimal-compatible positive numeric text", "close": "decimal-compatible positive numeric text", "volume": "finite nonnegative integer-compatible numeric text"},
        "audited_dtypes": {"raw_csv_reader": {column: "str" for column in COLUMNS}, "parsed_timestamp": "datetime.datetime with datetime.timezone.utc", "parsed_ohlc": "decimal.Decimal, exact for quarter-point tick audit", "parsed_volume": "decimal.Decimal with integer-valued assertion; safe integral conversion"},
        "timestamp_timezone": {"csv_has_timezone_suffix": False, "declared_timezone": "UTC", "basis": "README.md:122; update_data.py:122-123,165,245. UTC attached rather than local-time conversion.", "timestamp_parse_failures": 0, "bar_label_semantics": "Source calls records bars but does not independently establish start-versus-end label; strategy execution must freeze an explicit convention."},
        "source_provenance": {
            "readme_sha256": sha256(readme), "updater_sha256": sha256(updater),
            "readme_url": BASE_URL + "/README.md", "updater_url": BASE_URL + "/update_data.py",
            "readme_instrument_line": 18, "readme_timezone_line": 122, "readme_provider_line": 157,
            "provider_claim": "TopstepX via ProjectX Gateway API; public mirror, not independently reconciled exchange feed",
            "updater_contract_declaration": "NQ -> CON.F.US.ENQ.M26 (June 2026), update_data.py:32-41",
            "historical_native_contract_identity": "UNVERIFIED: updater appends its current mapping to existing CSVs and absent-file fallback retrieves only three days; no per-row contract ID, original backfill receipt, or documented roll/back-adjustment policy.",
            "downloaded_source_code_executed": False,
        },
        "global_quality": profile(rows, stamps),
        "native_five_minute_gap_audit": {
            "definition": "Every adjacent observed-bar interval greater than five minutes; absent grid slots here include documented clock-shaped market closures and are not all feed defects.",
            "gap_events": len(gaps),
            "classifications": dict(sorted(Counter(g["classification"] for g in gaps).items())),
            "unclassified_gap_events": sum(g["classification"].startswith("unclassified") for g in gaps),
            "gaps": gaps,
        },
        "split_source_quality": {name: split_coverage(rows, stamps, start, end) for name, (start, end) in SPLITS.items()},
        "predetermined_exclusion": {"entire_march_roll_month": True, "date_range": ["2026-03-01", "2026-03-31"], "reason": "Contract/backfill/roll provenance uncertainty; exclusion is not evidence that contract identity is verified."},
        "findings": [
            {"severity": "high", "confidence": "high", "issue": "Historical native contract/backfill identity unverified", "impact": "Do not claim all rows are a proven single native NQ contract or a verified continuous series.", "remediation": "Obtain provider historical contract identifiers/raw receipts or limit interpretation to the pinned public NQ mirror with explicit provenance caveat."},
            {"severity": "medium", "confidence": "high", "issue": "Feb16 and Apr3 are partial under the ordinary-session baseline", "impact": "Their 16:50 New York daily-flat quotes are absent; whole-session eligibility must exclude these dates or use an independently verified holiday close convention.", "remediation": "Preserve these source rows; explicitly freeze holiday exclusions before strategy work. The source audit does not independently verify the exchange holiday schedule."},
            {"severity": "low", "confidence": "high", "issue": "One additional 17:00 New York March18 bar lies outside the ordinary-session baseline", "impact": "March is already excluded from strategy splits.", "remediation": "Retain exact raw source and document the extra boundary bar rather than silently deleting it."},
        ],
        "final_outcomes": "UNTOUCHED",
        "strategy_signals_constructed": False,
        "strategy_pnl_computed": False,
    }
    (OUT / "source_quality_receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"source_sha256": SHA256, "quality": receipt["global_quality"],
                      "gap_classifications": receipt["native_five_minute_gap_audit"]["classifications"],
                      "splits": {name: {key: value[key] for key in ("ordinary_weekday_session_count", "complete_ordinary_sessions", "partial_ordinary_session_dates", "ordinary_session_missing_slots", "missing_scheduled_1650_quote_session_dates")} for name, value in receipt["split_source_quality"].items()}}, indent=2))


if __name__ == "__main__":
    main()
