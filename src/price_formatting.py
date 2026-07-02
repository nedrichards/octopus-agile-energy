def format_gbp(value, decimals=2):
    rounded_value = round(float(value), decimals)
    sign = "-" if rounded_value < 0 else ""
    return f"{sign}£{abs(rounded_value):.{decimals}f}"


def format_unit_price_gbp(value, decimals=2):
    return f"{format_gbp(value, decimals)}/kWh"
