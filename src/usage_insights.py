from __future__ import annotations

from datetime import datetime


def build_usage_insight_data(samples: list[dict], synced_at: str | None):
    if not samples:
        return _empty("No usage samples available yet.")

    daily_totals = {}
    for sample in samples:
        interval_start = sample.get("interval_start")
        consumption = sample.get("consumption")
        if interval_start is None or consumption is None:
            continue
        try:
            start_dt = datetime.fromisoformat(interval_start.replace("Z", "+00:00"))
            day_key = start_dt.date().isoformat()
            daily_totals[day_key] = daily_totals.get(day_key, 0.0) + float(consumption)
        except (TypeError, ValueError):
            continue

    if len(daily_totals) < 7:
        return _empty("Not enough usage data yet (need at least seven days).")

    sorted_days = sorted(daily_totals.items(), key=lambda x: x[0])
    day_keys = [day for day, _ in sorted_days]
    values = [value for _day, value in sorted_days]
    avg_daily = sum(values) / len(values)
    recent_7 = values[-7:]
    previous_7 = values[-14:-7] if len(values) >= 14 else []
    recent_avg = sum(recent_7) / len(recent_7)
    previous_avg = (sum(previous_7) / len(previous_7)) if previous_7 else recent_avg
    trend_pct = 0.0 if previous_avg == 0 else ((recent_avg - previous_avg) / previous_avg) * 100.0
    trend_pct = max(-100.0, min(100.0, trend_pct))
    trend_strength = min(100.0, abs(trend_pct) * 2.0)

    confidence = "high" if len(values) >= 60 else "medium" if len(values) >= 21 else "low"
    based_on = f" Based on data up to {synced_at[:10]}." if synced_at else ""
    summary = (
        f"Consumption is {'rising' if trend_pct > 1 else 'falling' if trend_pct < -1 else 'steady'} over the last week."
        f"{based_on} Confidence: {confidence}."
    )

    return {
        "summary": summary,
        "avg_text": f"{avg_daily:.2f} kWh/day",
        "trend_text": f"{trend_pct:+.1f}%",
        "monthly_text": f"{(avg_daily * 30.0):.0f} kWh",
        "trend_strength": trend_strength,
        "chart_points": values[-90:],
        "chart_dates": day_keys[-90:],
        "trend_pct": trend_pct,
    }


def _empty(summary: str):
    return {
        "summary": summary,
        "avg_text": "—",
        "trend_text": "—",
        "monthly_text": "—",
        "trend_strength": 0.0,
        "chart_points": [],
        "chart_dates": [],
        "trend_pct": 0.0,
    }
