#!/usr/bin/env python3
"""Compare release-managed Agile price bands with Flexible Octopus rates."""

import argparse
import json
import sys
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.price_bands import (  # noqa: E402
    HIGH_PRICE_THRESHOLD_GBP,
    LOW_PRICE_THRESHOLD_GBP,
    PRICE_BAND_VERSION,
)

API_ROOT = "https://api.octopus.energy/v1"
AGILE_PRODUCT = "AGILE-24-10-01"
FLEXIBLE_PRODUCT = "VAR-22-11-01"
REGIONS = ("A", "B", "C", "D", "E", "F", "G", "H", "J", "K", "L", "M", "N", "P")


def parse_args():
    yesterday = date.today() - timedelta(days=1)
    parser = argparse.ArgumentParser(
        description="Review candidate chart bands against public Agile and Flexible Octopus rates.",
    )
    parser.add_argument(
        "--region",
        default="C",
        choices=("all", *REGIONS),
        help="DNO region letter, or 'all' for every supported region (default: C/London).",
    )
    parser.add_argument("--days", type=int, default=28, help="Completed Agile days to analyse (default: 28).")
    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        default=yesterday,
        help=f"Last completed date in YYYY-MM-DD form (default: {yesterday.isoformat()}).",
    )
    parser.add_argument(
        "--low-pence",
        type=float,
        default=LOW_PRICE_THRESHOLD_GBP * 100,
        help="Candidate low/medium boundary in p/kWh.",
    )
    parser.add_argument(
        "--high-pence",
        type=float,
        default=HIGH_PRICE_THRESHOLD_GBP * 100,
        help="Candidate medium/high boundary in p/kWh.",
    )
    args = parser.parse_args()
    if args.days <= 0:
        parser.error("--days must be positive")
    if args.low_pence <= 0 or args.high_pence <= args.low_pence:
        parser.error("thresholds must satisfy 0 < low-pence < high-pence")
    return args


def fetch_pages(url, params):
    results = []
    next_url = f"{url}?{urlencode(params)}"
    while next_url:
        request = Request(next_url, headers={"User-Agent": "octopusagile-price-band-review/1"})
        with urlopen(request, timeout=30) as response:
            payload = json.load(response)
        results.extend(payload.get("results", []))
        next_url = payload.get("next")
    return results


def tariff_url(product, region):
    tariff_code = f"E-1R-{product}-{region}"
    return f"{API_ROOT}/products/{product}/electricity-tariffs/{tariff_code}/standard-unit-rates/"


def iso_utc(day):
    return datetime.combine(day, time.min, tzinfo=timezone.utc).isoformat().replace("+00:00", "Z")


def fetch_flexible_direct_debit(region, end_date):
    records = fetch_pages(
        tariff_url(FLEXIBLE_PRODUCT, region),
        {
            "period_from": iso_utc(end_date),
            "period_to": iso_utc(end_date + timedelta(days=1)),
            "page_size": 100,
        },
    )
    direct_debit = [record for record in records if record.get("payment_method") == "DIRECT_DEBIT"]
    if not direct_debit:
        raise RuntimeError(f"No Flexible Direct Debit rate returned for region {region}")
    return float(max(direct_debit, key=lambda record: record["valid_from"])["value_inc_vat"])


def fetch_agile_prices(region, start_date, end_date):
    records = fetch_pages(
        tariff_url(AGILE_PRODUCT, region),
        {
            "period_from": iso_utc(start_date),
            "period_to": iso_utc(end_date + timedelta(days=1)),
            "page_size": 1500,
        },
    )
    return [float(record["value_inc_vat"]) for record in records]


def percentile(sorted_values, fraction):
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * fraction
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(sorted_values) - 1)
    weight = position - lower_index
    return sorted_values[lower_index] * (1 - weight) + sorted_values[upper_index] * weight


def summarize_prices(prices, low_pence, high_pence):
    sorted_prices = sorted(prices)
    return {
        "count": len(prices),
        "minimum": sorted_prices[0],
        "p25": percentile(sorted_prices, 0.25),
        "median": percentile(sorted_prices, 0.5),
        "p75": percentile(sorted_prices, 0.75),
        "maximum": sorted_prices[-1],
        "negative": sum(price < 0 for price in prices),
        "low": sum(0 <= price < low_pence for price in prices),
        "medium": sum(low_pence <= price < high_pence for price in prices),
        "high": sum(price >= high_pence for price in prices),
    }


def print_summary(label, flexible_rate, summary, low_pence, high_pence):
    count = summary["count"]
    print(f"\n{label}")
    print(f"  Flexible Direct Debit: {flexible_rate:.3f}p/kWh")
    print(
        "  Agile range/percentiles: "
        f"{summary['minimum']:.3f} / {summary['p25']:.3f} / {summary['median']:.3f} / "
        f"{summary['p75']:.3f} / {summary['maximum']:.3f}p"
    )
    for name in ("negative", "low", "medium", "high"):
        band_count = summary[name]
        print(f"  {name.title():8} {band_count:5} slots ({band_count / count:5.1%})")
    print(f"  Low boundary:  {low_pence:.3g}p ({low_pence / flexible_rate:.1%} of Flexible)")
    print(f"  High boundary: {high_pence:.3g}p ({high_pence / flexible_rate:.1%} of Flexible)")


def main():
    args = parse_args()
    start_date = args.end_date - timedelta(days=args.days - 1)
    regions = REGIONS if args.region == "all" else (args.region,)
    all_prices = []
    flexible_rates = []

    print(f"Price band version: {PRICE_BAND_VERSION}")
    print(f"Analysis period: {start_date.isoformat()} to {args.end_date.isoformat()} inclusive")
    print(f"Candidate boundaries: 0p / {args.low_pence:g}p / {args.high_pence:g}p")

    for region in regions:
        flexible_rate = fetch_flexible_direct_debit(region, args.end_date)
        agile_prices = fetch_agile_prices(region, start_date, args.end_date)
        if not agile_prices:
            raise RuntimeError(f"No Agile rates returned for region {region}")
        summary = summarize_prices(agile_prices, args.low_pence, args.high_pence)
        print_summary(f"Region {region}", flexible_rate, summary, args.low_pence, args.high_pence)
        flexible_rates.append(flexible_rate)
        all_prices.extend(agile_prices)

    if len(regions) > 1:
        benchmark = sum(flexible_rates) / len(flexible_rates)
        summary = summarize_prices(all_prices, args.low_pence, args.high_pence)
        print_summary("All supported regions", benchmark, summary, args.low_pence, args.high_pence)
        print(
            f"  Flexible regional range: {min(flexible_rates):.3f}–{max(flexible_rates):.3f}p/kWh"
        )


if __name__ == "__main__":
    main()
