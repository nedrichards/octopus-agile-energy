from datetime import timedelta


def extract_product_code(selected_tariff_code):
    parts = selected_tariff_code.split('-')
    return '-'.join(parts[2:-1])


def find_cheapest_slot(prices, now, duration_hours, start_within_hours):
    num_slots = duration_hours * 2
    cutoff = now + timedelta(hours=start_within_hours)
    prices_to_search = [p for p in prices if now <= p['valid_from'] < cutoff]

    if len(prices_to_search) < num_slots:
        return None

    best_window = None
    best_total_price = float('inf')

    for i in range(len(prices_to_search) - num_slots + 1):
        window = prices_to_search[i:i + num_slots]
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
