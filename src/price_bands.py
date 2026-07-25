PRICE_BAND_NEGATIVE = "negative"
PRICE_BAND_LOW = "low"
PRICE_BAND_MEDIUM = "medium"
PRICE_BAND_HIGH = "high"

PRICE_BAND_VERSION = 2
LOW_PRICE_THRESHOLD_GBP = 0.20
HIGH_PRICE_THRESHOLD_GBP = 0.265


def get_price_band(price_gbp):
    """Classify an import unit rate using the release-managed price bands."""
    if price_gbp < 0:
        return PRICE_BAND_NEGATIVE
    if price_gbp < LOW_PRICE_THRESHOLD_GBP:
        return PRICE_BAND_LOW
    if price_gbp < HIGH_PRICE_THRESHOLD_GBP:
        return PRICE_BAND_MEDIUM
    return PRICE_BAND_HIGH


def format_price_threshold(price_gbp):
    """Format a price-band threshold as a compact pence-per-kWh value."""
    return f"{round(price_gbp * 100, 3):g}p/kWh"
