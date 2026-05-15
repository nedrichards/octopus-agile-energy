from datetime import datetime, time, timedelta, timezone


def extract_product_code(selected_tariff_code):
    parts = selected_tariff_code.split('-')
    return '-'.join(parts[2:-1])


def find_cheapest_slot(
    prices,
    now,
    duration_hours,
    start_within_hours,
    whole_hour_starts_only=False,
    continuous_starts=False,
):
    if continuous_starts:
        return _find_cheapest_continuous_slot(prices, now, duration_hours, start_within_hours)

    num_slots = duration_hours * 2
    cutoff = now + timedelta(hours=start_within_hours)
    prices_to_search = [p for p in prices if now <= p['valid_from'] < cutoff]

    if len(prices_to_search) < num_slots:
        return None

    best_window = None
    best_total_price = float('inf')

    for i in range(len(prices_to_search) - num_slots + 1):
        window = prices_to_search[i:i + num_slots]
        if whole_hour_starts_only and window[0]['valid_from'].astimezone().minute != 0:
            continue

        total_price = sum(p['price_gbp'] for p in window)
        if total_price < best_total_price:
            best_total_price = total_price
            best_window = window

    if not best_window:
        return None

    return {
        'start': best_window[0]['valid_from'],
        'end': best_window[-1]['valid_to'],
        'average_price_gbp': best_total_price / num_slots,
    }


def _find_cheapest_continuous_slot(prices, now, duration_hours, start_within_hours):
    now = now.replace(second=0, microsecond=0)
    duration = timedelta(hours=duration_hours)
    cutoff = now + timedelta(hours=start_within_hours)
    sorted_prices = sorted(prices, key=lambda price: price['valid_from'])
    candidates = []
    candidate = now
    while candidate < cutoff:
        candidates.append(candidate)
        candidate += timedelta(minutes=30)

    best_start = None
    best_average_price = float('inf')

    for start in sorted(candidates):
        end = start + duration
        average_price = _calculate_weighted_average_price(sorted_prices, start, end)
        if average_price is None:
            continue

        if average_price < best_average_price:
            best_average_price = average_price
            best_start = start

    if best_start is None:
        return None

    return {
        'start': best_start,
        'end': best_start + duration,
        'average_price_gbp': best_average_price,
    }


def _calculate_weighted_average_price(prices, start, end):
    duration_seconds = (end - start).total_seconds()
    if duration_seconds <= 0:
        return None

    cursor = start
    total_price_seconds = 0.0

    for price in prices:
        if price['valid_to'] <= cursor:
            continue
        if price['valid_from'] >= end:
            break
        if price['valid_from'] > cursor:
            return None

        overlap_start = max(cursor, price['valid_from'])
        overlap_end = min(end, price['valid_to'])
        if overlap_end <= overlap_start:
            continue

        total_price_seconds += price['price_gbp'] * (overlap_end - overlap_start).total_seconds()
        cursor = overlap_end
        if cursor >= end:
            return total_price_seconds / duration_seconds

    return None


def build_dual_register_price_windows(
    day_rates,
    night_rates,
    period_start,
    period_end,
    # Octopus documents smart-meter Economy 7 off-peak as 00:30-07:30 UTC.
    # https://octopus.energy/help-and-faqs/articles/what-is-an-economy-7-meter-and-tariff/
    night_start=time(0, 30),
    night_end=time(7, 30),
):
    """
    Expands day/night unit-rate records into the half-hour windows used by the chart.
    The Economy 7 switching times are treated as UTC clock times.
    """
    current = _floor_to_half_hour(period_start.astimezone(timezone.utc))
    period_end = period_end.astimezone(timezone.utc)
    prices = []

    while current < period_end:
        next_slot = current + timedelta(minutes=30)
        source_rates = night_rates if _is_night_slot(current, night_start, night_end) else day_rates
        rate = _find_active_rate(source_rates, current)
        if rate:
            prices.append({
                'valid_from': current.isoformat().replace("+00:00", "Z"),
                'valid_to': next_slot.isoformat().replace("+00:00", "Z"),
                'value_inc_vat': rate['value_inc_vat'],
            })
        current = next_slot

    return prices


def _floor_to_half_hour(value):
    minute = 0 if value.minute < 30 else 30
    return value.replace(minute=minute, second=0, microsecond=0)


def _is_night_slot(value, night_start, night_end):
    slot_time = value.time().replace(tzinfo=None)
    if night_start <= night_end:
        return night_start <= slot_time < night_end
    return slot_time >= night_start or slot_time < night_end


def _find_active_rate(rates, target):
    for rate in rates:
        try:
            valid_from = datetime.fromisoformat(rate['valid_from'].replace('Z', '+00:00'))
            valid_to = (
                datetime.fromisoformat(rate['valid_to'].replace('Z', '+00:00'))
                if rate.get('valid_to')
                else datetime.max.replace(tzinfo=timezone.utc)
            )
        except (KeyError, ValueError, TypeError):
            continue

        if valid_from <= target < valid_to:
            return rate

    return None


def build_region_to_tariffs_map(product_data, region_code_to_name):
    region_to_tariffs_map = {code: [] for code in region_code_to_name.keys()}
    product_name = product_data.get('full_name', 'Agile Tariff')
    tariffs = product_data.get('single_register_electricity_tariffs', {})

    for region_code, tariff_types in tariffs.items():
        if region_code not in region_code_to_name:
            continue

        tariff_code = None
        if 'direct_debit_monthly' in tariff_types and 'code' in tariff_types['direct_debit_monthly']:
            tariff_code = tariff_types['direct_debit_monthly']['code']
        else:
            for payment_method in tariff_types.values():
                if isinstance(payment_method, dict) and 'code' in payment_method:
                    tariff_code = payment_method['code']
                    break

        if tariff_code:
            region_name = region_code_to_name[region_code]
            region_to_tariffs_map[region_code].append({
                'code': tariff_code,
                'full_name': f"{product_name} ({region_name})",
            })

    return region_to_tariffs_map
