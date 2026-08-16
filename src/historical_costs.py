from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timedelta, timezone

from .price_bands import (
    PRICE_BAND_HIGH,
    PRICE_BAND_LOW,
    PRICE_BAND_NEGATIVE,
    PRICE_BAND_VERSION,
    get_price_band,
)
from .uk_time import UK_TIMEZONE


def parse_octopus_datetime(value):
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


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
    tariff_lookup = _prepare_tariff_lookup(tariff_periods)
    rates_lookup = {
        tariff_code: _prepare_record_lookup(records)
        for tariff_code, records in rates_by_tariff.items()
    }
    standing_charge_lookup = {
        tariff_code: _prepare_record_lookup(records)
        for tariff_code, records in standing_charges_by_tariff.items()
    }

    for sample in samples:
        start = parse_octopus_datetime(sample.get("interval_start"))
        if not start:
            continue

        try:
            consumption = float(sample.get("consumption", 0.0))
        except (TypeError, ValueError):
            continue

        day_key = start.astimezone(UK_TIMEZONE).date().isoformat()
        day = daily.setdefault(
            day_key,
            {
                "date": day_key,
                "kwh": 0.0,
                "energy_cost_gbp": 0.0,
                "standing_charge_gbp": 0.0,
                "total_cost_gbp": 0.0,
                "matched_kwh": 0.0,
                "cheap_kwh": 0.0,
                "negative_kwh": 0.0,
                "high_kwh": 0.0,
                "price_band_version": PRICE_BAND_VERSION,
                "missing_rate_count": 0,
                "sample_count": 0,
            },
        )
        day["kwh"] += consumption
        day["sample_count"] += 1

        tariff_code = _find_tariff_code(tariff_lookup, start)
        rate = _find_record(rates_lookup.get(tariff_code, []), start) if tariff_code else None
        if not rate:
            day["missing_rate_count"] += 1
            continue

        unit_rate_gbp = float(rate.get("value_inc_vat", 0.0)) / 100.0
        price_band = get_price_band(unit_rate_gbp)
        day["matched_kwh"] += consumption
        if price_band == PRICE_BAND_NEGATIVE:
            day["negative_kwh"] += consumption
        if price_band in (PRICE_BAND_NEGATIVE, PRICE_BAND_LOW):
            day["cheap_kwh"] += consumption
        if price_band == PRICE_BAND_HIGH:
            day["high_kwh"] += consumption
        day["energy_cost_gbp"] += consumption * unit_rate_gbp

    for day_key, day in daily.items():
        midday = datetime.fromisoformat(day_key).replace(hour=12, tzinfo=UK_TIMEZONE)
        tariff_code = _find_tariff_code(tariff_lookup, midday)
        standing_charge = (
            _find_record(standing_charge_lookup.get(tariff_code, []), midday)
            if tariff_code
            else None
        )
        if standing_charge:
            day["standing_charge_gbp"] = float(standing_charge.get("value_inc_vat", 0.0)) / 100.0
        day["total_cost_gbp"] = day["energy_cost_gbp"] + day["standing_charge_gbp"]

    return [daily[key] for key in sorted(daily)]


def _prepare_tariff_lookup(tariff_periods):
    prepared = []
    for period in tariff_periods:
        valid_from = period.get("valid_from")
        valid_to = period.get("valid_to") or datetime.max.replace(tzinfo=timezone.utc)
        tariff_code = period.get("tariff_code")
        if valid_from and tariff_code:
            prepared.append((valid_from, valid_to, tariff_code))
    ranges = sorted(prepared, key=lambda item: item[0])
    return [record[0] for record in ranges], ranges


def _prepare_record_lookup(records):
    prepared = []
    for record in records:
        valid_from = parse_octopus_datetime(record.get("valid_from"))
        valid_to = parse_octopus_datetime(record.get("valid_to")) or datetime.max.replace(tzinfo=timezone.utc)
        if valid_from:
            prepared.append((valid_from, valid_to, record))
    ranges = sorted(prepared, key=lambda item: item[0])
    return [record[0] for record in ranges], ranges


def _find_tariff_code(tariff_periods, target):
    return _find_range_value(tariff_periods, target)


def _find_record(records, target):
    return _find_range_value(records, target)


def _find_range_value(records, target):
    if not records or not records[0]:
        return None

    starts, ranges = records
    index = bisect_right(starts, target) - 1
    if index < 0:
        return None

    valid_from, valid_to, value = ranges[index]
    if valid_from <= target < valid_to:
        return value
    return None
