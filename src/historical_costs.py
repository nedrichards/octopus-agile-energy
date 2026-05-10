from __future__ import annotations

from datetime import datetime, timedelta, timezone


def parse_octopus_datetime(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def build_tariff_periods(account_data, period_start, period_end):
    periods = []
    seen = set()

    for property_data in account_data.get("properties", []):
        for meter_point in property_data.get("electricity_meter_points", []):
            for agreement in meter_point.get("agreements", []):
                tariff_code = agreement.get("tariff_code")
                valid_from = parse_octopus_datetime(agreement.get("valid_from"))
                valid_to = parse_octopus_datetime(agreement.get("valid_to")) or period_end
                if not tariff_code or not valid_from:
                    continue

                start = max(valid_from, period_start)
                end = min(valid_to, period_end)
                if start >= end:
                    continue

                key = (tariff_code, start.isoformat(), end.isoformat())
                if key in seen:
                    continue
                seen.add(key)
                periods.append({"tariff_code": tariff_code, "valid_from": start, "valid_to": end})

    return sorted(periods, key=lambda period: period["valid_from"])


def get_usage_period(samples):
    starts = []
    ends = []
    for sample in samples:
        start = parse_octopus_datetime(sample.get("interval_start"))
        if not start:
            continue

        end = parse_octopus_datetime(sample.get("interval_end"))
        if not end:
            end = start + timedelta(minutes=30)
        starts.append(start)
        ends.append(end)

    if not starts or not ends:
        return None, None

    return min(starts), max(ends)


def build_daily_costs(samples, tariff_periods, rates_by_tariff, standing_charges_by_tariff):
    daily = {}

    for sample in samples:
        start = parse_octopus_datetime(sample.get("interval_start"))
        if not start:
            continue

        try:
            consumption = float(sample.get("consumption", 0.0))
        except (TypeError, ValueError):
            continue

        day_key = start.date().isoformat()
        day = daily.setdefault(
            day_key,
            {
                "date": day_key,
                "kwh": 0.0,
                "energy_cost_gbp": 0.0,
                "standing_charge_gbp": 0.0,
                "total_cost_gbp": 0.0,
                "missing_rate_count": 0,
                "sample_count": 0,
            },
        )
        day["kwh"] += consumption
        day["sample_count"] += 1

        tariff_code = _find_tariff_code(tariff_periods, start)
        rate = _find_record(rates_by_tariff.get(tariff_code, []), start) if tariff_code else None
        if not rate:
            day["missing_rate_count"] += 1
            continue

        day["energy_cost_gbp"] += consumption * (float(rate.get("value_inc_vat", 0.0)) / 100.0)

    for day_key, day in daily.items():
        midday = datetime.fromisoformat(day_key).replace(hour=12, tzinfo=timezone.utc)
        tariff_code = _find_tariff_code(tariff_periods, midday)
        standing_charge = (
            _find_record(standing_charges_by_tariff.get(tariff_code, []), midday)
            if tariff_code
            else None
        )
        if standing_charge:
            day["standing_charge_gbp"] = float(standing_charge.get("value_inc_vat", 0.0)) / 100.0
        day["total_cost_gbp"] = day["energy_cost_gbp"] + day["standing_charge_gbp"]

    return [daily[key] for key in sorted(daily)]


def _find_tariff_code(tariff_periods, target):
    for period in tariff_periods:
        if period["valid_from"] <= target < period["valid_to"]:
            return period["tariff_code"]
    return None


def _find_record(records, target):
    for record in records:
        valid_from = parse_octopus_datetime(record.get("valid_from"))
        valid_to = parse_octopus_datetime(record.get("valid_to")) or datetime.max.replace(tzinfo=timezone.utc)
        if valid_from and valid_from <= target < valid_to:
            return record
    return None
