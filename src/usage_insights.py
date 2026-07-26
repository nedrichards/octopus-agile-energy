from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .price_bands import (
    HIGH_PRICE_THRESHOLD_GBP,
    LOW_PRICE_THRESHOLD_GBP,
    PRICE_BAND_VERSION,
    format_price_threshold,
)

SAMPLES_PER_COMPLETE_DAY = 48
USAGE_BANDS = (
    ("Overnight", 0, 6),
    ("Morning", 6, 12),
    ("Afternoon", 12, 17),
    ("Evening", 17, 22),
    ("Late evening", 22, 24),
)


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
        "chart_rolling_average": build_rolling_average(values[-90:]),
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
        "chart_rolling_average": [],
        "trend_pct": 0.0,
    }


def build_rolling_average(values: list[float], window_size: int = 7) -> list[float]:
    if window_size <= 0:
        raise ValueError("window_size must be positive")

    rolling = []
    for index, _value in enumerate(values):
        window = values[max(0, index - window_size + 1):index + 1]
        rolling.append(sum(window) / len(window))
    return rolling


def build_usage_pattern_insights(samples: list[dict], daily_costs: list[dict] | None = None):
    baseline = _build_always_on_baseline(samples)
    peak = _build_peak_usage_pattern(samples)
    rate_capture = _build_rate_capture(daily_costs or [])
    return {
        "baseline_text": baseline["text"],
        "baseline_detail": baseline["detail"],
        "peak_text": peak["text"],
        "peak_detail": peak["detail"],
        "cheap_rate_text": rate_capture["cheap_rate_text"],
        "cheap_rate_detail": rate_capture["cheap_rate_detail"],
        "average_unit_text": rate_capture["average_unit_text"],
        "average_unit_detail": rate_capture["average_unit_detail"],
    }


def _build_always_on_baseline(samples: list[dict]):
    daily_slots = _daily_complete_slots(samples)
    if len(daily_slots) < 7:
        return _insight_empty("Needs seven complete days of usage data.")

    daily_minimums = [
        min(slot["consumption"] for slot in slots)
        for _day, slots in daily_slots[-30:]
    ]
    if not daily_minimums:
        return _insight_empty("Needs complete half-hour usage data.")

    typical_half_hour_kwh = _median(daily_minimums)
    watts = round(typical_half_hour_kwh * 2 * 1000)
    daily_kwh = typical_half_hour_kwh * 48
    return {
        "text": f"~{watts} W",
        "detail": f"Lowest regular half-hour load suggests about {daily_kwh:.1f} kWh/day before active use.",
    }


def _build_peak_usage_pattern(samples: list[dict]):
    parsed_samples = _parse_samples(samples)
    if not parsed_samples:
        return _insight_empty("Needs usage samples.")

    band_totals = {name: 0.0 for name, _start, _end in USAGE_BANDS}
    slot_totals = {}
    total_kwh = 0.0
    for sample in parsed_samples:
        local_start = sample["start"].astimezone()
        consumption = sample["consumption"]
        total_kwh += consumption
        band_totals[_band_for_hour(local_start.hour)] += consumption
        slot_key = local_start.strftime("%H:%M")
        slot_totals[slot_key] = slot_totals.get(slot_key, 0.0) + consumption

    if total_kwh <= 0:
        return _insight_empty("Needs non-zero usage samples.")

    peak_band, peak_band_kwh = max(band_totals.items(), key=lambda item: item[1])
    peak_share = (peak_band_kwh / total_kwh) * 100
    peak_slot, _slot_kwh = max(slot_totals.items(), key=lambda item: item[1])
    peak_slot_end = _format_half_hour_end(peak_slot)
    return {
        "text": f"{peak_band} ({peak_share:.0f}%)",
        "detail": f"Most-used half-hour is usually {peak_slot}-{peak_slot_end}.",
    }


def _build_rate_capture(daily_costs: list[dict]):
    complete_days = [
        day for day in daily_costs
        if day.get("sample_count", 0) >= SAMPLES_PER_COMPLETE_DAY and day.get("missing_rate_count", 0) == 0
    ]
    matched_kwh = sum(float(day.get("matched_kwh", day.get("kwh", 0.0)) or 0.0) for day in complete_days)
    if matched_kwh <= 0:
        empty = _insight_empty("Needs matched historical rates.")
        return {
            "cheap_rate_text": empty["text"],
            "cheap_rate_detail": empty["detail"],
            "average_unit_text": empty["text"],
            "average_unit_detail": empty["detail"],
        }

    has_price_band_data = all(
        day.get("price_band_version") == PRICE_BAND_VERSION
        and "matched_kwh" in day
        and "cheap_kwh" in day
        and "high_kwh" in day
        and "negative_kwh" in day
        for day in complete_days
    )
    cheap_kwh = sum(float(day.get("cheap_kwh", 0.0) or 0.0) for day in complete_days)
    negative_kwh = sum(float(day.get("negative_kwh", 0.0) or 0.0) for day in complete_days)
    high_kwh = sum(float(day.get("high_kwh", 0.0) or 0.0) for day in complete_days)
    energy_cost = sum(float(day.get("energy_cost_gbp", 0.0) or 0.0) for day in complete_days)

    average_unit_pence = (energy_cost / matched_kwh) * 100
    if not has_price_band_data:
        return {
            "cheap_rate_text": "—",
            "cheap_rate_detail": "Refresh usage history to classify cheap-rate usage.",
            "average_unit_text": f"{average_unit_pence:.1f}p/kWh",
            "average_unit_detail": "Effective energy rate across matched days.",
        }

    cheap_share = (cheap_kwh / matched_kwh) * 100
    high_share = (high_kwh / matched_kwh) * 100
    negative_detail = (
        f" Includes {negative_kwh:.1f} kWh during negative prices."
        if negative_kwh > 0.05
        else ""
    )
    return {
        "cheap_rate_text": f"{cheap_share:.0f}%",
        "cheap_rate_detail": (
            f"{cheap_kwh:.1f} of {matched_kwh:.1f} kWh landed below "
            f"{format_price_threshold(LOW_PRICE_THRESHOLD_GBP)}."
            f"{negative_detail}"
        ),
        "average_unit_text": f"{average_unit_pence:.1f}p/kWh",
        "average_unit_detail": (
            f"Effective energy rate across matched days; {high_share:.0f}% of usage was at "
            f"{format_price_threshold(HIGH_PRICE_THRESHOLD_GBP)} or above."
        ),
    }


def _daily_complete_slots(samples: list[dict]):
    slots_by_day = {}
    for sample in _parse_samples(samples):
        day_key = sample["start"].astimezone().date().isoformat()
        slots_by_day.setdefault(day_key, []).append(sample)

    complete = [
        (day_key, slots)
        for day_key, slots in sorted(slots_by_day.items())
        if len(slots) >= SAMPLES_PER_COMPLETE_DAY
    ]
    return complete


def _parse_samples(samples: list[dict]):
    parsed = []
    for sample in samples:
        interval_start = sample.get("interval_start")
        consumption = sample.get("consumption")
        if interval_start is None or consumption is None:
            continue
        try:
            parsed.append({
                "start": datetime.fromisoformat(interval_start.replace("Z", "+00:00")),
                "consumption": float(consumption),
            })
        except (TypeError, ValueError):
            continue
    return parsed


def _band_for_hour(hour: int):
    for name, start, end in USAGE_BANDS:
        if start <= hour < end:
            return name
    return USAGE_BANDS[-1][0]


def _format_half_hour_end(start_text: str):
    start = datetime.strptime(start_text, "%H:%M").replace(tzinfo=timezone.utc)
    return (start + timedelta(minutes=30)).strftime("%H:%M")


def _median(values):
    sorted_values = sorted(values)
    midpoint = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[midpoint]
    return (sorted_values[midpoint - 1] + sorted_values[midpoint]) / 2


def _insight_empty(detail: str):
    return {"text": "—", "detail": detail}


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
