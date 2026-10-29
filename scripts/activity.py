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

from generate import request_json

SCHEMA = 2
MAX_PAGES = 49  # At most 49 GraphQL calls + one avatar download.
REPOSITORIES = '''repositories(first: 100, after: $cursor, ownerAffiliations: [OWNER],
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
    'reviewed': 'is:pr reviewed-by:',
}


def query(user, first):
    searches = '\n'.join(f'{key}: search(type: ISSUE, first: 1, query: "is:public {value}{user}") {{issueCount}}'
                         for key, value in FILTERS.items()) if first else ''
    identity = 'login avatarUrl(size: 128) followers {totalCount}' if first else 'login'
    return f'''query Activity($login: String!, $cursor: String) {{
      user(login: $login) {{ {identity} {REPOSITORIES} }}
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


def collect(user, token, cache_dir, today=None, request=request_json, avatar=fetch_avatar):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]{0,38}', user):
        raise ValueError('Invalid user name')
    today = today or dt.datetime.now(dt.timezone.utc).date().isoformat()
    file = Path(cache_dir) / user.lower() / 'snapshot.json'
    previous = json.loads(file.read_text(encoding='utf-8')) if file.exists() else {}
    same_owner = previous.get('schema') == SCHEMA and previous.get('user', '').lower() == user.lower()
    week = dt.date.fromisoformat(today).strftime('%G-W%V')
    if same_owner and previous.get('week') == week:
        print('Activity snapshot: weekly Actions cache hit; 0 API requests.')
        return previous
    if not token:
        raise ValueError('Activity generation requires GH_TOKEN or GITHUB_TOKEN')
    cursor, seen, repos, model = None, set(), [], {}
    for page in range(MAX_PAGES):
        raw, _ = request('https://api.github.com/graphql', token=token, body={
            'query': query(user, page == 0), 'variables': {'login': user, 'cursor': cursor}})
        if raw.get('errors'):
            raise RuntimeError('Activity GraphQL failed: ' + '; '.join(e.get('message', 'error') for e in raw['errors']))
        data = raw['data']
        account = data.get('user')
        if not account or account['login'].lower() != user.lower():
            raise ValueError('Activity account mismatch or missing account')
        if page == 0:
            model = {'schema': SCHEMA, 'user': account['login'], 'date': today, 'week': week,
                     'counts': {key: data[key]['issueCount'] for key in FILTERS},
                     'followers': account['followers']['totalCount'],
                     'avatarUrl': account['avatarUrl']}
        connection = account['repositories']
        for repo in connection['nodes']:
            if repo['id'] not in seen:
                seen.add(repo['id'])
                repos.append(repo)
        has_next = connection['pageInfo']['hasNextPage']
        if not has_next:
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
    print(f'Activity: {page + 1} GraphQL request(s), {0 if cached_avatar else 1} avatar download; '
          f'{len(repos)}/{model["repositories"]} public non-fork repositories.')
    return model


ICONS = {
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


def render(model, theme='light', preview=False):
    dark = theme == 'dark'
    bg, panel, fg, muted, border, accent = ('#0d1117', '#161b22', '#e6edf3', '#9da7b3', '#30363d', '#79c0ff') if dark else ('#ffffff', '#f6f8fa', '#1f2328', '#59636e', '#d1d9e0', '#0969da')
    height = 600 if preview else 800
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" width="800" height="{height}" viewBox="0 0 800 {height}" role="img" aria-labelledby="title desc">',
             f'<title id="title">{escape(model["user"])} · GitHub activity</title>',
             '<desc id="desc">Public pull requests, issues, reviewed pull requests, repositories and language distribution.</desc>',
             '<defs><clipPath id="avatar"><circle cx="58" cy="58" r="26"/></clipPath><linearGradient id="fade" x2="0" y2="1"><stop offset="0" stop-color="white"/><stop offset="1" stop-color="black"/></linearGradient><mask id="preview"><rect width="800" height="450" fill="white"/><rect y="450" width="800" height="150" fill="url(#fade)"/></mask></defs>',
             f'<g font-family="Liberation Sans, Arial, sans-serif" fill="{fg}"' + (' mask="url(#preview)"' if preview else '') + '>',
             f'<rect x=".5" y=".5" width="799" height="799" rx="18" fill="{bg}" stroke="{border}"/>']
    def text(x, y, value, size=14, color=None, extra=''):
        parts.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color or fg}" {extra}>{escape(str(value))}</text>')
    def icon(name, x, y):
        parts.append(f'<g transform="translate({x},{y}) scale(.75)" fill="none" stroke="{muted}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</g>')
    def row(x, y, name, label, value):
        icon(name, x, y - 15)
        text(x + 29, y, label)
        text(x + 314, y, f'{value:,}', 17, extra='text-anchor="end" font-weight="600"')
    def card(x, y, title, subtitle):
        parts.append(f'<rect x="{x}" y="{y}" width="356" height="234" rx="12" fill="{panel}" stroke="{border}"/>')
        text(x + 20, y + 31, title, 17, accent, 'font-weight="600"')
        text(x + 20, y + 52, subtitle, 11, muted)
    parts.append(f'<image x="32" y="32" width="52" height="52" clip-path="url(#avatar)" xlink:href="{escape(model["avatar"], quote=True)}"/>')
    text(100, 52, model['user'], 22, extra='font-weight="700"')
    text(100, 77, 'GitHub activity', 14, muted)
    text(768, 49, model['date'], 12, muted, 'text-anchor="end"')
    text(768, 72, 'Public data', 12, muted, 'text-anchor="end"')
    c = model['counts']
    card(32, 110, 'Pull requests', 'Authored · all time')
    card(412, 110, 'Issues & reviews', 'Authored issues · all time')
    for i, (label, value) in enumerate([('Created', c['prOpen']+c['prMerged']+c['prClosed']), ('Merged', c['prMerged']), ('Open', c['prOpen']), ('Closed, unmerged', c['prClosed'])]):
        row(52, 198 + i*38, 'pr', label, value)
    for i, (kind, label, value) in enumerate([('issue','Issues created', c['issueOpen']+c['issueClosed']), ('issue','Issues open',c['issueOpen']), ('issue','Issues closed',c['issueClosed']), ('review','PRs reviewed',c['reviewed'])]):
        row(432, 198+i*38, kind, label, value)
    text(32, 385, 'Repositories & community', 18, accent, 'font-weight="600"')
    text(32, 407, 'Owned · public · forks excluded' + (' · PARTIAL SAMPLE' if model['partial'] else ''), 12, muted)
    items = [('repo','Repositories',model['repositories']), ('star','Stars received',model['stars']),
             ('archive','Archived',model['archived']), ('fork','Forks received',model['forks']),
             ('release','Releases',model['releases']), ('people','Followers',model['followers'])]
    for i, (kind,label,value) in enumerate(items):
        row(32 + i%2*380, 442+i//2*38, kind,label,value)
    parts.append(f'<path d="M32 544H768" stroke="{border}"/>')
    text(32, 580, 'Language distribution', 18, accent, 'font-weight="600"')
    languages = model['languages']
    total = sum(l['size'] for l in languages)
    top = [dict(l) for l in languages[:7]]
    if len(languages)>7:
        top.append({'name': 'Other languages', 'size':sum(l['size'] for l in languages[7:]), 'color': '#8b949e'})
    x = 32
    for item in top:
        color = item['color'] if re.fullmatch(r'#[0-9a-fA-F]{6}', item['color']) else '#8b949e'
        width = 736 * item['size'] / total
        parts.append(f'<rect x="{x:.3f}" y="603" width="{width:.3f}" height="12" fill="{color}"/>')
        x += width
    if not top:
        text(32, 615, 'No detected languages', 14, muted)
    for i, item in enumerate(top):
        x, y = 32 + i%2*380, 645+i//2*25
        color = item['color'] if re.fullmatch(r'#[0-9a-fA-F]{6}', item['color']) else '#8b949e'
        parts.append(f'<circle cx="{x+5}" cy="{y-5}" r="4" fill="{color}"/>')
        text(x+18, y, item['name'], 13)
        text(x+356, y, f'{100*item["size"]/total:.1f}%', 13, muted, 'text-anchor="end"')
    text(32, 755, f'Language bytes across {model["sampled"]:,} / {model["repositories"]:,} public, non-fork repositories.', 11, muted)
    text(32, 775, 'Repository contents, not personal lines of code. Reviews count distinct PRs.', 11, muted)
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
    model = collect(args.user, os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN'), args.cache_dir)
    write_outputs(model,args.directory,os.environ.get('GITHUB_REPOSITORY',''),os.environ.get('OUTPUT_BRANCH','contribution-graphs'))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        from deploy import redact_diagnostics
        print('Activity generation failed: ' + redact_diagnostics(str(exc)),file=sys.stderr)
        sys.exit(1)
