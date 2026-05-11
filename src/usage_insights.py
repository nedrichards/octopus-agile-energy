from __future__ import annotations

from datetime import datetime, timedelta, timezone

SAMPLES_PER_COMPLETE_DAY = 48


def build_usage_insight_data(samples: list[dict], synced_at: str | None):
    if not samples:
        return _empty("No usage samples available yet.")

    daily_totals = {}
    daily_sample_counts = {}
    for sample in samples:
        interval_start = sample.get("interval_start")
        consumption = sample.get("consumption")
        if interval_start is None or consumption is None:
            continue
        try:
            start_dt = datetime.fromisoformat(interval_start.replace("Z", "+00:00"))
            day_key = start_dt.date().isoformat()
            daily_totals[day_key] = daily_totals.get(day_key, 0.0) + float(consumption)
            daily_sample_counts[day_key] = daily_sample_counts.get(day_key, 0) + 1
        except (TypeError, ValueError):
            continue

    if len(daily_totals) < 7:
        return _empty("Not enough usage data yet (need at least seven days).")

    sorted_days = sorted(daily_totals.items(), key=lambda x: x[0])
    day_keys = [day for day, _ in sorted_days]
    values = [value for _day, value in sorted_days]
    avg_daily = sum(values) / len(values)
    complete_days = _get_complete_days(sorted_days, daily_sample_counts, synced_at)
    trend_pct = _get_seven_day_trend_pct([value for _day, value in complete_days])
    if trend_pct is not None:
        trend_pct = max(-100.0, min(100.0, trend_pct))

    data_coverage = "high" if len(values) >= 60 else "medium" if len(values) >= 21 else "low"
    based_on = f" Based on data up to {synced_at[:10]}." if synced_at else ""
    coverage_note = " Data coverage: low." if data_coverage == "low" else ""
    if trend_pct is None:
        summary = f"Seven-day trend needs 14 complete days of data.{based_on}{coverage_note}"
    else:
        summary = (
            f"Consumption is {'rising' if trend_pct > 1 else 'falling' if trend_pct < -1 else 'steady'} over the last week."
            f"{based_on}{coverage_note}"
        )

    return {
        "summary": summary,
        "avg_text": f"{avg_daily:.2f} kWh/day",
        "trend_text": "—" if trend_pct is None else f"{trend_pct:+.1f}%",
        "monthly_text": f"{(avg_daily * 30.0):.0f} kWh",
        "chart_points": values[-90:],
        "chart_dates": day_keys[-90:],
        "trend_pct": trend_pct or 0.0,
    }


def _empty(summary: str):
    return {
        "summary": summary,
        "avg_text": "—",
        "trend_text": "—",
        "monthly_text": "—",
        "chart_points": [],
        "chart_dates": [],
        "trend_pct": 0.0,
    }


def _get_complete_days(sorted_days, daily_sample_counts, synced_at):
    if not sorted_days:
        return []

    latest_complete_day = None
    if synced_at:
        try:
            synced_dt = datetime.fromisoformat(synced_at.replace("Z", "+00:00"))
            if synced_dt.tzinfo is None:
                synced_dt = synced_dt.replace(tzinfo=timezone.utc)
            latest_complete_day = synced_dt.astimezone(timezone.utc).date()
            if synced_dt.time() != datetime.min.time():
                latest_complete_day = latest_complete_day - timedelta(days=1)
        except (TypeError, ValueError):
            latest_complete_day = None

    complete_days = []
    for day_key, value in sorted_days:
        day_date = datetime.fromisoformat(day_key).date()
        if latest_complete_day and day_date > latest_complete_day:
            continue
        if daily_sample_counts.get(day_key, 0) >= SAMPLES_PER_COMPLETE_DAY:
            complete_days.append((day_key, value))

    return complete_days


def _get_seven_day_trend_pct(complete_values):
    if len(complete_values) < 14:
        return None

    recent_7 = complete_values[-7:]
    previous_7 = complete_values[-14:-7]
    recent_avg = sum(recent_7) / len(recent_7)
    previous_avg = sum(previous_7) / len(previous_7)
    if previous_avg == 0:
        return 0.0

    return ((recent_avg - previous_avg) / previous_avg) * 100.0
