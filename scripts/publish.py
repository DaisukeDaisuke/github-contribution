#!/usr/bin/env python3
"""Commit generated files only to a separate branch, without force-pushing."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile


def git(*args, cwd=None, check=True):
    return subprocess.run(['git', *args], cwd=cwd, check=check, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def publish(source, branch='contribution-graphs', default_branch='main', repo=None):
    source = Path(source).resolve()
    repo = Path(repo or git('rev-parse', '--show-toplevel').stdout.strip()).resolve()
    git('check-ref-format', '--branch', branch, cwd=repo)
    if branch == default_branch:
        raise ValueError('The generated output branch must differ from the default branch')
    required = ['contributions.svg', 'index.html', 'data.json', 'daily.csv', 'README.md', 'embed.md']
    if any(not (source / name).is_file() for name in required):
        raise ValueError('Generated output is incomplete')
    ref = 'refs/heads/' + branch
    remote = git('ls-remote', '--heads', 'origin', ref, cwd=repo).stdout.strip()
    with tempfile.TemporaryDirectory(prefix='contribution-publish-') as temporary:
        target = Path(temporary) / 'worktree'
        if remote:
            git('fetch', '--depth=1', 'origin', ref, cwd=repo)
            commit = git('rev-parse', 'FETCH_HEAD', cwd=repo).stdout.strip()
        else:
            commit = git('rev-parse', 'HEAD', cwd=repo).stdout.strip()
        git('worktree', 'add', '--detach', str(target), commit, cwd=repo)
        try:
            if not remote:
                git('switch', '--orphan', branch, cwd=target)
            for path in source.iterdir():
                if path.is_symlink() or not path.is_file():
                    raise ValueError('Generated output must contain only regular files')
                shutil.copy2(path, target / path.name)
            git('config', 'user.name', 'github-actions[bot]', cwd=target)
            git('config', 'user.email', '41898282+github-actions[bot]@users.noreply.github.com', cwd=target)
            git('add', '--all', cwd=target)
            changed = git('diff', '--cached', '--quiet', cwd=target, check=False).returncode
            if changed == 0:
                print('No generated changes; branch left unchanged.')
                return
            if changed != 1:
                raise RuntimeError('Could not inspect generated changes')
            git('commit', '-m', 'Update contribution archive', cwd=target)
            git('push', 'origin', 'HEAD:' + ref, cwd=target)
            print('Published generated files to ' + branch)
        finally:
            git('worktree', 'remove', '--force', str(target), cwd=repo, check=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=Path('dist'))
    parser.add_argument('--branch', default='contribution-graphs')
    parser.add_argument('--default-branch', required=True)
    options = parser.parse_args()
    publish(options.directory, options.branch, options.default_branch)
