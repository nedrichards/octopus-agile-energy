from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta, timezone

from .uk_time import UK_TIMEZONE, latest_complete_local_day

USAGE_ARCHIVE_DAYS = 5 * 366
SEASONAL_COMPARISON_DAYS = 28
MIN_COMPARISON_COVERAGE_DAYS = 24


def build_daily_usage_archive(samples: list[dict]) -> list[dict]:
    """Collapse half-hourly or API-grouped consumption records into GB days."""
    totals = {}
    for sample in samples:
        interval_start = sample.get("interval_start")
        consumption = sample.get("consumption")
        if interval_start is None or consumption is None:
            continue
        try:
            start = datetime.fromisoformat(interval_start.replace("Z", "+00:00"))
            if start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            day_key = start.astimezone(UK_TIMEZONE).date().isoformat()
            totals[day_key] = totals.get(day_key, 0.0) + float(consumption)
        except (TypeError, ValueError):
            continue

    return [
        {"date": day_key, "kwh": totals[day_key]}
        for day_key in sorted(totals)
    ]


def merge_daily_usage_archive(cached_archive, fresh_archive, now=None):
    now = now or datetime.now(timezone.utc)
    cutoff = now.astimezone(UK_TIMEZONE).date() - timedelta(days=USAGE_ARCHIVE_DAYS)
    by_date = {}
    for record in [*(cached_archive or []), *(fresh_archive or [])]:
        try:
            day = date.fromisoformat(record.get("date", ""))
            kwh = float(record.get("kwh"))
        except (TypeError, ValueError):
            continue
        if day >= cutoff:
            by_date[day] = {"date": day.isoformat(), "kwh": kwh}
    return [by_date[day] for day in sorted(by_date)]


def build_seasonal_usage_insight(daily_archive, synced_at):
    latest_complete = latest_complete_local_day(synced_at)
    by_date = _parse_archive(daily_archive, latest_complete)
    if not by_date:
        return _empty("Seasonal history will appear after usage has been refreshed.")

    monthly = _build_monthly_series(by_date)
    latest_day = latest_complete or max(by_date)
    recent_start = latest_day - timedelta(days=SEASONAL_COMPARISON_DAYS - 1)
    previous_start = _shift_year(recent_start, -1)
    previous_end = _shift_year(latest_day, -1)
    recent_values = _window_values(by_date, recent_start, latest_day)
    previous_values = _window_values(by_date, previous_start, previous_end)

    recent_average = _average(recent_values)
    previous_average = _average(previous_values)
    comparison_pct = None
    if (
        len(recent_values) >= MIN_COMPARISON_COVERAGE_DAYS
        and len(previous_values) >= MIN_COMPARISON_COVERAGE_DAYS
        and previous_average
    ):
        comparison_pct = ((recent_average - previous_average) / previous_average) * 100

    annual_start = latest_day - timedelta(days=364)
    annual_values = _window_values(by_date, annual_start, latest_day)
    annual_average = _average(annual_values)
    coverage_days = len(annual_values)
    coverage_text = f"{coverage_days} complete days in the last year"
    if comparison_pct is None:
        comparison_text = "Available after a matching period last year"
    else:
        direction = "higher" if comparison_pct > 1 else "lower" if comparison_pct < -1 else "similar"
        comparison_text = f"{abs(comparison_pct):.0f}% {direction} than the same period last year"

    return {
        "summary": comparison_text,
        "recent_average_text": "—" if recent_average is None else f"{recent_average:.2f} kWh/day",
        "year_comparison_text": "—" if comparison_pct is None else f"{comparison_pct:+.1f}%",
        "annual_average_text": "—" if annual_average is None else f"{annual_average:.2f} kWh/day",
        "annual_average": annual_average,
        "coverage_text": coverage_text,
        "comparison_pct": comparison_pct,
        "chart_points": [month["average_kwh"] for month in monthly],
        "chart_dates": [month["month_start"] for month in monthly],
        "chart_months": monthly,
    }


def _parse_archive(daily_archive, latest_complete):
    by_date = {}
    for record in daily_archive or []:
        try:
            day = date.fromisoformat(record.get("date", ""))
            kwh = float(record.get("kwh"))
        except (TypeError, ValueError):
            continue
        if latest_complete is None or day <= latest_complete:
            by_date[day] = kwh
    return by_date


def _build_monthly_series(by_date):
    grouped = {}
    for day, value in sorted(by_date.items()):
        grouped.setdefault((day.year, day.month), []).append(value)

    monthly = []
    for (year, month), values in grouped.items():
        expected_days = calendar.monthrange(year, month)[1]
        monthly.append({
            "month_start": date(year, month, 1).isoformat(),
            "average_kwh": sum(values) / len(values),
            "day_count": len(values),
            "expected_days": expected_days,
        })
    return monthly


def _window_values(by_date, start, end):
    return [value for day, value in by_date.items() if start <= day <= end]


def _average(values):
    return sum(values) / len(values) if values else None


def _shift_year(day, offset):
    try:
        return day.replace(year=day.year + offset)
    except ValueError:
        return day.replace(year=day.year + offset, day=28)


def _empty(summary):
    return {
        "summary": summary,
        "recent_average_text": "—",
        "year_comparison_text": "—",
        "annual_average_text": "—",
        "annual_average": None,
        "coverage_text": "No complete seasonal history yet",
        "comparison_pct": None,
        "chart_points": [],
        "chart_dates": [],
        "chart_months": [],
    }
