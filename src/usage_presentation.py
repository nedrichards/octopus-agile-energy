"""Pure Usage presentation preparation, run before updating GTK widgets."""
from .price_formatting import format_gbp
from .uk_time import is_complete_usage_day
from .usage_insights import build_rolling_average


def get_complete_daily_costs(daily_costs, synced_at):
    complete_daily_costs = []
    for day in daily_costs:
        if day.get("missing_rate_count", 0) != 0 or not is_complete_usage_day(
            day.get("date"),
            day.get("sample_count", 0),
            synced_at,
        ):
            continue

        complete_daily_costs.append(day)

    return complete_daily_costs


def get_series_trend_pct(values):
    if len(values) < 14:
        return None
    recent = values[-7:]
    previous = values[-14:-7]
    recent_avg = sum(recent) / len(recent)
    previous_avg = sum(previous) / len(previous)
    if previous_avg == 0:
        return 0.0
    return max(-100.0, min(100.0, ((recent_avg - previous_avg) / previous_avg) * 100.0))


def add_usage_cost_insights(insight, synced_at, daily_costs, avg_unit_price, standing_charge_gbp):
    insight = dict(insight)
    avg_daily = 0.0
    if insight["avg_text"] != "—":
        avg_daily = float(insight["avg_text"].split(" ")[0])

    if daily_costs:
        complete_daily_costs = get_complete_daily_costs(daily_costs, synced_at)
        if complete_daily_costs:
            energy_totals = [float(day.get("energy_cost_gbp", 0.0)) for day in complete_daily_costs]
            totals = [float(day.get("total_cost_gbp", 0.0)) for day in complete_daily_costs]
            avg_daily_energy_cost = sum(energy_totals) / len(energy_totals)
            avg_daily_cost = sum(totals) / len(totals)
            monthly_cost = avg_daily_cost * 30.0
            cost_trend_pct = get_series_trend_pct(totals)
            insight["daily_cost_text"] = f"{format_gbp(avg_daily_energy_cost)}/day"
            insight["daily_total_cost_text"] = f"{format_gbp(avg_daily_cost)}/day"
            insight["cost_trend_text"] = "—" if cost_trend_pct is None else f"{cost_trend_pct:+.1f}%"
            insight["monthly_cost_text"] = format_gbp(monthly_cost, decimals=0)
            return insight

    avg_daily_energy_cost = avg_daily * avg_unit_price
    avg_daily_total_cost = avg_daily_energy_cost + standing_charge_gbp
    monthly_cost = avg_daily_total_cost * 30.0
    insight["daily_cost_text"] = "—" if insight["avg_text"] == "—" else f"{format_gbp(avg_daily_energy_cost)}/day"
    insight["daily_total_cost_text"] = "—" if insight["avg_text"] == "—" else f"{format_gbp(avg_daily_total_cost)}/day"
    insight["cost_trend_text"] = "—"
    insight["monthly_cost_text"] = "—" if insight["monthly_text"] == "—" else format_gbp(monthly_cost, decimals=0)
    return insight


def get_usage_chart_series(insight, daily_costs, period_mode="recent", graph_mode="kwh"):
    if period_mode != "recent":
        seasonal = insight.get("seasonal", {})
        month_limit = {
            "12-months": 12,
            "24-months": 24,
            "5-years": 60,
        }.get(period_mode, 12)
        months = seasonal.get("chart_months", [])[-month_limit:]
        points = [float(month.get("average_kwh", 0.0)) for month in months]
        dates = [month.get("month_start") for month in months]
        daily_data = [
            {
                "date": month.get("month_start"),
                "kwh": month.get("average_kwh"),
                "day_count": month.get("day_count"),
                "expected_days": month.get("expected_days"),
                "is_month": True,
            }
            for month in months
        ]
        return (
            points,
            dates,
            "kWh",
            daily_data,
            build_rolling_average(points, window_size=3) if points else [],
        )

    daily_cost_by_date = {
        day.get("date"): day
        for day in daily_costs
        if day.get("date")
    }

    if graph_mode == "kwh":
        daily_data = []
        for date, kwh in zip(insight["chart_dates"], insight["chart_points"], strict=True):
            day = daily_cost_by_date.get(date, {})
            daily_data.append({
                "date": date,
                "kwh": kwh,
                "energy_cost_gbp": day.get("energy_cost_gbp"),
                "total_cost_gbp": day.get("total_cost_gbp"),
                "standing_charge_gbp": day.get("standing_charge_gbp"),
                "missing_rate_count": day.get("missing_rate_count"),
                "sample_count": day.get("sample_count"),
            })
        return (
            list(insight["chart_points"]),
            list(insight["chart_dates"]),
            "kWh",
            daily_data,
            list(insight.get("chart_rolling_average", [])),
        )

    points = []
    dates = []
    daily_data = []
    for date in insight["chart_dates"]:
        day = daily_cost_by_date.get(date)
        if (
            not day
            or day.get("missing_rate_count", 0) != 0
            or not is_complete_usage_day(date, day.get("sample_count", 0))
        ):
            continue
        points.append(float(day.get(graph_mode, 0.0)))
        dates.append(date)
        daily_data.append(day)

    return (
        points,
        dates,
        "£",
        daily_data,
        build_rolling_average(points),
    )
