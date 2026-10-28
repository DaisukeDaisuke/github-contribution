#!/usr/bin/env python3
"""Publish generated files to an explicitly opted-in repository branch."""
import argparse
import base64
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from generate import profile_images, request_json

MARKER = '.contribution-map'
MARKER_CONTENT = 'Managed output branch for GitHub Contribution Archive.\n'
REQUIRED_OUTPUTS = ('contributions.svg', 'index.html', 'data.json', 'daily.csv', 'README.md', 'embed.md')


def git(*args, cwd=None, env=None, check=True):
    return subprocess.run(['git', *args], cwd=cwd, env=env, check=check,
                          text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def configuration(environ=None):
    environ = os.environ if environ is None else environ
    names = ('DEPLOY_REPOSITORY', 'DEPLOY_BRANCH', 'DEPLOY_TOKEN')
    values = tuple(environ.get(name, '').strip() for name in names)
    if not any(values):
        return None
    missing = [name for name, value in zip(names, values) if not value]
    if missing:
        raise ValueError('External deployment requires all settings; missing: ' + ', '.join(missing))
    repository, branch, token = values
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9_.-]+', repository):
        raise ValueError('DEPLOY_REPOSITORY must be OWNER/REPOSITORY')
    if branch.startswith(('refs/', '-')) or branch == 'HEAD':
        raise ValueError('DEPLOY_BRANCH must be an unqualified branch name')
    git('check-ref-format', 'refs/heads/' + branch)
    return repository, branch, token


def authentication_environment(token):
    # Credentials stay in the child environment, never the URL, argv or git config.
    env = {key: value for key, value in os.environ.items()
           if not key.startswith('GIT_') and key != 'DEPLOY_TOKEN'}
    encoded = base64.b64encode(('x-access-token:' + token).encode('utf-8')).decode('ascii')
    env.update({
        'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
        'GIT_TERMINAL_PROMPT': '0', 'GIT_CONFIG_COUNT': '3',
        'GIT_CONFIG_KEY_0': 'http.https://github.com/.extraheader',
        'GIT_CONFIG_VALUE_0': 'AUTHORIZATION: basic ' + encoded,
        'GIT_CONFIG_KEY_1': 'credential.helper', 'GIT_CONFIG_VALUE_1': '',
        'GIT_CONFIG_KEY_2': 'core.hooksPath', 'GIT_CONFIG_VALUE_2': os.devnull,
    })
    return env


def default_branch(repository, token):
    metadata, _ = request_json('https://api.github.com/repos/' + repository, token=token)
    branch = metadata.get('default_branch')
    if not isinstance(branch, str) or not branch:
        raise ValueError('Cannot determine the destination default branch; deployment refused')
    return branch


def refuse_default(branch, read_default):
    current_default = read_default()
    if not current_default or branch == current_default:
        raise ValueError('Deployment to the destination default branch is forbidden')


def remote_head(repo, branch, env):
    ref = 'refs/heads/' + branch
    result = git('ls-remote', '--heads', 'origin', ref, cwd=repo, env=env).stdout
    for line in result.splitlines():
        sha, name = line.split('\t', 1)
        if name == ref:
            return sha
    return None


def publish_to_remote(source, remote_url, branch, read_default, *, env=None, overrides=None):
    """Use an isolated repo; local bare remotes can exercise the same push path."""
    source = Path(source).resolve()
    files = list(source.iterdir())
    if any(not (source / name).is_file() for name in REQUIRED_OUTPUTS):
        raise ValueError('Generated output is incomplete')
    if any(path.is_symlink() or not path.is_file() or path.name.casefold() == '.git' for path in files):
        raise ValueError('Generated output must contain only regular files')
    git('check-ref-format', 'refs/heads/' + branch, env=env)
    refuse_default(branch, read_default)
    ref = 'refs/heads/' + branch
    with tempfile.TemporaryDirectory(prefix='contribution-deploy-') as temporary:
        repo = Path(temporary)
        git('init', '--quiet', cwd=repo, env=env)
        git('remote', 'add', 'origin', remote_url, cwd=repo, env=env)
        original = remote_head(repo, branch, env)
        if original:
            # Fetch only the destination branch; never fetch or copy default-branch files.
            git('fetch', '--depth=1', 'origin', ref, cwd=repo, env=env)
            fetched = git('rev-parse', 'FETCH_HEAD', cwd=repo, env=env).stdout.strip()
            if fetched != original:
                raise RuntimeError('Destination branch changed during inspection; stopped without retry')
            marker = git('ls-tree', fetched, '--', MARKER, cwd=repo, env=env).stdout.strip()
            if not marker or marker.split()[0] not in ('100644', '100755'):
                raise ValueError('Existing destination branch has no regular ' + MARKER + '; deployment refused')
            git('switch', '--detach', fetched, cwd=repo, env=env)
            # A marked branch is managed output: remove old files but retain its history.
            git('rm', '-r', '--ignore-unmatch', '--', '.', cwd=repo, env=env)
        else:
            # This repository has no source commit or default-branch checkout to inherit.
            git('switch', '--orphan', 'generated-output', cwd=repo, env=env)
        for path in files:
            shutil.copy2(path, repo / path.name)
        for name, content in (overrides or {}).items():
            if name not in REQUIRED_OUTPUTS:
                raise ValueError('Only generated output files may be overridden')
            (repo / name).write_text(content, encoding='utf-8')
        (repo / MARKER).write_text(MARKER_CONTENT, encoding='utf-8')
        git('config', 'user.name', 'github-actions[bot]', cwd=repo, env=env)
        git('config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com', cwd=repo, env=env)
        git('add', '--all', cwd=repo, env=env)
        changed = git('diff', '--cached', '--quiet', cwd=repo, env=env, check=False).returncode
        if changed == 0:
            print('No external deployment changes; branch left unchanged.')
            return False
        if changed != 1:
            raise RuntimeError('Could not inspect external deployment changes')
        git('commit', '-m', 'Update contribution archive', cwd=repo, env=env)
        # Recheck both settings and remote state immediately before a normal push.
        refuse_default(branch, read_default)
        if remote_head(repo, branch, env) != original:
            raise RuntimeError('Destination branch changed before push; stopped without retry')
        git('push', 'origin', 'HEAD:' + ref, cwd=repo, env=env)
        print('Published generated files to destination branch ' + branch)
        return True


def publish_external(source, repository, branch, token):
    # Validate direct Python callers as well as the command-line environment.
    repository, branch, token = configuration({'DEPLOY_REPOSITORY': repository, 'DEPLOY_BRANCH': branch, 'DEPLOY_TOKEN': token})
    base = f'https://raw.githubusercontent.com/{repository}/{branch}'
    embed = ('# READMEへの埋め込み\n## 同じリポジトリの別ブランチから参照\n```markdown\n'
             + profile_images('/../' + branch) + '\n```\n'
             + '## 同じブランチから参照\n```markdown\n' + profile_images() + '\n```\n'
             + '## 別のリポジトリから参照\n```markdown\n' + profile_images(base) + '\n```\n')
    return publish_to_remote(
        source, 'https://github.com/' + repository + '.git', branch,
        lambda: default_branch(repository, token),
        env=authentication_environment(token), overrides={'embed.md': embed},
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('dist'))
    parser.add_argument('--check-config', action='store_true', help='Validate settings without network access')
    options = parser.parse_args(argv)
    settings = configuration()
    if settings is None:
        print('External deployment disabled; DEPLOY_REPOSITORY, DEPLOY_BRANCH and DEPLOY_TOKEN are unset.')
        return
    if options.check_config:
        print('External deployment settings are complete.')
        return
    publish_external(options.directory, *settings)


if __name__ == '__main__':
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f'Deployment failed: git {exc.cmd[1]} exited {exc.returncode}; no force push or retry was attempted.', file=sys.stderr)
        raise SystemExit(1)
    except (ValueError, RuntimeError, OSError, KeyError) as exc:
        print('Deployment failed: ' + str(exc), file=sys.stderr)
        raise SystemExit(1)
