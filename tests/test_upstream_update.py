"""Updater contracts, using local archives and an in-memory GitHub API."""
import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


update = load('update_upstream', 'scripts/update-upstream.py')
publisher = load('publish_update_pr', 'scripts/publish-update-pr.py')
RELEASE = {'tag_name': 'v2026.10.1', 'published_at': '2026-10-01T10:00:00Z',
           'html_url': 'https://github.com/NousResearch/hermes-agent/releases/tag/v2026.10.1',
           'draft': False, 'prerelease': False}
COMMIT = 'a' * 40


class Preparation(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.workspace = Path(self.temp.name)
        self.root = self.workspace / 'repository'
        self.root.mkdir()
        for filename in update.FILES:
            target = self.root / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / filename, target)
        self.config = json.loads((self.root / 'packaging/config.json').read_text())
        # Keep fixtures stable when the updater advances the repository version.
        self.config.update(version='0.21.5', electron_version='40.10.2')
        (self.root / 'packaging/config.json').write_text(json.dumps(self.config))
        metadata = self.root / update.FILES[-2]
        tree = ET.parse(metadata)
        tree.getroot().find('releases/release').set('version', '0.21.5')
        tree.write(metadata)
        (self.root / 'scripts').mkdir()
        shutil.copyfile(ROOT / 'scripts/generate-manifest.py', self.root / 'scripts/generate-manifest.py')

    def archive(self, proposed='0.22.0', electron='41.0.0', nested=True):
        path = self.workspace / 'fixture.tar.gz'
        lock = {'packages': {('apps/desktop/node_modules/electron' if nested else 'node_modules/electron'):
                             {'version': electron}}}
        with tarfile.open(path, 'w:gz') as archive:
            for name, content in {'pyproject.toml': f'[project]\nversion = "{proposed}"\n',
                                  'package-lock.json': json.dumps(lock)}.items():
                data = content.encode()
                member = tarfile.TarInfo('upstream/' + name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        return path

    def test_numeric_versions_and_conflicts(self):
        update.check_version('0.9.9', '0.10.0')
        for proposed in ('0.21.5', '0.20.9', '0.22.0rc1', 'v0.22.0', '00.22.0'):
            with self.subTest(proposed=proposed), self.assertRaises(ValueError):
                update.check_version('0.21.5', proposed)

    def test_annotated_tag_resolves_to_commit(self):
        with patch.object(update, 'api', side_effect=[
            {'object': {'type': 'tag', 'sha': 'b' * 40}},
            {'object': {'type': 'commit', 'sha': COMMIT}},
        ]) as api:
            self.assertEqual(update.resolve_tag('v2026.10.1'), COMMIT)
            self.assertEqual(api.call_args.args[0], '/git/tags/' + 'b' * 40)

    def test_no_new_release_writes_nothing(self):
        release = dict(RELEASE, tag_name=self.config['upstream_tag'])
        output = self.workspace / 'output'
        with patch.object(update, 'api', return_value=[release]), \
                patch.object(update, 'resolve_tag', return_value=self.config['upstream_commit']), \
                patch.object(update, 'prepare') as prepare:
            self.assertFalse(update.run(output, self.root))
        self.assertFalse(output.exists())
        prepare.assert_not_called()

    def test_nonstable_releases_are_ignored(self):
        for flag in ('draft', 'prerelease'):
            with self.subTest(flag=flag), \
                    patch.object(update, 'api', return_value=[dict(RELEASE, **{flag: True})]), \
                    patch.object(update, 'resolve_tag') as resolve:
                self.assertFalse(update.run(self.workspace / 'output', self.root))
                resolve.assert_not_called()
        self.assertFalse((self.workspace / 'output').exists())

    def receipt_fixture(self, proposed='0.21.6', skip_bundles=True,
                        final_object='b' * 40, claim_object='c' * 40):
        release = dict(RELEASE, tag_name='v' + proposed, id=406714323)
        claim_ref = f'rc.4-v{proposed}'
        obj = {'type': 'commit', 'sha': COMMIT}
        claim = {'schema': 1, 'version': proposed, 'commit': COMMIT, 'attempt': 4,
                 'claimEpoch': 1791456120, 'autopublish': False,
                 'skipBundles': skip_bundles, 'skipTests': True}
        final = {'schema': 1, 'version': proposed, 'commit': COMMIT,
                 'claimTag': claim_ref, 'claimTagObject': claim_object,
                 'claimEpoch': claim['claimEpoch'], 'autopublish': False,
                 'releaseId': release['id'], 'archive': f'releases/tag/{claim_ref}/',
                 'dockerManifestDigest': 'sha256:' + 'd' * 64,
                 'candidateManifestSha256': None if skip_bundles else 'e' * 64}
        responses = {
            '/git/ref/tags/' + release['tag_name']: {'object': {'type': 'tag', 'sha': final_object}},
            '/git/tags/' + final_object: {'tag': release['tag_name'], 'object': obj,
                                         'message': json.dumps(final) + '\n'},
            '/git/tags/' + claim_object: {'tag': claim_ref, 'object': obj,
                                         'message': json.dumps(claim) + '\n'},
        }
        return release, responses

    def test_core_only_release_leaves_output_and_repository_untouched(self):
        release, responses = self.receipt_fixture()
        packaged = dict(RELEASE, tag_name=self.config['upstream_tag'])
        responses['/releases?per_page=100&page=1'] = [release, packaged]
        output = self.workspace / 'output'
        before = {filename: (self.root / filename).read_bytes() for filename in update.FILES}
        summary = self.workspace / 'summary'
        with patch.object(update, 'api', side_effect=responses.__getitem__), \
                patch.object(update, 'resolve_tag', return_value=self.config['upstream_commit']), \
                patch.object(update, 'download') as download, patch.object(update, 'prepare') as prepare, \
                patch.dict(update.os.environ, {'GITHUB_STEP_SUMMARY': str(summary)}):
            self.assertFalse(update.run(output, self.root))
        self.assertIn('Skipping v0.21.6', summary.read_text())
        self.assertIn('No new stable Desktop release', summary.read_text())
        self.assertFalse(output.exists())
        self.assertEqual(before, {filename: (self.root / filename).read_bytes() for filename in update.FILES})
        download.assert_not_called()
        prepare.assert_not_called()

    def test_selection_continues_past_core_only_and_nonstable_releases(self):
        skipped, responses = self.receipt_fixture('0.23.0')
        bundled, bundle_responses = self.receipt_fixture(
            '0.22.0', skip_bundles=False, final_object='f' * 40, claim_object='1' * 40)
        responses.update(bundle_responses)
        responses['/releases?per_page=100&page=1'] = [dict(RELEASE, prerelease=True)] * 99 + [skipped]
        responses['/releases?per_page=100&page=2'] = [dict(RELEASE, draft=True), bundled]
        with patch.object(update, 'api', side_effect=responses.__getitem__):
            self.assertEqual(update.select_release(self.config), (bundled, COMMIT, '0.22.0'))

    def test_signed_receipts_are_read_without_the_signature_armor(self):
        release, responses = self.receipt_fixture(skip_bundles=False)
        for path, response in responses.items():
            if path.startswith('/git/tags/'):
                response['message'] += '\n-----BEGIN PGP SIGNATURE-----\nfixture\n-----END PGP SIGNATURE-----\n'
        with patch.object(update, 'api', side_effect=responses.__getitem__):
            self.assertEqual(update.release_identity(release), (COMMIT, '0.21.6', True))

    def test_invalid_receipts_and_claims_fail_instead_of_skipping(self):
        cases = [('final', 'version', '0.99.0'), ('final', 'commit', 'f' * 40),
                 ('final', 'releaseId', 123), ('final', 'claimTag', 'rc.4-v0.99.0'),
                 ('final', 'claimTagObject', None), ('final', 'schema', 2),
                 ('final', 'candidateManifestSha256', 'e' * 64),
                 ('claim', 'skipBundles', 'true'), ('claim', 'skipBundles', False),
                 ('claim', 'version', '0.99.0'), ('claim', 'attempt', 5),
                 ('claim', 'commit', 'f' * 40), ('claim', 'claimEpoch', 123)]
        for kind, field, value in cases:
            with self.subTest(kind=kind, field=field):
                release, responses = self.receipt_fixture()
                response = responses['/git/tags/' + ('b' if kind == 'final' else 'c') * 40]
                record = json.loads(response['message'])
                record[field] = value
                response['message'] = json.dumps(record)
                with patch.object(update, 'api', side_effect=responses.__getitem__), self.assertRaises(ValueError):
                    update.release_identity(release)

    def test_semver_requires_receipt_and_unknown_tags_are_rejected(self):
        for tag in ('v0.22.0', 'v0.22.0rc1', 'rc.1-v0.22.0', 'v0.22.0+canary.20261001T000000Z'):
            with self.subTest(tag=tag), \
                    patch.object(update, 'api', return_value={'object': {'type': 'commit', 'sha': COMMIT}}), \
                    self.assertRaises(ValueError):
                update.release_identity(dict(RELEASE, tag_name=tag))

    def assert_preparation(self, source_version='0.22.0', receipt_version=None):
        archive = self.archive(proposed=source_version)
        urls = []

        def download(url, target):
            urls.append(url)
            target.write_bytes(archive.read_bytes() if '/tarball/' in url else url.encode())

        real_run = subprocess.run

        def run_generator(command, **kwargs):
            if command[0] == 'python3' and command[1].endswith('/scripts/generate-manifest.py'):
                return real_run(command, **kwargs)

        with patch.object(update, 'download', side_effect=download), \
                patch.object(update.subprocess, 'run', side_effect=run_generator) as run:
            metadata = update.prepare(self.root, RELEASE, COMMIT, self.workspace, receipt_version)
        config = json.loads((self.root / 'packaging/config.json').read_text())
        self.assertEqual(config['upstream_commit'], COMMIT)
        self.assertEqual(config['upstream_tag'], RELEASE['tag_name'])
        self.assertEqual(config['upstream_sha256'], update.sha256(archive))
        self.assertEqual(config['version'], '0.22.0')
        self.assertEqual(config['electron_version'], '41.0.0')
        self.assertEqual(config['electron_sha256'], hashlib.sha256(urls[1].encode()).hexdigest())
        self.assertEqual(config['electron_headers_sha256'], hashlib.sha256(urls[2].encode()).hexdigest())
        self.assertEqual(config['node_version'], self.config['node_version'])
        manifest = json.loads((self.root / 'io.github.jbsanf.HermesDesktop.json').read_text())
        self.assertEqual(manifest['build-options']['env']['ELECTRON_VERSION'], '41.0.0')
        self.assertEqual(manifest['build-options']['env']['FLATPAK_PACKAGE_VERSION'], '0.22.0')
        sources = next(module['sources'] for module in manifest['modules'] if module['name'] == 'hermes-desktop')
        self.assertEqual(sources[0]['sha256'], config['upstream_sha256'])
        self.assertTrue(sources[0]['url'].endswith('/' + COMMIT))
        self.assertEqual(metadata['previous_version'], '0.21.5')
        releases = ET.parse(self.root / update.FILES[-2]).getroot().find('releases')
        self.assertEqual(releases[0].attrib, {'version': '0.22.0', 'date': '2026-10-01'})
        self.assertEqual(releases[1].attrib['version'], '0.21.5')
        commands = [call.args[0] for call in run.call_args_list]
        self.assertEqual(commands[0][:3], ['git', 'apply', '--check'])
        self.assertTrue(commands[-1][1].endswith('/scripts/check.py'))
        self.assertIn(RELEASE['html_url'], (self.root / 'docs/RELEASE-NOTES.md').read_text())

    def test_prepare_pins_archive_electron_metadata_and_checks(self):
        self.assert_preparation()

    def test_receipt_version_replaces_source_placeholder_throughout_bundle(self):
        self.assert_preparation(source_version='0.0.0', receipt_version='0.22.0')

    def test_bundled_receipt_prepares_output_without_editing_repository(self):
        release, responses = self.receipt_fixture('0.22.0', skip_bundles=False)
        responses['/releases?per_page=100&page=1'] = [release]
        archive = self.archive(proposed='0.0.0')
        output = self.workspace / 'output'
        before = {filename: (self.root / filename).read_bytes() for filename in update.FILES}
        with patch.object(update, 'api', side_effect=responses.__getitem__), \
                patch.object(update, 'download', side_effect=lambda url, target: shutil.copyfile(archive, target)), \
                patch.object(update.subprocess, 'run'):
            self.assertTrue(update.run(output, self.root))
        self.assertEqual(json.loads((output / 'update.json').read_text())['version'], '0.22.0')
        config = json.loads((output / 'packaging/config.json').read_text())
        self.assertEqual((config['version'], config['upstream_tag'], config['upstream_commit']),
                         ('0.22.0', 'v0.22.0', COMMIT))
        self.assertTrue(all((output / filename).is_file() for filename in update.FILES))
        self.assertEqual(before, {filename: (self.root / filename).read_bytes() for filename in update.FILES})

    def test_receipt_version_still_rejects_downgrades_and_source_mismatches(self):
        for source, receipt in (('0.0.0', '0.21.5'), ('0.0.0', '0.20.9'),
                                ('0.23.0', '0.22.0'), ('0.0.0', None)):
            with self.subTest(source=source, receipt=receipt):
                workspace = self.workspace / f'case-{source}-{receipt}'
                workspace.mkdir()
                archive = self.archive(proposed=source)
                with patch.object(update, 'download', side_effect=lambda url, target: shutil.copyfile(archive, target)), \
                        patch.object(update.subprocess, 'run') as run, self.assertRaises(ValueError):
                    update.prepare(self.root, RELEASE, COMMIT, workspace, receipt)
                run.assert_not_called()
                self.assertEqual(json.loads((self.root / 'packaging/config.json').read_text()), self.config)

    def test_failure_leaves_repository_and_output_untouched(self):
        archive = self.archive()
        before = {filename: (self.root / filename).read_bytes() for filename in update.FILES}
        output = self.workspace / 'output'

        def download(url, target):
            target.write_bytes(archive.read_bytes() if '/tarball/' in url else b'electron')

        # Fail patch check, dependency generation, or the final static checks.
        for fail_at in (0, 1, 3):
            calls = [None] * fail_at + [subprocess.CalledProcessError(1, 'validation')]
            with self.subTest(fail_at=fail_at), patch.object(update, 'api', return_value=[RELEASE]), \
                    patch.object(update, 'resolve_tag', return_value=COMMIT), \
                    patch.object(update, 'download', side_effect=download), \
                    patch.object(update.subprocess, 'run', side_effect=calls), \
                    self.assertRaises(subprocess.CalledProcessError):
                update.run(output, self.root)
            self.assertFalse(output.exists())
            self.assertEqual(before, {filename: (self.root / filename).read_bytes() for filename in update.FILES})

    def test_download_errors_are_bounded(self):
        error = HTTPError('https://example.test', 429, 'rate limited', {}, io.BytesIO())
        self.addCleanup(error.close)
        with patch.object(update, 'urlopen', side_effect=error) as request, \
                patch.object(update.time, 'sleep'), self.assertRaises(HTTPError):
            update.download('https://example.test')
        self.assertEqual(request.call_count, 3)

    def test_cross_host_redirect_drops_github_token(self):
        request = update.Request('https://api.github.com/archive', headers={'Authorization': 'Bearer test'})
        redirected = update.SafeRedirect().redirect_request(
            request, None, 302, 'Found', {}, 'https://codeload.github.com/archive')
        self.assertFalse(redirected.has_header('Authorization'))

    def test_electron_workspace_resolution(self):
        lock = self.root / 'package-lock.json'
        lock.write_text(json.dumps({'packages': {'node_modules/electron': {'version': '40.0.0'},
                                                'apps/desktop/node_modules/electron': {'version': '41.0.0'}}}))
        self.assertEqual(update.electron_version(self.root), '41.0.0')
        lock.write_text(json.dumps({'packages': {'node_modules/electron': {'version': '40.0.0'}}}))
        self.assertEqual(update.electron_version(self.root), '40.0.0')
        lock.write_text('{"packages": {}}')
        with self.assertRaises(ValueError):
            update.electron_version(self.root)


class FakeGitHub:
    def __init__(self):
        self.base = 'base'
        self.head = None
        self.commits = {'base': {'tree': {'sha': 'base-tree'}}}
        self.pulls = []
        self.runs = set()
        self.dispatches = 0
        self.manual = False
        self.fail_dispatch = False
        self.concurrent_commit = False
        self.fail_pr_update = False

    def get(self, path):
        return self.call('GET', path)

    def call(self, method, path, data=None):
        if path == '/git/ref/heads/main':
            return {'object': {'sha': self.base}}
        if path.startswith('/git/matching-refs/'):
            return [{'ref': 'refs/heads/' + publisher.BRANCH, 'object': {'sha': self.head}}] if self.head else []
        if path.startswith('/compare/'):
            commit = {'author': {'login': 'human' if self.manual else publisher.BOT},
                      'committer': {'login': publisher.BOT}, 'commit': {'message': publisher.PREFIX + '0.22.0'}}
            return {'commits': [commit], 'total_commits': 1}
        if path.startswith('/git/commits/'):
            return self.commits[path.rsplit('/', 1)[-1]]
        if path == '/git/trees':
            return {'sha': hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()}
        if path == '/git/commits':
            sha = 'commit-' + str(len(self.commits))
            self.commits[sha] = {'tree': {'sha': data['tree']}, 'parents': data['parents']}
            return {'sha': sha}
        if path == '/git/refs' or path.startswith('/git/refs/heads/'):
            if method == 'PATCH':
                assert data['force'] is False
                if self.concurrent_commit:
                    raise RuntimeError('Concurrent branch update: not a fast-forward')
            self.head = data['sha']
            for pr in self.pulls:
                if pr['state'] == 'open':
                    pr['head']['sha'] = self.head
            return None
        if path.startswith('/pulls?'):
            return copy.deepcopy(self.pulls)
        if path == '/pulls':
            pr = dict(data, number=len(self.pulls) + 1, html_url='https://example.test/pr/1',
                      state='open', merged_at=None)
            pr['head'] = {'sha': self.head}
            self.pulls.append(pr)
            return copy.deepcopy(pr)
        if path.startswith('/pulls/'):
            if self.fail_pr_update:
                raise RuntimeError('PR update temporarily unavailable')
            self.pulls[0].update(data)
            return None
        if '/runs?' in path:
            return {'total_count': int(self.head in self.runs)}
        if path.endswith('/dispatches'):
            if self.fail_dispatch:
                raise RuntimeError('Dispatch temporarily unavailable')
            self.runs.add(self.head)
            self.dispatches += 1
            return None
        raise AssertionError((method, path, data))


class Publication(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.bundle = Path(self.temp.name)
        self.github = FakeGitHub()
        for filename in publisher.FILES:
            target = self.bundle / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text('{}')
        self.update_bundle('0.22.0')

    def update_bundle(self, version):
        metadata = dict(RELEASE, version=version, previous_version='0.21.5', upstream_tag=RELEASE['tag_name'],
                        upstream_url=RELEASE['html_url'], upstream_commit=COMMIT,
                        electron_version='41.0.0', previous_electron_version='40.10.2')
        (self.bundle / 'update.json').write_text(json.dumps(metadata))
        (self.bundle / 'packaging/config.json').write_text(json.dumps({'version': version, 'upstream_commit': COMMIT}))

    def publish(self):
        publisher.publish(self.github, self.bundle, 'base', 'owner/repo')

    def test_create_repeat_and_update_one_pr(self):
        self.publish()
        first = self.github.head
        self.publish()
        self.assertEqual(self.github.head, first)
        self.assertEqual(self.github.dispatches, 1)
        self.update_bundle('0.23.0')
        self.publish()
        self.assertNotEqual(self.github.head, first)
        self.assertEqual(len(self.github.pulls), 1)
        self.assertEqual(self.github.dispatches, 2)
        self.assertEqual(self.github.commits[self.github.head]['parents'], [first, 'base'])
        self.assertIn('0.23.0', self.github.pulls[0]['title'])

    def test_dispatch_retry_does_not_create_another_commit_or_pr(self):
        self.github.fail_dispatch = True
        with self.assertRaises(RuntimeError):
            self.publish()
        first = self.github.head
        self.github.fail_dispatch = False
        self.publish()
        self.assertEqual(self.github.head, first)
        self.assertEqual(len(self.github.pulls), 1)
        self.assertEqual(self.github.dispatches, 1)

    def test_pr_update_recovers_after_branch_was_already_pushed(self):
        self.publish()
        self.update_bundle('0.23.0')
        self.github.fail_pr_update = True
        with self.assertRaises(RuntimeError):
            self.publish()
        head = self.github.head
        self.github.fail_pr_update = False
        self.publish()
        self.assertEqual(self.github.head, head)
        self.assertIn('0.23.0', self.github.pulls[0]['title'])
        self.assertEqual(self.github.dispatches, 2)

    def test_manual_commits_are_preserved(self):
        self.publish()
        first = self.github.head
        self.github.manual = True
        self.update_bundle('0.23.0')
        with self.assertRaisesRegex(RuntimeError, 'manual commits'):
            self.publish()
        self.assertEqual(self.github.head, first)

    def test_concurrent_manual_commit_is_not_overwritten(self):
        self.publish()
        first = self.github.head
        self.github.concurrent_commit = True
        self.update_bundle('0.23.0')
        with self.assertRaisesRegex(RuntimeError, 'fast-forward'):
            self.publish()
        self.assertEqual(self.github.head, first)

    def test_moved_main_requires_new_preparation(self):
        self.github.base = 'new-base'
        with self.assertRaisesRegex(RuntimeError, 'main changed'):
            self.publish()
        self.assertIsNone(self.github.head)

    def test_manually_closed_pr_stays_closed(self):
        self.publish()
        self.github.pulls[0]['state'] = 'closed'
        self.publish()
        self.assertEqual(len(self.github.pulls), 1)
        self.assertEqual(self.github.pulls[0]['state'], 'closed')


if __name__ == '__main__':
    unittest.main()
