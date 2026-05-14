import logging
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from .historical_costs import build_daily_costs, build_tariff_periods, get_usage_period
from .octopus_api import OctopusApiError, get_json
from .price_logic import build_dual_register_price_windows, extract_product_code

logger = logging.getLogger(__name__)


def get_account_data(account_number):
    account_number = account_number.strip()
    if not account_number:
        raise OctopusApiError("Missing account number.")

    return get_json(
        f"https://api.octopus.energy/v1/accounts/{account_number}/",
        use_api_key=True,
        timeout=10,
    )


def fetch_recent_usage_samples(account_data):
    now = datetime.now(timezone.utc)
    period_from = (now - timedelta(days=120)).strftime("%Y-%m-%dT%H:%M:%SZ")

    for property_data in account_data.get("properties", []):
        for meter_point in property_data.get("electricity_meter_points", []):
            if not _has_active_agreement(meter_point, now):
                continue

            mpan = meter_point.get("mpan")
            _log_meter_point_probe(meter_point)
            best_samples = []
            for meter in meter_point.get("meters", []):
                serial_number = meter.get("serial_number")
                if not mpan or not serial_number:
                    continue

                url = (
                    f"https://api.octopus.energy/v1/electricity-meter-points/{mpan}"
                    f"/meters/{serial_number}/consumption/?"
                    + urlencode(
                        {
                            "period_from": period_from,
                            "order_by": "period",
                            "page_size": 250,
                        }
                    )
                )

                try:
                    samples = fetch_all_consumption_pages(url)
                except OctopusApiError as e:
                    logger.debug("Usage fetch failed for meter %s/%s: %s", mpan, serial_number, e)
                    continue

                _log_usage_sample_probe(mpan, serial_number, samples)
                if samples and len(samples) > len(best_samples):
                    best_samples = samples

            if best_samples:
                return best_samples

    return []


def fetch_all_consumption_pages(initial_url):
    samples = []
    next_url = initial_url
    max_pages = 40
    pages_fetched = 0

    while next_url and pages_fetched < max_pages:
        data = get_json(next_url, use_api_key=True, timeout=10)
        page_results = data.get("results", [])
        if page_results:
            samples.extend(page_results)

        next_url = data.get("next")
        pages_fetched += 1

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

    logger.warning(
        "Historical usage costs for %s are using provisional dual-register expansion "
        "with night window 00:30-07:30 UTC.",
        tariff_code,
    )
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
        f"https://api.octopus.energy/v1/products/{product_code}"
        f"/electricity-tariffs/{tariff_code}/{endpoint}/?"
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

    while next_url and pages_fetched < max_pages:
        data = get_json(next_url, use_api_key=True, timeout=10)
        page_results = data.get("results", [])
        if page_results:
            records.extend(page_results)

        next_url = data.get("next")
        pages_fetched += 1

    return records


def _format_octopus_datetime(value):
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log_meter_point_probe(meter_point):
    mpan = meter_point.get("mpan")
    meters = meter_point.get("meters", [])
    agreements = meter_point.get("agreements", [])
    active_tariff_codes = [agreement.get("tariff_code", "") for agreement in agreements]
    register_fields = {
        key: value
        for key, value in meter_point.items()
        if "register" in key.lower() or "profile" in key.lower() or "meter" in key.lower()
    }
    dual_register_tariffs = [
        tariff_code
        for tariff_code in active_tariff_codes
        if isinstance(tariff_code, str) and "-2R-" in tariff_code.upper()
    ]
    logger.warning(
        "Octopus account probe: active electricity meter point mpan=%s meters=%d agreements=%d keys=%s",
        mpan,
        len(meters),
        len(agreements),
        sorted(meter_point.keys()),
    )
    if dual_register_tariffs:
        logger.warning(
            "Octopus account probe: dual-register tariff agreement(s) detected for mpan=%s: %s",
            mpan,
            dual_register_tariffs,
        )
    if register_fields:
        logger.warning("Octopus account probe: meter/register fields for mpan=%s: %s", mpan, register_fields)
    else:
        logger.warning(
            "Octopus account probe: no obvious register/profile fields found directly on meter point mpan=%s.",
            mpan,
        )
    for agreement in agreements:
        logger.warning(
            "Octopus account probe: agreement tariff_code=%s valid_from=%s valid_to=%s",
            agreement.get("tariff_code"),
            agreement.get("valid_from"),
            agreement.get("valid_to"),
        )
    for meter in meters:
        logger.warning(
            "Octopus account probe: meter serial=%s keys=%s details=%s",
            meter.get("serial_number"),
            sorted(meter.keys()),
            {
                key: value
                for key, value in meter.items()
                if "register" in key.lower() or "profile" in key.lower() or "meter" in key.lower()
            },
        )
        registers = meter.get("registers")
        if registers is not None:
            logger.warning(
                "Octopus account probe: meter serial=%s registers=%s",
                meter.get("serial_number"),
                registers,
            )
        else:
            logger.warning(
                "Octopus account probe: meter serial=%s has no registers field in account payload.",
                meter.get("serial_number"),
            )


def _log_usage_sample_probe(mpan, serial_number, samples):
    logger.warning(
        "Octopus usage probe: meter %s/%s returned %d consumption sample(s).",
        mpan,
        serial_number,
        len(samples),
    )
    for sample in samples[:6]:
        register_fields = {
            key: value
            for key, value in sample.items()
            if "register" in key.lower() or "rate" in key.lower() or "cost" in key.lower()
        }
        logger.warning(
            "Octopus usage probe: sample interval_start=%s interval_end=%s consumption=%s keys=%s register/rate/cost fields=%s",
            sample.get("interval_start"),
            sample.get("interval_end"),
            sample.get("consumption"),
            sorted(sample.keys()),
            register_fields,
        )


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
