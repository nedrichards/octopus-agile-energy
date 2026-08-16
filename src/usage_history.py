import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlencode

import requests

from .historical_costs import build_daily_costs, build_tariff_periods, get_usage_period
from .octopus_api import OctopusApiError, get_json
from .price_bands import PRICE_BAND_VERSION
from .price_logic import build_dual_register_price_windows, extract_product_code
from .uk_time import UK_TIMEZONE

logger = logging.getLogger(__name__)
USAGE_HISTORY_DAYS = 120
USAGE_REFRESH_OVERLAP_DAYS = 7
USAGE_CACHE_VERSION = 2
ACCOUNT_NUMBER_PATTERN = re.compile(r"A-[A-Z0-9]+", re.IGNORECASE)


def get_account_data(account_number):
    account_number = account_number.strip()
    if not account_number:
        raise OctopusApiError("Missing account number.")
    if not ACCOUNT_NUMBER_PATTERN.fullmatch(account_number):
        raise OctopusApiError("The account number format is invalid.")

    return get_json(
        f"https://api.octopus.energy/v1/accounts/{quote(account_number, safe='')}/",
        use_api_key=True,
        timeout=10,
    )


def fetch_recent_usage_samples(account_data, period_from=None, now=None):
    now = now or datetime.now(timezone.utc)
    if period_from is None:
        period_from = now - timedelta(days=USAGE_HISTORY_DAYS)
    period_from_text = _format_octopus_datetime(period_from)

    for property_data in account_data.get("properties", []):
        for meter_point in property_data.get("electricity_meter_points", []):
            if not _has_active_agreement(meter_point, now):
                continue

            mpan = meter_point.get("mpan")
            best_samples = []
            for meter in meter_point.get("meters", []):
                serial_number = meter.get("serial_number")
                if not mpan or not serial_number:
                    continue

                url = (
                    f"https://api.octopus.energy/v1/electricity-meter-points/{quote(str(mpan), safe='')}"
                    f"/meters/{quote(str(serial_number), safe='')}/consumption/?"
                    + urlencode(
                        {
                            "period_from": period_from_text,
                            "order_by": "period",
                            "page_size": 250,
                        }
                    )
                )

                try:
                    samples = fetch_all_consumption_pages(url)
                except OctopusApiError as e:
                    logger.debug("Usage fetch failed for a meter: %s", type(e).__name__)
                    continue

                if samples and len(samples) > len(best_samples):
                    best_samples = samples

            if best_samples:
                return best_samples

    return []


def get_usage_refresh_start(cached_data, now=None):
    """Return the bounded start time for a full or incremental usage refresh."""
    now = now or datetime.now(timezone.utc)
    history_start = now - timedelta(days=USAGE_HISTORY_DAYS)
    cached_data = _compatible_usage_cache(cached_data)
    if not cached_data:
        return history_start

    cached_sample_starts = [
        sample_start
        for sample in cached_data.get("samples", [])
        if (sample_start := _parse_sample_start(sample)) is not None
    ]
    latest_sample_start = max(cached_sample_starts, default=None)
    if latest_sample_start is None:
        return history_start

    overlap_start_local = (
        min(latest_sample_start, now).astimezone(UK_TIMEZONE) - timedelta(days=USAGE_REFRESH_OVERLAP_DAYS)
    ).replace(
        hour=0,
        minute=0,
        second=0,
        microsecond=0,
    )
    overlap_start = overlap_start_local.astimezone(timezone.utc)
    return max(history_start, overlap_start)


def merge_usage_history(cached_data, fresh_samples, fresh_daily_costs, now=None):
    """Merge refreshed overlap data into a bounded, current usage cache payload."""
    now = now or datetime.now(timezone.utc)
    history_start = now - timedelta(days=USAGE_HISTORY_DAYS)
    cached_data = _compatible_usage_cache(cached_data) or {}

    samples_by_start = {}
    for sample in cached_data.get("samples", []):
        sample_start = _parse_sample_start(sample)
        if sample_start is not None and sample_start >= history_start:
            samples_by_start[sample_start] = sample
    for sample in fresh_samples:
        sample_start = _parse_sample_start(sample)
        if sample_start is not None and sample_start >= history_start:
            samples_by_start[sample_start] = sample

    merged_samples = [samples_by_start[sample_start] for sample_start in sorted(samples_by_start)]
    retained_dates = {
        sample_start.astimezone(UK_TIMEZONE).date().isoformat()
        for sample_start in samples_by_start
    }

    daily_costs_by_date = {
        day.get("date"): day
        for day in cached_data.get("daily_costs", [])
        if day.get("date") in retained_dates
    }
    if fresh_daily_costs is not None:
        for day in fresh_daily_costs:
            day_key = day.get("date")
            if day_key in retained_dates:
                daily_costs_by_date[day_key] = day

    return {
        "samples": merged_samples,
        "daily_costs": [daily_costs_by_date[day] for day in sorted(daily_costs_by_date)],
        "cache_version": USAGE_CACHE_VERSION,
        "price_band_version": PRICE_BAND_VERSION,
        "synced_at": now.isoformat(),
    }


def _compatible_usage_cache(cached_data):
    if (
        not cached_data
        or cached_data.get("cache_version") != USAGE_CACHE_VERSION
        or cached_data.get("price_band_version") != PRICE_BAND_VERSION
        or not isinstance(cached_data.get("samples"), list)
        or not isinstance(cached_data.get("daily_costs"), list)
    ):
        return None
    return cached_data


def _parse_sample_start(sample):
    value = sample.get("interval_start")
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def fetch_all_consumption_pages(initial_url):
    samples = []
    next_url = initial_url
    max_pages = 40
    pages_fetched = 0
    seen_urls = set()

    with requests.Session() as session:
        while next_url and pages_fetched < max_pages:
            if next_url in seen_urls:
                raise OctopusApiError("The API returned a repeated pagination URL.")
            seen_urls.add(next_url)
            data = get_json(next_url, use_api_key=True, timeout=10, session=session)
            page_results = data.get("results", [])
            if not isinstance(page_results, list):
                raise OctopusApiError("The API returned invalid consumption data.")
            if page_results:
                samples.extend(page_results)

            next_url = data.get("next")
            pages_fetched += 1

    if next_url:
        raise OctopusApiError("The API returned too many consumption pages.")
    return samples


def build_historical_usage_costs(account_data, usage_samples):
    period_start, period_end = get_usage_period(usage_samples)
    if not period_start or not period_end:
        return []

    tariff_periods = build_tariff_periods(account_data, period_start, period_end)
    rates_by_tariff = {}
    standing_charges_by_tariff = {}
    for tariff_code in {period["tariff_code"] for period in tariff_periods}:
        product_code = extract_product_code(tariff_code)
        rates_by_tariff[tariff_code] = fetch_historical_unit_rates(
            product_code,
            tariff_code,
            period_start,
            period_end,
        )
        standing_charges_by_tariff[tariff_code] = fetch_historical_tariff_records(
            product_code,
            tariff_code,
            "standing-charges",
            period_start,
            period_end,
        )

    return build_daily_costs(usage_samples, tariff_periods, rates_by_tariff, standing_charges_by_tariff)


def fetch_historical_unit_rates(product_code, tariff_code, period_start, period_end):
    try:
        return fetch_historical_tariff_records(
            product_code,
            tariff_code,
            "standard-unit-rates",
            period_start,
            period_end,
        )
    except OctopusApiError as exc:
        if "day and night rates" not in str(exc).lower():
            raise

    day_rates = fetch_historical_tariff_records(
        product_code,
        tariff_code,
        "day-unit-rates",
        period_start,
        period_end,
    )
    night_rates = fetch_historical_tariff_records(
        product_code,
        tariff_code,
        "night-unit-rates",
        period_start,
        period_end,
    )
    return build_dual_register_price_windows(day_rates, night_rates, period_start, period_end)


def fetch_historical_tariff_records(product_code, tariff_code, endpoint, period_start, period_end):
    url = (
        f"https://api.octopus.energy/v1/products/{quote(product_code, safe='-')}"
        f"/electricity-tariffs/{quote(tariff_code, safe='-')}/{quote(endpoint, safe='-')}/?"
        + urlencode(
            {
                "period_from": _format_octopus_datetime(period_start),
                "period_to": _format_octopus_datetime(period_end),
                "page_size": 1500,
            }
        )
    )
    return fetch_all_tariff_pages(url)


def fetch_all_tariff_pages(initial_url):
    records = []
    next_url = initial_url
    max_pages = 40
    pages_fetched = 0
    seen_urls = set()

    with requests.Session() as session:
        while next_url and pages_fetched < max_pages:
            if next_url in seen_urls:
                raise OctopusApiError("The API returned a repeated pagination URL.")
            seen_urls.add(next_url)
            data = get_json(next_url, use_api_key=True, timeout=10, session=session)
            page_results = data.get("results", [])
            if not isinstance(page_results, list):
                raise OctopusApiError("The API returned invalid tariff data.")
            if page_results:
                records.extend(page_results)

            next_url = data.get("next")
            pages_fetched += 1

    if next_url:
        raise OctopusApiError("The API returned too many tariff pages.")
    return records


def _format_octopus_datetime(value):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _has_active_agreement(meter_point, now):
    for agreement in meter_point.get("agreements", []):
        valid_from = agreement.get("valid_from")
        valid_to = agreement.get("valid_to")
        if not valid_from:
            continue

        start = datetime.fromisoformat(valid_from.replace("Z", "+00:00"))
        end = datetime.fromisoformat(valid_to.replace("Z", "+00:00")) if valid_to else None
        if start <= now and (end is None or now < end):
            return True

    return False
