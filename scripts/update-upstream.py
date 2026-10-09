#!/usr/bin/env python3
"""Prepare a reviewed upstream update; never write to GitHub.

All generation and checks run in a temporary copy. --output receives a bundle
of validated files for the publishing job; the working tree is never edited.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import tomllib
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = 'https://api.github.com/repos/NousResearch/hermes-agent'
FILES = (
    'packaging/config.json', 'packaging/python-sources.json',
    'packaging/npm-sources.json', 'packaging/requirements.txt',
    'io.github.jbsanf.HermesDesktop.json',
    'packaging/io.github.jbsanf.HermesDesktop.metainfo.xml', 'docs/RELEASE-NOTES.md',
)


class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, url):
        redirected = super().redirect_request(request, fp, code, message, headers, url)
        if redirected is not None and urlsplit(request.full_url).netloc != urlsplit(url).netloc:
            redirected.remove_header('Authorization')
        return redirected


urlopen = build_opener(SafeRedirect()).open


def download(url, destination=None):
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'hermes-flatpak-updater'}
    # Never forward the GitHub token to asset hosts.
    if url.startswith('https://api.github.com/') and os.environ.get('GH_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GH_TOKEN']
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=headers), timeout=60) as response:
                if destination is None:
                    return response.read()
                with destination.open('wb') as output:
                    shutil.copyfileobj(response, output)
                return
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
            time.sleep(2 ** (attempt + 1))


def api(path):
    return json.loads(download(UPSTREAM + path))


def version(value):
    if not re.fullmatch(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)', value):
        raise ValueError(f'Unsupported package version: {value!r}')
    return tuple(map(int, value.split('.')))


def resolve_tag(tag):
    obj = api('/git/ref/tags/' + quote(tag, safe=''))['object']
    for _ in range(10):
        if obj['type'] == 'commit':
            if not re.fullmatch(r'[0-9a-f]{40}', obj['sha']):
                raise ValueError('Invalid upstream commit')
            return obj['sha']
        if obj['type'] != 'tag':
            break
        obj = api('/git/tags/' + obj['sha'])['object']
    raise ValueError('Release tag does not resolve to a commit')


def check_version(current, proposed):
    if version(proposed) <= version(current):
        raise ValueError(f'Upstream revision requires a new package version: {current} -> {proposed}')


def tag_record(tag):
    # Signed annotated tags include an armored signature after the JSON record.
    try:
        record = json.loads(tag['message'].split('\n-----BEGIN ', 1)[0])
    except (KeyError, TypeError, AttributeError, json.JSONDecodeError) as error:
        raise ValueError('Invalid upstream release tag metadata') from error
    if not isinstance(record, dict):
        raise ValueError('Invalid upstream release tag metadata')
    return record


def release_identity(release):
    """Return (commit, receipt version, includes Desktop) for a stable release."""
    tag = release['tag_name']
    if re.fullmatch(r'v[0-9]{1,3}\.[0-9]+\.[0-9]+', tag) is None:
        # Historical CalVer releases carry the package version in pyproject.toml.
        if re.fullmatch(r'v[0-9]{4}\.[0-9]{1,2}\.[0-9]{1,2}', tag) is None:
            raise ValueError(f'Unsupported stable upstream tag: {tag!r}')
        return resolve_tag(tag), None, True
    proposed = tag[1:]
    version(proposed)
    obj = api('/git/ref/tags/' + quote(tag, safe=''))['object']
    if obj['type'] != 'tag' or not re.fullmatch(r'[a-f0-9]{40}', obj['sha']):
        raise ValueError('Stable upstream release requires an annotated receipt tag')
    receipt_tag = api('/git/tags/' + obj['sha'])
    commit = receipt_tag['object']['sha']
    receipt = tag_record(receipt_tag)
    claim_ref = receipt.get('claimTag', '')
    claim_object = receipt.get('claimTagObject', '')
    if (receipt_tag['tag'] != tag or receipt_tag['object']['type'] != 'commit'
            or not re.fullmatch(r'[a-f0-9]{40}', commit)
            or receipt.get('schema') != 1 or receipt.get('version') != proposed
            or receipt.get('commit') != commit or receipt.get('releaseId') != release['id']
            or not isinstance(claim_ref, str)
            or re.fullmatch(r'rc\.[1-9][0-9]*-' + re.escape(tag), claim_ref) is None
            or not isinstance(claim_object, str)
            or re.fullmatch(r'[a-f0-9]{40}', claim_object) is None):
        raise ValueError('Upstream release receipt differs from its tag or release')
    # Read the immutable claim object bound by the final receipt, not a mutable ref.
    claim_tag = api('/git/tags/' + claim_object)
    claim = tag_record(claim_tag)
    if (claim_tag['tag'] != claim_ref or claim_tag['object'] != receipt_tag['object']
            or claim.get('schema') != 1 or claim.get('version') != proposed
            or claim.get('commit') != commit
            or claim.get('attempt') != int(claim_ref.split('-')[0][3:])
            or type(claim.get('skipBundles')) is not bool
            or claim.get('claimEpoch') != receipt.get('claimEpoch')
            or claim.get('autopublish') != receipt.get('autopublish')):
        raise ValueError('Upstream release claim differs from its receipt')
    manifest = receipt.get('candidateManifestSha256')
    manifest_ok = (manifest is None if claim['skipBundles'] else
                   isinstance(manifest, str) and re.fullmatch(r'[a-f0-9]{64}', manifest) is not None)
    if 'candidateManifestSha256' not in receipt or not manifest_ok:
        raise ValueError('Upstream bundle manifest differs from its release policy')
    return commit, proposed, not claim['skipBundles']


def report(message):
    print(message)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(message + '\n')


def select_release(config):
    """Find the newest stable Desktop release, stopping at the packaged release."""
    page = 1
    while True:
        releases = api(f'/releases?per_page=100&page={page}')
        for release in releases:
            if release['draft'] or release['prerelease']:
                continue
            commit, proposed, desktop = release_identity(release)
            if not desktop:
                report(f'Skipping {release["tag_name"]}: upstream release excludes Desktop bundles.')
                continue
            if commit == config['upstream_commit'] and release['tag_name'] == config['upstream_tag']:
                return None
            return release, commit, proposed
        if len(releases) < 100:
            return None
        page += 1


def electron_version(source):
    packages = json.loads((source / 'package-lock.json').read_text())['packages']
    # Follow Node resolution from the Desktop workspace, including hoisted locks.
    for location in ('apps/desktop/node_modules/electron', 'apps/node_modules/electron', 'node_modules/electron'):
        if location in packages:
            result = packages[location]['version']
            version(result)
            return result
    raise ValueError('No locked Electron version for the Desktop workspace')


def sha256(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(root, release, commit, workspace, receipt_version=None):
    config = json.loads((root / 'packaging/config.json').read_text())
    archive = workspace / 'upstream.tar.gz'
    download(UPSTREAM + '/tarball/' + commit, archive)
    source_dir = workspace / 'source'
    source_dir.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(source_dir, filter='data')
    children = list(source_dir.iterdir())
    if len(children) != 1 or not children[0].is_dir():
        raise ValueError('Expected one upstream archive root')
    source = children[0]
    proposed = tomllib.loads((source / 'pyproject.toml').read_text())['project']['version']
    if receipt_version is not None:
        if proposed not in ('0.0.0', receipt_version):
            raise ValueError('Upstream source version differs from its release receipt')
        proposed = receipt_version
    check_version(config['version'], proposed)
    electron = electron_version(source)
    updated = dict(config, version=proposed, upstream_tag=release['tag_name'],
                   upstream_commit=commit, upstream_sha256=sha256(archive), electron_version=electron)
    if electron != config['electron_version']:
        urls = {
            'electron_sha256': f'https://github.com/electron/electron/releases/download/v{electron}/electron-v{electron}-linux-x64.zip',
            'electron_headers_sha256': f'https://artifacts.electronjs.org/headers/dist/v{electron}/node-v{electron}-headers.tar.gz',
        }
        for field, url in urls.items():
            artifact = workspace / field
            download(url, artifact)
            updated[field] = sha256(artifact)
    (root / 'packaging/config.json').write_text(json.dumps(updated, indent=2) + '\n')
    metadata = root / 'packaging/io.github.jbsanf.HermesDesktop.metainfo.xml'
    tree = ET.parse(metadata)
    releases = tree.getroot().find('releases')
    releases.insert(0, ET.Element('release', version=proposed, date=release['published_at'][:10]))
    tree.write(metadata, encoding='utf-8', xml_declaration=True)
    url = release['html_url']
    (root / 'docs/RELEASE-NOTES.md').write_text(
        f'## Hermes Desktop v{proposed}\n\n'
        f'Community Flatpak updated to [Hermes Agent {release["tag_name"]}]({url}).\n\n'
        f'Upstream commit: `{commit}`. Electron: `{electron}`.\n\n'
        'Install the release bundle or update an existing installation with `flatpak update`.\n'
        'See the [installation instructions](../README.md) and [usage guide](USAGE.md).\n')
    subprocess.run(['git', 'apply', '--check', str(root / 'patches/flatpak-integration.patch')], cwd=source, check=True)
    subprocess.run(['python3', str(root / 'scripts/generate-sources.py'), str(source)], cwd=root, check=True)
    subprocess.run(['python3', str(root / 'scripts/generate-manifest.py')], cwd=root, check=True)
    subprocess.run(['python3', str(root / 'scripts/check.py')], cwd=root, check=True)
    return {
        'version': proposed, 'previous_version': config['version'], 'upstream_tag': release['tag_name'],
        'upstream_commit': commit, 'upstream_url': url,
        'electron_version': electron, 'previous_electron_version': config['electron_version'],
    }


def run(output, root=ROOT):
    if output.exists():
        raise ValueError('Output must be a new directory')
    config = json.loads((root / 'packaging/config.json').read_text())
    selected = select_release(config)
    if selected is None:
        report('No new stable Desktop release; no changes or PR needed.')
        return False
    release, commit, receipt_version = selected
    with tempfile.TemporaryDirectory(prefix='hermes-update-') as directory:
        workspace = Path(directory)
        staging = workspace / 'repository'
        shutil.copytree(root, staging, ignore=shutil.ignore_patterns(
            '.git', '.cache', '.flatpak-builder', 'build-dir', 'dist', 'repo', '.local-keys', '__pycache__', 'repo-backup-*'))
        metadata = prepare(staging, release, commit, workspace, receipt_version)
        output.mkdir(parents=True)
        for filename in FILES:
            target = output / filename
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(staging / filename, target)
        (output / 'update.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(f'Prepared Hermes Desktop {metadata["version"]}')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    try:
        changed = run(args.output.resolve())
    except Exception as error:
        if os.environ.get('GITHUB_STEP_SUMMARY'):
            with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
                stream.write(f'Upstream preparation failed: {error}\n')
        raise
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
            stream.write(f'changed={str(changed).lower()}\n')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write('Update prepared for review.\n' if changed else 'No update prepared.\n')


if __name__ == '__main__':
    main()
