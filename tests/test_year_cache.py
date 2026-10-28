import datetime as dt
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import generate


def graphql_response(url, **kwargs):
    year = int(re.search(r'from: "(\d{4})-', kwargs['body']['query']).group(1))
    user = kwargs['body']['variables']['login']
    return {'data': {'user': {
        'login': user, 'url': 'https://github.com/' + user, 'createdAt': '2021-01-01T00:00:00Z',
        'contributionsCollection': {'contributionCalendar': {
            'totalContributions': 1, 'weeks': [{'contributionDays': [
                {'date': f'{year}-01-01', 'contributionCount': 1, 'contributionLevel': 'FIRST_QUARTILE'}]}]}}
    }, 'rateLimit': {'remaining': 100}}}, {}


class YearCacheTests(unittest.TestCase):
    def test_old_years_are_fixed_json_files_and_recent_years_are_always_fetched(self):
        until = dt.date(2026, 10, 28)
        with tempfile.TemporaryDirectory() as directory, patch('builtins.print'):
            with patch.object(generate, 'request_json', side_effect=graphql_response) as request:
                generate.fetch_graphql('Example', None, until, 'test-token', cache_dir=directory)
            self.assertEqual(request.call_count, 6)
            files = sorted(Path(directory).rglob('*.json'))
            self.assertEqual([file.name for file in files], [f'{year}.json' for year in range(2021, 2025)])
            before = {str(file): file.read_bytes() for file in files}
            with patch.object(generate, 'request_json', side_effect=graphql_response) as request:
                _, metadata, raw = generate.fetch_graphql('example', None, until, 'another-token', cache_dir=directory)
            requested = [int(re.search(r'from: "(\d{4})-', call.kwargs['body']['query']).group(1)) for call in request.call_args_list]
            self.assertEqual(requested, [2026, 2025])
            self.assertEqual(metadata['dataApiRequests'], 2)
            self.assertEqual(metadata['historicalCachedYears'], [2021, 2022, 2023, 2024])
            self.assertEqual(sum(item['cached'] for item in raw['responses']), 4)
            self.assertEqual(before, {str(file): file.read_bytes() for file in files})
            self.assertTrue(all(b'test-token' not in data and b'another-token' not in data for data in before.values()))
            # Another user cannot reuse these files.
            with patch.object(generate, 'request_json', side_effect=graphql_response) as request:
                generate.fetch_graphql('AnotherUser', None, until, 'test-token', cache_dir=directory)
            self.assertEqual(request.call_count, 6)

    def test_year_rollover_adds_only_the_newly_eligible_year(self):
        with tempfile.TemporaryDirectory() as directory, patch('builtins.print'):
            with patch.object(generate, 'request_json', side_effect=graphql_response):
                generate.fetch_graphql('Example', None, dt.date(2026, 12, 31), 'test-token', cache_dir=directory)
            with patch.object(generate, 'request_json', side_effect=graphql_response) as request:
                generate.fetch_graphql('Example', None, dt.date(2027, 1, 1), 'test-token', cache_dir=directory)
            requested = [int(re.search(r'from: "(\d{4})-', call.kwargs['body']['query']).group(1)) for call in request.call_args_list]
            self.assertEqual(requested, [2027, 2025, 2026])
            self.assertEqual(sorted(file.name for file in Path(directory).rglob('*.json')),
                             [f'{year}.json' for year in range(2021, 2026)])

    def test_public_source_has_separate_year_files_and_skips_cached_requests(self):
        def response(url, **kwargs):
            if url.startswith('https://api.github.com/users/'):
                return {'login': 'Example', 'html_url': 'https://github.com/Example', 'created_at': '2021-01-01T00:00:00Z'}, {}
            year = int(url.rsplit('=', 1)[1])
            return {'contributions': [{'date': f'{year}-01-01', 'count': 1, 'level': 1}], 'total': {str(year): 1}}, {}
        with tempfile.TemporaryDirectory() as directory, patch('builtins.print'):
            with patch.object(generate, 'request_json', side_effect=graphql_response):
                generate.fetch_graphql('Example', None, dt.date(2026, 1, 1), 'test-token', cache_dir=directory)
            with patch.object(generate, 'request_json', side_effect=response) as request:
                generate.fetch_public('Example', None, dt.date(2026, 1, 1), cache_dir=directory)
            self.assertEqual(request.call_count, 7)
            with patch.object(generate, 'request_json', side_effect=response) as request:
                _, metadata, _ = generate.fetch_public('Example', None, dt.date(2026, 2, 1), cache_dir=directory)
            self.assertEqual(request.call_count, 3)  # Profile, previous year, current year.
            self.assertEqual(metadata['dataApiRequests'], 2)

    def test_failed_api_response_is_not_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(generate, 'request_json', return_value=({'errors': [{'message': 'rate limit'}]}, {})):
                with self.assertRaisesRegex(RuntimeError, 'without retry or fallback'):
                    generate.fetch_graphql('Example', 2021, dt.date(2026, 1, 1), 'test-token', cache_dir=directory)
            self.assertEqual(list(Path(directory).rglob('*.json')), [])
