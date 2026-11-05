import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from src.octopus_api import OctopusApiError
from src.price_bands import PRICE_BAND_VERSION
from src.usage_history import USAGE_CACHE_VERSION, get_usage_repair_ranges, repair_usage_history

NOW = datetime(2026, 11, 5, 12, tzinfo=UTC)


def cache():
    return {
        'cache_version': USAGE_CACHE_VERSION, 'price_band_version': PRICE_BAND_VERSION,
        'samples': [{'interval_start': '2026-11-04T12:00:00Z'}],
        'daily_costs': [], 'daily_usage_archive': [
            {'date': '2026-10-19', 'kwh': 1, 'sample_count': 48, 'energy_cost_gbp': 1},
            {'date': '2026-10-20', 'kwh': 1, 'sample_count': 2, 'energy_cost_gbp': 1},
            {'date': '2026-10-22', 'kwh': 1, 'sample_count': 46, 'energy_cost_gbp': 1},
            *[{'date': f'2026-10-{day}', 'kwh': 1, 'sample_count': 50 if day == 25 else 48,
               'energy_cost_gbp': 1} for day in range(23, 29)],
        ],
    }


class UsageRepairTests(unittest.TestCase):

    def test_adjacent_gaps_include_wholly_missing_day_and_use_local_midnights(self):
        ranges = get_usage_repair_ranges(cache(), NOW)
        assert [(start.isoformat(), end.isoformat()) for start, end in ranges] == [
            ('2026-10-20T00:00:00+01:00', '2026-10-23T00:00:00+01:00')]


    def test_weekly_retry_and_manual_bypass(self):
        data = cache()
        data['repair_synced_at'] = (NOW - timedelta(days=6)).isoformat()
        assert not get_usage_repair_ranges(data, NOW)
        assert get_usage_repair_ranges(data, NOW, force=True)
        assert get_usage_repair_ranges(data, NOW + timedelta(days=1))


    def test_span_is_bounded_and_checked_gaps_rotate(self):
        data = cache()
        data['daily_usage_archive'] = [{'date': '2026-07-10', 'sample_count': 1}]
        ranges = get_usage_repair_ranges(data, NOW)
        assert ranges[-1][1] - ranges[0][0] <= timedelta(days=14)
        data['repair_checked_days'] = {(ranges[0][0].date() + timedelta(days=i)).isoformat(): NOW.isoformat()
                                       for i in range(14)}
        assert get_usage_repair_ranges(data, NOW)[0][0] > ranges[-1][0]


    def test_older_action_extends_beyond_recent_retention(self):
        data = cache()
        data['daily_usage_archive'] = [{'date': '2025-01-01', 'sample_count': 1}]
        assert get_usage_repair_ranges(data, NOW)[0][0].year == 2026
        assert get_usage_repair_ranges(data, NOW, force=True, older=True)[0][0].year == 2025


    def test_empty_response_is_checked_without_erasing_cached_data(self):
        data = cache()
        with patch('src.usage_history._fetch_usage_samples', return_value=[]), \
             patch('src.usage_history.build_historical_usage_costs', return_value=[]):
            result = repair_usage_history({}, data, NOW)
        assert result['daily_usage_archive'] == data['daily_usage_archive']
        assert result['repair_checked_days']['2026-10-21'] == NOW.isoformat()
        assert not get_usage_repair_ranges(result, NOW)


    def test_network_failure_does_not_mark_checked_or_mutate_cache(self):
        data = cache()
        with patch('src.usage_history._fetch_usage_samples', side_effect=OctopusApiError('unavailable')), \
             self.assertRaises(OctopusApiError):
            repair_usage_history({}, data, NOW)
        assert 'repair_checked_days' not in data


    def test_repaired_day_updates_samples_costs_and_archive(self):
        data = cache()
        sample = {'interval_start': '2026-10-20T01:00:00Z', 'consumption': 0.5}
        cost = {'date': '2026-10-20', 'sample_count': 48, 'kwh': 2, 'energy_cost_gbp': -1,
                'missing_rate_count': 0}
        with patch('src.usage_history._fetch_usage_samples', return_value=[sample]), \
             patch('src.usage_history.build_historical_usage_costs', return_value=[cost]):
            result = repair_usage_history({}, data, NOW, force=True)
        assert sample in result['samples']
        assert result['daily_costs'] == [cost]
        assert next(day for day in result['daily_usage_archive'] if day['date'] == cost['date']) == cost
