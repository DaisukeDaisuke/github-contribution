import base64
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import deploy


class DeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.remote = self.base / 'destination.git'
        self.writer = self.base / 'writer'
        self.source = self.base / 'dist'
        self.writer.mkdir(); self.source.mkdir()
        self.git('init', '--bare', str(self.remote), cwd=self.base)
        self.git('init', '-b', 'trunk', cwd=self.writer)
        for repo in (self.writer, self.remote):
            self.git('config', 'user.name', 'Test', cwd=repo)
            self.git('config', 'user.email', 'test@example.invalid', cwd=repo)
        (self.writer / 'main-only.txt').write_text('Keep the default branch intact\n', encoding='utf-8')
        self.git('add', '.', cwd=self.writer)
        self.git('commit', '-m', 'Default branch contents', cwd=self.writer)
        self.git('remote', 'add', 'origin', str(self.remote), cwd=self.writer)
        self.git('push', 'origin', 'trunk', cwd=self.writer)
        self.git('symbolic-ref', 'HEAD', 'refs/heads/trunk', cwd=self.remote)
        self.default_head = self.head('trunk')
        for name in deploy.REQUIRED_OUTPUTS:
            (self.source / name).write_text('generated ' + name + '\n', encoding='utf-8')

    def git(self, *args, cwd):
        return subprocess.run(['git', *args], cwd=cwd, check=True, text=True,
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout.strip()

    def head(self, branch):
        return self.git('rev-parse', 'refs/heads/' + branch, cwd=self.remote)

    def read_default(self):
        return self.git('symbolic-ref', '--short', 'HEAD', cwd=self.remote)

    def publish(self, **kwargs):
        return deploy.publish_to_remote(self.source, str(self.remote), 'profile-images',
                                        kwargs.pop('read_default', self.read_default), **kwargs)

    def existing_branch(self, marker=None):
        self.git('switch', '-c', 'profile-images', cwd=self.writer)
        if marker == 'file':
            (self.writer / deploy.MARKER).write_text('', encoding='utf-8')
        elif marker == 'symlink':
            (self.writer / deploy.MARKER).symlink_to('main-only.txt')
        elif marker == 'directory':
            (self.writer / deploy.MARKER).mkdir()
            (self.writer / deploy.MARKER / 'file').write_text('not a marker file', encoding='utf-8')
        (self.writer / 'stale.txt').write_text('old output', encoding='utf-8')
        self.git('add', '.', cwd=self.writer)
        self.git('commit', '-m', 'Existing output branch', cwd=self.writer)
        self.git('push', 'origin', 'profile-images', cwd=self.writer)
        return self.head('profile-images')

    def test_missing_branch_gets_independent_root_without_default_files(self):
        with patch.object(deploy, 'git', wraps=deploy.git) as calls:
            self.assertTrue(self.publish())
        head = self.head('profile-images')
        self.assertEqual(self.git('rev-list', '--parents', '-n', '1', head, cwd=self.remote), head)
        files = self.git('ls-tree', '--name-only', head, cwd=self.remote).splitlines()
        self.assertEqual(set(files), set(deploy.REQUIRED_OUTPUTS) | {deploy.MARKER})
        self.assertEqual(self.head('trunk'), self.default_head)
        pushes = [call.args for call in calls.call_args_list if call.args[0] == 'push']
        self.assertEqual(pushes, [('push', 'origin', 'HEAD:refs/heads/profile-images')])

    def test_marked_existing_branch_keeps_parent_and_replaces_only_its_contents(self):
        original = self.existing_branch('file')
        self.assertTrue(self.publish())
        current = self.head('profile-images')
        self.assertEqual(self.git('rev-parse', current + '^', cwd=self.remote), original)
        files = self.git('ls-tree', '--name-only', current, cwd=self.remote).splitlines()
        self.assertEqual(set(files), set(deploy.REQUIRED_OUTPUTS) | {deploy.MARKER})
        self.assertEqual(self.head('trunk'), self.default_head)
        self.assertFalse(self.publish())
        self.assertEqual(self.head('profile-images'), current)

    def test_unmarked_existing_branch_is_unchanged(self):
        original = self.existing_branch()
        with patch.object(deploy, 'git', wraps=deploy.git) as calls:
            with self.assertRaisesRegex(ValueError, 'no regular .contribution-map'):
                self.publish()
        self.assertEqual(self.head('profile-images'), original)
        self.assertFalse(any(call.args[0] == 'push' for call in calls.call_args_list))

    def test_symlink_or_directory_is_not_an_opt_in_marker(self):
        original = self.existing_branch('symlink')
        with self.assertRaisesRegex(ValueError, 'no regular .contribution-map'):
            self.publish()
        self.assertEqual(self.head('profile-images'), original)
        (self.writer / deploy.MARKER).unlink()
        (self.writer / deploy.MARKER).mkdir()
        (self.writer / deploy.MARKER / 'file').write_text('not a marker', encoding='utf-8')
        self.git('add', '.', cwd=self.writer)
        self.git('commit', '-m', 'Directory marker is invalid', cwd=self.writer)
        self.git('push', 'origin', 'profile-images', cwd=self.writer)
        original = self.head('profile-images')
        with self.assertRaisesRegex(ValueError, 'no regular .contribution-map'):
            self.publish()
        self.assertEqual(self.head('profile-images'), original)

    def test_actual_default_branch_is_rejected_even_with_marker(self):
        (self.writer / deploy.MARKER).write_text('', encoding='utf-8')
        self.git('add', '.', cwd=self.writer)
        self.git('commit', '-m', 'Marker does not permit default branch writes', cwd=self.writer)
        self.git('push', 'origin', 'trunk', cwd=self.writer)
        original = self.head('trunk')
        with self.assertRaisesRegex(ValueError, 'default branch is forbidden'):
            deploy.publish_to_remote(self.source, str(self.remote), 'trunk', self.read_default)
        self.assertEqual(self.head('trunk'), original)

    def test_default_branch_is_checked_again_before_push(self):
        with patch.object(deploy, 'git', wraps=deploy.git) as calls:
            with self.assertRaisesRegex(ValueError, 'default branch is forbidden'):
                self.publish(read_default=iter(['trunk', 'profile-images']).__next__)
        self.assertFalse(any(call.args[0] == 'push' for call in calls.call_args_list))

    def test_destination_moving_during_preparation_is_not_overwritten(self):
        original = self.existing_branch('file')
        checks = []
        advanced = []
        def read_default():
            checks.append(True)
            if len(checks) == 2:
                tree = self.git('rev-parse', original + '^{tree}', cwd=self.remote)
                commit = self.git('commit-tree', tree, '-p', original, '-m', 'Concurrent update', cwd=self.remote)
                self.git('update-ref', 'refs/heads/profile-images', commit, original, cwd=self.remote)
                advanced.append(commit)
            return 'trunk'
        with self.assertRaisesRegex(RuntimeError, 'changed before push'):
            self.publish(read_default=read_default)
        self.assertEqual(self.head('profile-images'), advanced[0])

    def test_incomplete_or_symlinked_output_does_not_push(self):
        (self.source / 'daily.csv').unlink()
        with self.assertRaisesRegex(ValueError, 'incomplete'):
            self.publish()
        (self.source / 'daily.csv').symlink_to(self.writer / 'main-only.txt')
        with self.assertRaisesRegex(ValueError, 'regular files'):
            self.publish()

    def test_settings_are_optional_but_partial_settings_fail_closed(self):
        self.assertIsNone(deploy.configuration({}))
        with self.assertRaisesRegex(ValueError, 'DEPLOY_BRANCH, DEPLOY_TOKEN'):
            deploy.configuration({'DEPLOY_REPOSITORY': 'Example/profile'})
        config = {'DEPLOY_REPOSITORY': 'Example/profile', 'DEPLOY_BRANCH': 'profile-images', 'DEPLOY_TOKEN': 'test-token'}
        self.assertEqual(deploy.configuration(config), ('Example/profile', 'profile-images', 'test-token'))
        for branch in ['--all', 'refs/heads/trunk', 'HEAD', 'bad branch', '@{-1}']:
            with self.subTest(branch=branch), self.assertRaises((ValueError, subprocess.CalledProcessError)):
                deploy.configuration(dict(config, DEPLOY_BRANCH=branch))

    def test_token_stays_out_of_urls_arguments_and_persisted_config(self):
        token = 'deployment-test-token'
        env = deploy.authentication_environment(token)
        self.assertNotIn('DEPLOY_TOKEN', env)
        expected = base64.b64encode(('x-access-token:' + token).encode()).decode()
        self.assertEqual(env['GIT_CONFIG_VALUE_0'], 'AUTHORIZATION: basic ' + expected)
        with patch.object(deploy, 'git', wraps=deploy.git) as calls:
            self.publish(env=env)
        for call in calls.call_args_list:
            self.assertNotIn(token, ' '.join(call.args))
            self.assertNotIn(expected, ' '.join(call.args))
            if call.args[0] == 'config':
                self.assertNotIn('extraheader', ' '.join(call.args))

    def test_unknown_default_branch_is_refused(self):
        with patch.object(deploy, 'request_json', return_value=({}, {})):
            with self.assertRaisesRegex(ValueError, 'Cannot determine'):
                deploy.default_branch('Example/profile', 'test-token')

    def test_public_deployer_uses_destination_auth_and_destination_embed_urls(self):
        implementation = deploy.publish_to_remote
        def local_destination(source, url, branch, read_default, **kwargs):
            self.assertEqual(url, 'https://github.com/Example/profile.git')
            self.assertEqual(branch, 'profile-images')
            return implementation(source, str(self.remote), branch, read_default, **kwargs)
        with patch.object(deploy, 'request_json', return_value=({'default_branch': 'trunk'}, {})) as request, patch.object(deploy, 'publish_to_remote', side_effect=local_destination):
            self.assertTrue(deploy.publish_external(self.source, 'Example/profile', 'profile-images', 'test-token'))
        self.assertEqual(request.call_count, 2)
        for call in request.call_args_list:
            self.assertEqual(call.args, ('https://api.github.com/repos/Example/profile',))
            self.assertEqual(call.kwargs, {'token': 'test-token'})
        embed = self.git('show', 'refs/heads/profile-images:embed.md', cwd=self.remote)
        self.assertIn('/../profile-images/profile-light.webp#gh-light-mode-only', embed)
        self.assertIn('https://raw.githubusercontent.com/Example/profile/profile-images/profile-dark.webp#gh-dark-mode-only', embed)
        self.assertEqual((self.source / 'embed.md').read_text(encoding='utf-8'), 'generated embed.md\n')

    def test_branch_created_by_another_writer_is_not_overwritten(self):
        checks = []
        def read_default():
            checks.append(True)
            if len(checks) == 2:
                self.existing_branch()
            return 'trunk'
        with self.assertRaisesRegex(RuntimeError, 'changed before push'):
            self.publish(read_default=read_default)
        self.assertEqual(self.git('show', 'refs/heads/profile-images:stale.txt', cwd=self.remote), 'old output')
        self.assertNotIn(deploy.MARKER, self.git('ls-tree', '--name-only', 'refs/heads/profile-images', cwd=self.remote))


if __name__ == '__main__':
    unittest.main()
