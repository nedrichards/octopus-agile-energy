# Price band review

Price bands are deliberately release-managed. The application does not fetch a
Flexible Octopus benchmark at runtime, so chart colours and usage classifications
remain stable, predictable, and available from cached Agile data.

The source of truth is `src/price_bands.py`. Band version 2 uses:

- negative: below 0p/kWh;
- low: 0p/kWh up to, but not including, 20p/kWh;
- medium: 20p/kWh up to, but not including, 26.5p/kWh; and
- high: 26.5p/kWh or above.

## Periodic analysis

Review the bands when Flexible Octopus changes, or before a release where the
existing thresholds appear out of step with the market. Use at least 28 completed
days so the sample contains weekdays and weekends. A longer 56- or 90-day window
is preferable when a quarter has been unusually volatile.

Run the public-API analysis for every region supported by the application:

```bash
python3 scripts/analyse_price_bands.py --region all --days 28
```

The command defaults to yesterday as the final date, avoiding a partial current
day. Use `--end-date YYYY-MM-DD` to reproduce an earlier review. Candidate bands
can be compared without editing the application:

```bash
python3 scripts/analyse_price_bands.py --region all --days 28 \
  --low-pence 20 --high-pence 26.5
```

The report shows each region's Flexible Direct Debit rate, Agile range and
quartiles, band populations, and each proposed boundary as a percentage of
Flexible. It uses only public Octopus tariff endpoints and does not require an
API key or account details.

Choose thresholds for meaning rather than equal-sized buckets:

- keep the negative boundary exactly at 0p;
- treat the low boundary as a substantial saving, currently about 75% of
  Flexible;
- place the high boundary around the upper end of regional Flexible Direct Debit
  rates, using a simple half-penny or whole-penny value; and
- check that no supported region produces a clearly misleading distribution.

## Rolling the bands forward

When thresholds change:

1. Update `LOW_PRICE_THRESHOLD_GBP` and/or `HIGH_PRICE_THRESHOLD_GBP` in
   `src/price_bands.py`.
2. Increment `PRICE_BAND_VERSION`. Cached usage totals include this version; the
   application will regard an older classification as stale and rebuild it in
   the background.
3. Update the exact boundary tests in `tests/test_price_bands.py` and the
   historical aggregation test in `tests/test_historical_costs.py`.
4. Record the review date, analysis window, Flexible regional range, chosen
   thresholds, and rationale in the release notes or pull request.
5. Run the normal source checks and authoritative development Flatpak build from
   `AGENTS.md`.

Do not change the thresholds dynamically or silently between releases. Users
should receive a stable visual classification for the lifetime of an installed
version.

## Version 2 decision

Reviewed on 25 July 2026 using all 14 regions and the 28 completed days from
27 June through 24 July. Across 18,816 Agile slots, 863 (4.6%) were negative,
6,493 (34.5%) were low, 6,771 (36.0%) were medium, and 4,689 (24.9%) were high.
Regional Flexible Direct Debit rates ranged from 25.096p to 27.657p/kWh, with a
26.110p mean.

The 20p low boundary therefore remained a meaningful saving against Flexible,
while 26.5p sat near the regional Flexible benchmark and avoided marking prices
that were still clearly cheaper than Flexible as high. This replaced the
original 15p and 25p boundaries.
