#!/usr/bin/env python3
"""Independent public activity card; cached inputs never enter the output directory."""
import argparse
import base64
from collections import defaultdict
import datetime as dt
from html import escape
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlparse

from generate import APIHTTPError, request_json

SCHEMA = 5
MAX_REQUESTS = 49  # Includes failed attempts; reserve one request for the avatar.
REPOSITORIES = '''repositories(first: PAGE_SIZE, after: $cursor, ownerAffiliations: [OWNER],
  privacy: PUBLIC, isFork: false, orderBy: {field: NAME, direction: ASC}) {
  totalCount pageInfo {hasNextPage endCursor}
  nodes { id isArchived stargazerCount forkCount releases {totalCount}
    languages(first: 100, orderBy: {field: SIZE, direction: DESC}) {
      totalSize edges {size node {name color}}
    }
  }
}'''
FILTERS = {
    'prOpen': 'is:pr is:open author:',
    'prMerged': 'is:pr is:merged author:',
    'prClosed': 'is:pr is:closed is:unmerged author:',
    'issueOpen': 'is:issue is:open author:',
    'issueClosed': 'is:issue is:closed author:',
    'issueNotPlanned': 'is:issue is:closed reason:"not planned" author:',
    'reviewed': 'is:pr reviewed-by:',
}


def query(user, first, include_private=False, page_size=25):
    visibility = '' if include_private else 'is:public '
    repositories = REPOSITORIES.replace('PAGE_SIZE', str(page_size))
    if include_private:
        repositories = repositories.replace('privacy: PUBLIC, ', '').replace(
            'ownerAffiliations: [OWNER]',
            'ownerAffiliations: [OWNER, COLLABORATOR, ORGANIZATION_MEMBER]')
    searches = '\n'.join(f'{key}: search(type: ISSUE, first: 1, query: {json.dumps(visibility + value + user)}) {{issueCount}}'
                         for key, value in FILTERS.items()) if first else ''
    identity = 'login createdAt avatarUrl(size: 128) followers {totalCount}' if first else 'login'
    return f'''query Activity($login: String!, $cursor: String) {{
      user(login: $login) {{ {identity} {repositories} }}
      {searches}
      rateLimit {{remaining cost}}
    }}'''


def fetch_avatar(url):
    if urlparse(url).scheme != 'https' or urlparse(url).hostname != 'avatars.githubusercontent.com':
        raise ValueError('Unexpected avatar host')
    time.sleep(1.2)
    request = urllib.request.Request(url, headers={'User-Agent': 'contribution-activity-card'})
    with urllib.request.urlopen(request, timeout=60) as response:
        content_type = response.headers.get_content_type()
        if content_type not in ('image/png', 'image/jpeg', 'image/webp'):
            raise ValueError('Unsupported avatar format')
        data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError('Avatar exceeds size limit')
    return f'data:{content_type};base64,' + base64.b64encode(data).decode('ascii')


def collect(user, token, cache_dir, today=None, request=request_json, avatar=fetch_avatar, *, include_private=False):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', user):
        raise ValueError('Invalid user name')
    today = today or dt.datetime.now(dt.timezone.utc).date().isoformat()
    scope = 'accessible' if include_private else 'public'
    file = Path(cache_dir) / scope / user.lower() / 'snapshot.json'
    previous = json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
    same_owner = previous.get('schema') == SCHEMA and previous.get('user', '').lower() == user.lower() and previous.get('scope') == scope
    week = dt.date.fromisoformat(today).strftime('%G-W%V')
    if same_owner and previous.get('week') == week:
        print('Activity snapshot: weekly Actions cache hit; 0 API requests.')
        return previous
    if not token:
        raise ValueError('Activity generation requires GH_TOKEN or GITHUB_TOKEN')
    cursor, seen, repos, model = None, set(), [], {}
    attempts, page_size = 0, 25
    for page in range(MAX_REQUESTS):
        for retry in range(3):
            attempts += 1
            remaining, cost = None, None
            total_requests, batch_size, repository_progress = 'unknown', 'unknown', 'unknown'
            try:
                raw, headers = request('https://api.github.com/graphql', token=token, body={
                    'query': query(user, page == 0, include_private, page_size),
                    'variables': {'login': user, 'cursor': cursor}})
                rate = (raw.get('data') or {}).get('rateLimit') or {}
                remaining = rate.get('remaining', headers.get('remaining'))
                cost = rate.get('cost')
                connection = ((raw.get('data') or {}).get('user') or {}).get('repositories')
                if connection:
                    batch_size = len(connection['nodes'])
                    collected = len(seen | {repo['id'] for repo in connection['nodes']})
                    total = connection['totalCount']
                    repository_progress = f'{collected}/{total}'
                    if connection['pageInfo']['hasNextPage']:
                        pages_left = max(1, (max(0, total - collected) + page_size - 1) // page_size)
                        total_requests = f'{attempts + pages_left} (estimated total)'
                    else:
                        total_requests = str(attempts)
                break
            except APIHTTPError as exc:
                remaining = exc.remaining
                from deploy import redact_diagnostics
                diagnostic = (f'GitHub API HTTP {exc.status}; request-id={exc.request_id or "not supplied"}\n'
                              'Response body (credentials redacted):\n' +
                              (exc.response_body or '(empty response body)'))
                print(redact_diagnostics(diagnostic, tokens=(token,)), file=sys.stderr, flush=True)
                if exc.status not in (502, 503, 504) or exc.remaining == '0':
                    raise
                if retry == 2 or attempts >= MAX_REQUESTS:
                    raise RuntimeError(f'Activity API HTTP {exc.status}; stopped after {retry + 1} attempts '
                                       f'for this page ({attempts}/{MAX_REQUESTS} total requests).') from None
                delay = 3 * (2 ** retry)
                if exc.retry_after:
                    # Do not retry early or introduce a long-running wait.
                    if not exc.retry_after.isdigit() or int(exc.retry_after) > 60:
                        raise
                    delay = max(delay, int(exc.retry_after))
                page_size = max(5, page_size // 2)
                print(f'Activity API HTTP {exc.status}; retry {retry + 1}/2 in {delay}s '
                      f'with {page_size} repositories per page.', flush=True)
            finally:
                # Rate limits are points, not a guaranteed number of further calls.
                def number(value):
                    return str(value) if re.fullmatch(r'[0-9]+', str(value)) else 'unknown'
                print(f'Activity API request {attempts}/{total_requests}, '
                      f'batch={batch_size} repositories, repositories={repository_progress}; '
                      f'request budget remaining={MAX_REQUESTS - attempts}/{MAX_REQUESTS}; '
                      f'rate limit remaining={number(remaining)} points; cost={number(cost)}.', flush=True)
            time.sleep(delay)
        if raw.get('errors'):
            raise RuntimeError('Activity GraphQL failed: ' + '; '.join(e.get('message', 'error') for e in raw['errors']))
        data = raw['data']
        account = data.get('user')
        if not account or account['login'].lower() != user.lower():
            raise ValueError('Activity account mismatch or missing account')
        if page == 0:
            model = {'schema': SCHEMA, 'scope': scope, 'user': account['login'], 'date': today, 'week': week,
                     'counts': {key: data[key]['issueCount'] for key in FILTERS},
                     'followers': account['followers']['totalCount'],
                     'createdAt': account['createdAt'],
                     'avatarUrl': account['avatarUrl']}
        connection = account['repositories']
        for repo in connection['nodes']:
            if repo['id'] not in seen:
                seen.add(repo['id'])
                repos.append(repo)
        has_next = connection['pageInfo']['hasNextPage']
        if not has_next or attempts >= MAX_REQUESTS:
            break
        next_cursor = connection['pageInfo']['endCursor']
        if not next_cursor or next_cursor == cursor:
            raise ValueError('Repository pagination did not advance')
        cursor = next_cursor
        if data['rateLimit']['remaining'] <= 0:
            raise RuntimeError('Activity API rate limit exhausted; no retry')
    sizes, colors = defaultdict(int), {}
    for repo in repos:
        language = repo['languages']
        for edge in language['edges']:
            name = edge['node']['name']
            sizes[name] += edge['size']
            colors[name] = edge['node']['color'] or '#8b949e'
        sizes['Other'] += max(0, language['totalSize'] - sum(e['size'] for e in language['edges']))
    model.update({'repositories': connection['totalCount'], 'sampled': len(repos), 'partial': has_next,
                  'archived': sum(r['isArchived'] for r in repos),
                  'stars': sum(r['stargazerCount'] for r in repos),
                  'forks': sum(r['forkCount'] for r in repos),
                  'releases': sum(r['releases']['totalCount'] for r in repos),
                  'languages': [{'name': name, 'size': size, 'color': colors.get(name, '#8b949e')}
                                for name, size in sorted(sizes.items(), key=lambda item: (-item[1], item[0])) if size]})
    cached_avatar = same_owner and previous.get('avatarUrl') == model['avatarUrl'] and previous.get('avatar')
    model['avatar'] = previous['avatar'] if cached_avatar else avatar(model['avatarUrl'])
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(model, ensure_ascii=False), encoding='utf-8')
    print(f'Activity: {attempts} GraphQL request(s), including retries, {0 if cached_avatar else 1} avatar download; '
          f'{len(repos)}/{model["repositories"]} {scope} non-fork repositories.')
    return model


ICONS = {
    'calendar': '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4M17 3v4M3 10h18m-14 5 3 3 6-6"/>',
    'activity': '<path d="M2 12h5l3-8 4 16 3-8h5"/>',
    'notPlanned': '<circle cx="12" cy="12" r="9"/><path d="m6 18 12-12"/>',
    'clock': '<circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 2"/>',
    'pr': '<circle cx="6" cy="4" r="2"/><circle cx="6" cy="20" r="2"/><path d="M6 6v12M14 4h2a3 3 0 0 1 3 3v11M14 4l3-3M14 4l3 3"/><circle cx="19" cy="20" r="2"/>',
    'issue': '<circle cx="12" cy="12" r="9"/><path d="M12 7v6M12 16v1"/>',
    'review': '<path d="M5 3h14v13H9l-4 4zM9 9l2 2 4-4"/>',
    'repo': '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M5 17h14M9 7h6"/>',
    'star': '<path d="m12 2 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1z"/>',
    'fork': '<circle cx="6" cy="4" r="2"/><circle cx="18" cy="4" r="2"/><circle cx="12" cy="20" r="2"/><path d="M6 6v3c0 4 12 4 12 0V6M12 12v6"/>',
    'release': '<path d="m3 12 9-9h8v8l-9 10z"/><circle cx="16" cy="7" r="1"/>',
    'archive': '<path d="M4 8h16v13H4zM3 3h18v5H3zM9 12h6"/>',
    'people': '<circle cx="9" cy="7" r="3"/><path d="M2 21v-3a7 7 0 0 1 14 0v3M16 4a3 3 0 0 1 0 6M18 14a6 6 0 0 1 4 7"/>',
}


def format_bytes(size):
    """Format GitHub language bytes using decimal B/KB/MB/GB/TB units."""
    value = float(size)
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if value < 1000 or unit == 'TB':
            number = f'{value:,.0f}' if unit == 'B' else f'{value:,.1f}'.rstrip('0').rstrip('.')
            return f'{number} {unit}'
        value /= 1000


def with_contribution_totals(model, report_path):
    """Reuse the grass map's validated totals from historical and fresh year data."""
    report = json.loads(Path(report_path).read_text(encoding='utf-8'))
    if report['metadata']['user'].lower() != model['user'].lower():
        raise ValueError('Contribution archive owner differs from activity account')
    return dict(model, activeDays=report['summary']['activeDays'], contributions=report['summary']['total'])


def render(model, theme='light', preview=False):
    dark = theme == 'dark'
    bg, panel, fg, muted, border, accent = ('#0d1117', '#161b22', '#e6edf3', '#9da7b3', '#30363d', '#79c0ff') if dark else ('#ffffff', '#f6f8fa', '#1f2328', '#59636e', '#d1d9e0', '#0969da')
    language_count = min(len(model['languages']), 8)
    has_contribution_totals = 'activeDays' in model and 'contributions' in model
    totals_height = 36 if has_contribution_totals else 0
    last_y = totals_height + (516 + ((language_count - 1) // 2) * 25 if language_count else 493)
    full_height = last_y + 32 + (26 if model['partial'] else 0)
    height = min(600, full_height) if preview else full_height
    fade_start = height - 150
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="800" height="{height}" viewBox="0 0 800 {height}" role="img" aria-labelledby="title desc">',
             f'<title id="title">{escape(model["user"])} · GitHub activity</title>',
             '<desc id="desc">Public pull requests, issues, reviewed pull requests, repositories and language distribution.</desc>',
             f'<defs><clipPath id="avatar"><circle cx="58" cy="58" r="26"/></clipPath><linearGradient id="fade" x2="0" y2="1"><stop offset="0" stop-color="white"/><stop offset="1" stop-color="black"/></linearGradient><mask id="preview"><rect width="800" height="{fade_start}" fill="white"/><rect y="{fade_start}" width="800" height="150" fill="url(#fade)"/></mask></defs>',
             f'<g font-family="Liberation Sans, Arial, sans-serif" fill="{fg}"' + (' mask="url(#preview)"' if preview else '') + '>',
             f'<rect x=".5" y=".5" width="799" height="{full_height - 1}" rx="18" fill="{bg}" stroke="{border}"/>']
    def text(x, y, value, size=14, color=None, extra=''):
        parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color or fg}" {extra}>{escape(str(value))}</text>')
    colors = {'green': '#3fb950' if dark else '#1a7f37',
              'purple': '#bc8cff' if dark else '#8250df',
              'red': '#f85149' if dark else '#cf222e',
              'blue': accent, 'gold': '#e3b341' if dark else '#9a6700', 'muted': muted}
    def row(x, y, name, label, value, color, suffix=''):
        value = f'{value:,}' if isinstance(value, int) else escape(str(value))
        parts.append(f'<g transform="translate({x},{y-15}) scale(.75)" fill="none" stroke="{colors[color]}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</g>')
        parts.append(f'<text x="{x+29}" y="{y}" font-size="15">{escape(label)} <tspan font-weight="700" font-size="20">{value}</tspan>{escape(suffix)}</text>')
    parts.append(f'<image x="32" y="32" width="52" height="52" clip-path="url(#avatar)" xlink:href="{escape(model["avatar"], quote=True)}"/>')
    text(100, 52, model['user'], 22, extra='font-weight="700"')
    text(100, 77, 'GitHub activity', 14, muted)
    text(768, 49, model['date'], 12, muted, 'text-anchor="end"')
    c = model['counts']
    items = [
        ('pr', 'PRs created', c['prOpen']+c['prMerged']+c['prClosed'], 'green'),
        ('issue', 'Issues created', c['issueOpen']+c['issueClosed'], 'green'),
        ('pr', 'PRs open', c['prOpen'], 'green'),
        ('issue', 'Issues open', c['issueOpen'], 'green'),
        ('pr', 'PRs merged', c['prMerged'], 'purple'),
        ('issue', 'Issues closed', c['issueClosed'] - c['issueNotPlanned'], 'purple'),
        ('pr', 'PRs closed, unmerged', c['prClosed'], 'red'),
        ('notPlanned', 'Issues not planned', c['issueNotPlanned'], 'muted'),
        ('repo', 'Repositories', model['repositories'], 'blue'),
        ('star', 'Stars received', model['stars'], 'gold'),
        ('archive', 'Archived repositories', model['archived'], 'muted'),
        ('fork', 'Forks received', model['forks'], 'blue'),
        ('release', 'Releases', model['releases'], 'blue'),
        ('people', 'Followers', model['followers'], 'purple'),
        ('review', 'PRs reviewed', c['reviewed'], 'blue'),
        ('clock', 'GitHub Joined', dt.datetime.fromisoformat(model['createdAt'].replace('Z', '+00:00'))
         .astimezone(dt.timezone.utc).strftime('%Y/%m/%d'), 'muted'),
    ]
    if has_contribution_totals:
        items.extend([
            ('calendar', 'Active', model['activeDays'], 'green'),
            ('activity', 'Contributions', model['contributions'], 'green'),
        ])
    for i, (kind, label, value, color) in enumerate(items):
        row(32 + i%2*380, 140+i//2*36, kind, label, value, color, ' days' if kind == 'calendar' else '')
    parts.append(f'<path d="M32 {419 + totals_height}H768" stroke="{border}"/>')
    text(32, 453 + totals_height, 'Language distribution', 18, accent, 'font-weight="600"')
    languages = model['languages']
    total = sum(l['size'] for l in languages)
    top = [dict(l) for l in languages[:7]]
    if len(languages)>7:
        top.append({'name': 'Other languages', 'size':sum(l['size'] for l in languages[7:]), 'color': '#8b949e'})
    x = 32
    for item in top:
        color = item['color'] if re.fullmatch(r'#[0-9a-fA-F]{6}', item['color']) else '#8b949e'
        width = 736 * item['size'] / total
        parts.append(f'<rect x="{x:.3f}" y="{475 + totals_height}" width="{width:.3f}" height="12" fill="{color}"/>')
        x += width
    if not top:
        text(32, 493 + totals_height, 'No detected languages', 14, muted)
    for i, item in enumerate(top):
        x, y = 32 + i%2*380, 516+totals_height+i//2*25
        color = item['color'] if re.fullmatch(r'#[0-9a-fA-F]{6}', item['color']) else '#8b949e'
        parts.append(f'<circle cx="{x+5}" cy="{y-5}" r="4" fill="{color}"/>')
        parts.append(f'<text x="{x+18}" y="{y}" font-size="13">{escape(item["name"])} <tspan fill="{muted}">{100*item["size"]/total:.1f}%</tspan><tspan dx="12" fill="{muted}">{format_bytes(item["size"])}</tspan></text>')
    if model['partial']:
        text(32, last_y + 26, f'PARTIAL SAMPLE · {model["sampled"]:,} / {model["repositories"]:,}', 11, muted)
    parts.append('</g></svg>')
    return '\n'.join(parts)


def activity_images(base=''):
    prefix = base.rstrip('/') + '/' if base else ''
    return ' \\\n'.join(f'[![activity-{theme}.webp]({prefix}activity-{theme}3.webp#gh-{theme}-mode-only)]({prefix}activity-{theme}.webp#gh-{theme}-mode-only)' for theme in ('dark', 'light')) + '\n'


def activity_embed(repository, branch):
    absolute = activity_images(f'https://raw.githubusercontent.com/{repository}/{branch}')
    return ('\n## Activity statistics\n\n' + absolute + '\n同じリポジトリの別ブランチ：\n\n```markdown\n' +
            activity_images('/../'+branch) + '```\n\n別のリポジトリ：\n\n```markdown\n' + absolute + '```\n')


def write_outputs(model, directory, repository, branch):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    for theme in ('dark', 'light'):
        for preview in (False, True):
            stem = f'activity-{theme}' + ('3' if preview else '')
            (directory / (stem+'.svg')).write_text(render(model, theme, preview), encoding='utf-8')
    for name, content in [('README.md', '\n## Activity statistics\n\n'+activity_images()),
                          ('embed.md', activity_embed(repository, branch))]:
        with (directory / name).open('a', encoding='utf-8') as file:
            file.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('dist'))
    parser.add_argument('--cache-dir', type=Path, default=Path('.cache/activity'))
    parser.add_argument('--user', default=os.environ.get('CONTRIBUTION_USER') or os.environ.get('GITHUB_REPOSITORY_OWNER'))
    parser.add_argument('--render', action='store_true')
    args = parser.parse_args()
    if args.render:
        for theme in ('dark','light'):
            for suffix in ('','3'):
                stem = f'activity-{theme}{suffix}'
                subprocess.run(['inkscape',str(args.directory/(stem+'.svg')),'--export-type=png',
                                '--export-filename='+str(args.directory/(stem+'.png')),
                                '--export-width='+('800' if suffix else '1600')],check=True)
        return
    if not args.user:
        parser.error('--user or CONTRIBUTION_USER is required')
    # Also space this process's first call from the preceding workflow step.
    time.sleep(1.2)
    model = collect(args.user, os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN'), args.cache_dir, include_private=os.environ.get('ACTIVITY_SCOPE') == 'accessible')
    model = with_contribution_totals(model, args.directory / 'data.json')
    write_outputs(model,args.directory,os.environ.get('GITHUB_REPOSITORY',''),os.environ.get('OUTPUT_BRANCH','contribution-graphs'))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        from deploy import redact_diagnostics
        print('Activity generation failed: ' + redact_diagnostics(str(exc)),file=sys.stderr)
        sys.exit(1)
