#!/usr/bin/env python3
"""Fetch daily GitHub contributions once, then render an offline archive."""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import io
import json
import os
from pathlib import Path
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

LEVELS = {'NONE': 0, 'FIRST_QUARTILE': 1, 'SECOND_QUARTILE': 2, 'THIRD_QUARTILE': 3, 'FOURTH_QUARTILE': 4}
PALETTE = ['#eff2f5', '#aceebb', '#4ac26b', '#2da44e', '#116329']
REQUEST_INTERVAL_SECONDS = 1.2
_last_request_finished = None


def year_cache_path(directory, user, source, year, until):
    if directory is None or year > until.year - 2:
        return None
    return Path(directory) / source / user.lower() / f'{year}.json'


def save_year_cache(path, response):
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(response, ensure_ascii=False), encoding='utf-8')


def request_json(url, *, token=None, body=None):
    global _last_request_finished
    if _last_request_finished is not None:
        wait = REQUEST_INTERVAL_SECONDS - (time.monotonic() - _last_request_finished)
        if wait > 0:
            time.sleep(wait)
    headers = {'User-Agent': 'monthly-contribution-archive/1.0', 'Accept': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    if body is not None:
        headers['Content-Type'] = 'application/json'
    request = urllib.request.Request(url, data=json.dumps(body).encode('utf-8') if body is not None else None, headers=headers)
    try:
        # Exactly one attempt. In particular, never retry 403, 429, or rate errors.
        with urllib.request.urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode('utf-8'))
            limit = {k: response.headers.get('X-RateLimit-' + k) for k in ['Limit', 'Remaining', 'Reset']}
    except urllib.error.HTTPError as exc:
        retry_after = exc.headers.get('Retry-After') if exc.headers else None
        raise RuntimeError(f'API HTTP {exc.code}; stopped without retry. Retry-After={retry_after or "not supplied"}') from None
    finally:
        _last_request_finished = time.monotonic()
    return result, {k.lower(): v for k, v in limit.items() if v is not None}


def graphql_query(year, until):
    end = min(dt.date(year, 12, 31), until)
    return f'''query ContributionArchive($login: String!) {{
      user(login: $login) {{ login createdAt url
        contributionsCollection(from: "{year}-01-01T00:00:00Z", to: "{end.isoformat()}T23:59:59Z") {{
          contributionCalendar {{ totalContributions weeks {{ contributionDays {{ date contributionCount contributionLevel }} }} }}
        }}
      }}
      rateLimit {{ cost limit remaining resetAt }}
    }}'''


def fetch_graphql(user, start_year, until, token, *, cache_dir=None):
    if not token:
        raise ValueError('GraphQL requires GH_TOKEN or GITHUB_TOKEN. Use --source public for the public calendar API.')
    entries, responses, rate_history = [], [], []
    account = None
    cached_years = []
    # The first annual response already includes the account creation date.
    # Reuse its calendar so automatic discovery adds no extra API request.
    pending_years = collections.deque([until.year] if start_year is None else range(start_year, until.year + 1))
    while pending_years:
        year = pending_years.popleft()
        cache_path = year_cache_path(cache_dir, user, 'github-graphql', year, until)
        cached = cache_path is not None and cache_path.is_file()
        if cached:
            raw, headers = json.loads(cache_path.read_text(encoding='utf-8')), {}
            cached_years.append(year)
            print(f'Using historical cache {year}.json; no API request.', flush=True)
        else:
            remaining = rate_history[-1].get('remaining') if rate_history else None
            if remaining is not None and int(remaining) <= 0:
                raise RuntimeError('Rate limit exhausted; stopped before the next request')
            raw, headers = request_json('https://api.github.com/graphql', token=token, body={
                'query': graphql_query(year, until), 'variables': {'login': user},
            })
        if raw.get('errors'):
            messages = '; '.join(str(error.get('message', 'GraphQL error')) for error in raw['errors'])
            raise RuntimeError('GraphQL stopped without retry or fallback: ' + messages)
        account = raw.get('data', {}).get('user')
        if not account or account['login'].lower() != user.lower():
            raise ValueError('GitHub user was not found or the cached owner differs')
        if start_year is None:
            start_year = int(account['createdAt'][:4])
            pending_years.extend(range(start_year, until.year))
        collection = account.get('contributionsCollection')
        if not collection:
            raise ValueError(f'No contribution calendar for {year}')
        calendar = collection['contributionCalendar']
        annual = []
        for week in calendar['weeks']:
            for day in week['contributionDays']:
                if day['date'].startswith(str(year)) and day['date'] <= until.isoformat():
                    annual.append({'date': day['date'], 'count': day['contributionCount'], 'level': LEVELS[day['contributionLevel']]})
        if sum(d['count'] for d in annual) != calendar['totalContributions']:
            raise ValueError(f'{year}: annual count does not match calendar total')
        entries.extend(annual)
        rate = raw['data'].get('rateLimit', headers)
        responses.append({'year':year,'response':raw,'cached':cached})
        if not cached:
            save_year_cache(cache_path, raw)
            rate_history.append({'year':year,**rate})
            print(f'Fetched {year}; {len(annual)} dates; rate={json.dumps(rate)}', flush=True)
    entries.sort(key=lambda day: day['date'])
    return entries, {
        'user': account['login'], 'profileUrl': account['url'], 'accountCreatedAt': account['createdAt'],
        'sourceName': 'GitHub公式GraphQL API', 'sourceUrl': 'https://api.github.com/graphql',
        'sourceType': 'github-graphql', 'dataApiRequests': len(rate_history),
        'rateLimit': rate_history[-1], 'rateLimitHistory': rate_history,
        'historicalCachedYears': sorted(cached_years), 'historicalCacheThrough': until.year - 2,
        'minimumRequestIntervalSeconds': REQUEST_INTERVAL_SECONDS,
    }, {'responses':responses}


def fetch_public(user, start_year, until, *, cache_dir=None):
    base_url = 'https://github-contributions-api.jogruber.de/v4/' + urllib.parse.quote(user, safe='')
    # Account creation is needed to exclude pre-account days from activity rates.
    profile, limits = request_json('https://api.github.com/users/' + urllib.parse.quote(user, safe=''))
    if start_year is None:
        start_year = int(profile['created_at'][:4])
    entries, responses, cached_years = [], [], []
    requests = 0
    for year in range(start_year, until.year + 1):
        if year < int(profile['created_at'][:4]):
            continue
        cache_path = year_cache_path(cache_dir, user, 'public-calendar-api', year, until)
        cached = cache_path is not None and cache_path.is_file()
        if cached:
            raw = json.loads(cache_path.read_text(encoding='utf-8'))
            cached_years.append(year)
            print(f'Using historical cache {year}.json; no API request.', flush=True)
        else:
            raw, _ = request_json(base_url + f'?y={year}')
            requests += 1
        if raw.get('error') or not isinstance(raw.get('contributions'), list):
            raise ValueError(f'Public calendar API did not return contributions for {year}')
        annual = [d for d in raw['contributions'] if d['date'].startswith(str(year))]
        reported_total = raw.get('total',{}).get(str(year))
        if reported_total is None or sum(d['count'] for d in annual) != reported_total:
            raise ValueError(f'{year}: public API annual total does not match')
        entries.extend(annual)
        responses.append({'year':year,'response':raw,'cached':cached})
        if not cached:
            save_year_cache(cache_path, raw)
            print(f'Fetched public calendar {year}',flush=True)
    return entries, {
        'user': profile['login'], 'profileUrl': profile['html_url'], 'accountCreatedAt': profile['created_at'],
        'sourceName': 'GitHub Contributions API v4（第三者・公開草マップ由来）',
        'sourceUrl': base_url, 'sourceType': 'public-calendar-api', 'dataApiRequests': requests,
        'historicalCachedYears': sorted(cached_years), 'historicalCacheThrough': until.year - 2,
        'profileApiRequests': 1, 'rateLimit': limits, 'cacheMaximumSeconds': 3600,
        'minimumRequestIntervalSeconds': REQUEST_INTERVAL_SECONDS,
    }, {'responses':responses}


def validate_days(entries, start_year, until, joined=None):
    start = dt.date(start_year, 1, 1)
    days = sorted((dict(d) for d in entries if start.isoformat() <= d['date'] <= until.isoformat()), key=lambda x: x['date'])
    if len({d['date'] for d in days}) != len(days):
        raise ValueError('Duplicate contribution dates')
    if joined:
        # Some public providers omit years before account creation. Only those
        # known pre-account dates may be added; never fill post-account gaps.
        known = {d['date'] for d in days}
        cursor = start
        joined_date = dt.date.fromisoformat(joined)
        while cursor < joined_date and cursor <= until:
            if cursor.isoformat() not in known:
                days.append({'date':cursor.isoformat(),'count':0,'level':0})
            cursor += dt.timedelta(days=1)
        days.sort(key=lambda d:d['date'])
    if len(days) != (until - start).days + 1:
        raise ValueError('Missing or duplicate days in the requested period; no missing day will be invented as zero')
    for index, day in enumerate(days):
        if day['date'] != (start + dt.timedelta(days=index)).isoformat():
            raise ValueError('Date coverage is not contiguous')
        if type(day['count']) is not int or day['count'] < 0 or type(day['level']) is not int or day['level'] not in range(5):
            raise ValueError('Invalid contribution count or level')
        if (day['count'] == 0) != (day['level'] == 0):
            raise ValueError('Contribution count and level disagree')
    return days


def find_streaks(days):
    runs, run = [], []
    for day in days:
        if run and (not day['count'] or dt.date.fromisoformat(day['date']) != dt.date.fromisoformat(run[-1]['date']) + dt.timedelta(days=1)):
            runs.append({'days': len(run), 'start': run[0]['date'], 'end': run[-1]['date']})
            run = []
        if day['count']:
            run.append(day)
    if run:
        runs.append({'days': len(run), 'start': run[0]['date'], 'end': run[-1]['date']})
    return sorted(runs, key=lambda r: (-r['days'], r['start']))


def statistics(days, joined):
    total = sum(d['count'] for d in days)
    active = sum(d['count'] > 0 for d in days)
    eligible = sum(d['date'] >= joined for d in days)
    runs = find_streaks(days)
    peak = max((d['count'] for d in days), default=0)
    return {
        'total': total, 'observedDays': len(days), 'eligibleDays': eligible, 'activeDays': active,
        'activeRate': round(active / eligible * 100, 2) if eligible else 0,
        'averagePerDay': round(total / eligible, 3) if eligible else 0,
        'averagePerActiveDay': round(total / active, 3) if active else 0,
        'maxDailyCount': peak, 'peakDates': [d['date'] for d in days if d['count'] == peak],
        'longestStreak': runs[0] if runs else {'days': 0, 'start': None, 'end': None},
    }


def build_report(entries, metadata, start_year, until):
    joined = metadata['accountCreatedAt'][:10]
    days = validate_days(entries, start_year, until, joined)
    summary = statistics(days, joined)
    runs = find_streaks(days)
    summary['currentStreak'] = next((r for r in runs if r['end'] == until.isoformat()), {'days': 0, 'start': None, 'end': None})
    active = [d for d in days if d['count']]
    summary['firstActiveDate'] = active[0]['date'] if active else None
    summary['latestActiveDate'] = active[-1]['date'] if active else None
    years, months = [], []
    for year in range(start_year, until.year + 1):
        annual = [d for d in days if d['date'].startswith(str(year))]
        item = dict(statistics(annual, joined), year=year, partial=annual[-1]['date'][5:] != '12-31', through=annual[-1]['date'])
        previous = [d for d in days if d['date'].startswith(str(year - 1)) and d['date'][5:] <= annual[-1]['date'][5:]]
        prior = sum(d['count'] for d in previous)
        item['comparisonPreviousTotal'] = prior if year > start_year else None
        item['comparisonChangePercent'] = round((item['total'] / prior - 1) * 100, 2) if prior else None
        years.append(item)
        for month in range(1, 13):
            monthly = [d for d in annual if d['date'][5:7] == f'{month:02d}']
            if monthly:
                month_end = (dt.date(year + (month == 12), month % 12 + 1, 1) - dt.timedelta(days=1)).isoformat()
                months.append(dict(statistics(monthly, joined), month=f'{year}-{month:02d}', partial=monthly[-1]['date'] != month_end))
    weekdays = []
    for wd in range(7):
        selected = [d for d in days if d['date'] >= joined and dt.date.fromisoformat(d['date']).weekday() == wd]
        item = dict(statistics(selected, joined), weekday=wd, label='月火水木金土日'[wd])
        weekdays.append(item)
    meta = dict(metadata)
    meta.update(periodStart=f'{start_year}-01-01', periodEnd=until.isoformat(), cutoffTimezone='Asia/Tokyo', palette=PALETTE,
                preAccountDaysExcludedFromRates=sum(d['date'] < joined for d in days),
                futureDaysExcluded=(dt.date(until.year, 12, 31) - until).days,
                dayBoundary='GitHub dates are preserved; no timezone redistribution')
    return {
        'metadata': meta, 'summary': summary, 'days': days, 'years': years, 'months': months, 'weekdays': weekdays,
        'topDays': sorted(active, key=lambda d: (-d['count'], d['date']))[:10], 'topStreaks': runs[:10],
    }


def csv_text(rows, fields):
    stream = io.StringIO(newline='')
    writer = csv.DictWriter(stream, fieldnames=fields, extrasaction='ignore', lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue()


def profile_images(image_base=''):
    prefix = image_base.rstrip('/') + '/' if image_base else ''
    return (
        f'![profile-dark.webp]({prefix}profile-dark.webp#gh-dark-mode-only) \\\n'
        f'![profile-light.webp]({prefix}profile-light.webp#gh-light-mode-only)\n'
    )


def embed_markdown(repository, branch):
    images = profile_images(f'https://raw.githubusercontent.com/{repository}/{branch}')
    sibling = profile_images('/../' + branch)
    return (f'# READMEへの埋め込み\n\n'
            f'[{repository} / {branch}](https://github.com/{repository}/tree/{branch})\n\n'
            f'{images}\n'
            f'## 同じリポジトリの別ブランチから参照\n\n```markdown\n{sibling}```\n\n'
            f'## 別のリポジトリから参照\n\n```markdown\n{images}```\n')


def write_outputs(report, raw, destination, repository, branch):
    from render_report import render_html, render_svg, render_preview_svg
    destination.mkdir(parents=True, exist_ok=True)
    metadata = report['metadata']
    user, until = metadata['user'], metadata['periodEnd']
    light_svg, dark_svg = render_svg(report), render_svg(report,theme='dark')
    light_html, dark_html = render_html(report), render_html(report,theme='dark')
    outputs = {
        'index.html': light_html, 'contributions.svg': light_svg,
        'profile-light.svg': light_svg, 'profile-dark.svg': dark_svg,
        'profile-light3.svg': render_preview_svg(report), 'profile-dark3.svg': render_preview_svg(report,theme='dark'),
        'profile-light.html': light_html, 'profile-dark.html': dark_html,
        'data.json': json.dumps(report, ensure_ascii=False, indent=2),
        'source.json': json.dumps(raw, ensure_ascii=False, indent=2),
        'daily.csv': csv_text([dict(d, weekday='月火水木金土日'[dt.date.fromisoformat(d['date']).weekday()], before_account_created=str(d['date'] < metadata['accountCreatedAt'][:10]).lower()) for d in report['days']], ['date', 'weekday', 'count', 'level', 'before_account_created']),
        'yearly.csv': csv_text(report['years'], ['year', 'through', 'partial', 'total', 'eligibleDays', 'activeDays', 'activeRate', 'averagePerDay', 'maxDailyCount', 'comparisonPreviousTotal', 'comparisonChangePercent']),
        'monthly.csv': csv_text(report['months'], ['month', 'partial', 'total', 'eligibleDays', 'activeDays', 'activeRate', 'averagePerDay', 'maxDailyCount']),
        '.nojekyll': '',
    }
    image_base = f'https://raw.githubusercontent.com/{repository}/{branch}'
    snippet = profile_images(image_base)
    relative = profile_images()
    outputs['embed.md'] = embed_markdown(repository, branch) + f'\n対象：{user}。更新日：{until}。\n'
    outputs['README.md'] = f'# {user} contribution archive\n{metadata["periodStart"]} — {until}\n{relative}\n[全体画像：黒](profile-dark.webp) · [全体画像：白](profile-light.webp) · [README貼り付け用コード](embed.md)\n## ダイアログ\n[ダイアログHTML](dialog.html)をブラウザーまたはGitHub Pagesで開くと、プレビューをクリックして全体を表示できます。画像内蔵の単独HTMLです。\n全体表示：index.html、profile-dark.html。\n日別CSV：daily.csv。年別CSV：yearly.csv。月別CSV：monthly.csv。全データ：data.json。\n累計{report["summary"]["total"]:,}件・活動{report["summary"]["activeDays"]:,}日。\n'
    for name, content in outputs.items():
        (destination / name).write_text(content, encoding='utf-8')
    return snippet


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--user', default=os.environ.get('CONTRIBUTION_USER') or os.environ.get('GITHUB_REPOSITORY_OWNER'))
    parser.add_argument('--start-year', type=int, default=os.environ.get('START_YEAR') or None,
                        help='First year; defaults to the target account creation year')
    parser.add_argument('--until', type=dt.date.fromisoformat, default=dt.datetime.now(ZoneInfo('Asia/Tokyo')).date())
    parser.add_argument('--source', choices=['auto', 'graphql', 'public'], default=os.environ.get('CONTRIBUTION_SOURCE', 'auto'))
    parser.add_argument('--input', type=Path, help='Read an existing normalized archive JSON; no network requests')
    parser.add_argument('--cache-dir', type=Path, help='Reuse complete years at least two calendar years old')
    parser.add_argument('--output', type=Path, default=Path('dist'))
    parser.add_argument('--repository', default=os.environ.get('GITHUB_REPOSITORY'))
    parser.add_argument('--branch', default=os.environ.get('OUTPUT_BRANCH', 'contribution-graphs'))
    args = parser.parse_args(argv)
    if (args.start_year is not None and not 1 <= args.start_year <= args.until.year) or args.until > dt.datetime.now(ZoneInfo('Asia/Tokyo')).date():
        parser.error('start-year must be positive and no later than the end year; the end date cannot be in the future')
    if args.input:
        raw = json.loads(args.input.read_text(encoding='utf-8'))
        if not isinstance(raw.get('metadata'), dict) or not isinstance(raw.get('days'), list):
            parser.error('--input requires a normalized data.json with metadata and days')
        metadata, entries = dict(raw['metadata']), raw['days']
        if args.start_year is None:
            args.start_year = dt.date.fromisoformat(metadata['periodStart']).year
        if args.user and args.user.casefold() != metadata['user'].casefold():
            parser.error('--user differs from the input snapshot owner')
        metadata['sourceName'] = '保存済みデータ（オフライン再生成）'
        metadata['dataApiRequests'] = 0
        metadata['sourceType'] = 'offline-snapshot'
    else:
        if not args.user or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})', args.user):
            parser.error('Specify a valid --user or GITHUB_REPOSITORY_OWNER')
        token = os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN')
        use_graphql = args.source == 'graphql' or (args.source == 'auto' and bool(token))
        cache_options = {'cache_dir': args.cache_dir} if args.cache_dir else {}
        if use_graphql:
            entries, metadata, raw = fetch_graphql(args.user, args.start_year, args.until, token, **cache_options)
        else:
            entries, metadata, raw = fetch_public(args.user, args.start_year, args.until, **cache_options)
        metadata['dataFetchedAt'] = dt.datetime.now(dt.timezone.utc).isoformat()
    if args.start_year is None:
        args.start_year = int(metadata['accountCreatedAt'][:4])
    if args.start_year > args.until.year:
        parser.error('The end date precedes the target account creation year')
    repository = args.repository or metadata['user'] + '/' + metadata['user']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repository):
        parser.error('repository must be OWNER/REPO')
    if not re.fullmatch(r'[A-Za-z0-9_-]+', args.branch):
        parser.error('Output branch must contain only letters, digits, underscores and hyphens')
    report = build_report(entries, metadata, args.start_year, args.until)
    snippet = write_outputs(report, raw, args.output, repository, args.branch)
    print(f'{metadata["user"]}: {report["summary"]["total"]:,} contributions; {len(report["days"]):,} days; source={metadata["sourceType"]}')
    print('Rate limit:', json.dumps(metadata.get('rateLimit', {}), ensure_ascii=False))
    print(snippet)
    return report


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print(f'Generation failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
