#!/usr/bin/env python3
"""Publish a validated update bundle with GITHUB_TOKEN and dispatch its CI."""
import argparse
import json
import os
from pathlib import Path
import runpy
import subprocess
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
FILES = runpy.run_path(str(ROOT / 'scripts/update-upstream.py'))['FILES']
BRANCH = 'automation/update-hermes-agent'
PREFIX = 'chore: update Hermes Agent to '
BOT = 'github-actions[bot]'


class GitHub:
    def __init__(self, repository):
        self.prefix = f'repos/{repository}'

    def call(self, method, path, data=None):
        command = ['gh', 'api', '--method', method, self.prefix + path]
        if data is not None:
            command += ['--input', '-']
        try:
            result = subprocess.run(command, input=json.dumps(data) if data is not None else None,
                                    text=True, capture_output=True, check=True)
        except subprocess.CalledProcessError as error:
            raise RuntimeError(f'GitHub {method} {path}: {error.stderr.strip()}') from error
        return json.loads(result.stdout) if result.stdout.strip() else None

    def get(self, path):
        return self.call('GET', path)


def guard_branch(github, base, head):
    page = 1
    seen = 0
    while True:
        comparison = github.get(f'/compare/{base}...{head}?per_page=100&page={page}')
        commits = comparison['commits']
        for commit in commits:
            if (commit.get('author') or {}).get('login') != BOT or \
                    (commit.get('committer') or {}).get('login') != BOT or \
                    not commit['commit']['message'].startswith(PREFIX):
                raise RuntimeError('Automation branch contains manual commits; refusing to overwrite them')
        seen += len(commits)
        if seen >= comparison['total_commits']:
            return
        if not commits:
            raise RuntimeError('Could not inspect all automation branch commits')
        page += 1


def ensure_ci(github, sha):
    query = urlencode({'event': 'workflow_dispatch', 'head_sha': sha, 'branch': BRANCH, 'per_page': 1})
    runs = github.get('/actions/workflows/ci.yml/runs?' + query)
    if runs['total_count']:
        print(f'CI already exists for {sha}')
        return
    github.call('POST', '/actions/workflows/ci.yml/dispatches', {'ref': BRANCH})
    print(f'Dispatched CI for {sha}')


def publish(github, bundle, base, repository):
    metadata = json.loads((bundle / 'update.json').read_text())
    config = json.loads((bundle / 'packaging/config.json').read_text())
    if config['version'] != metadata['version'] or config['upstream_commit'] != metadata['upstream_commit']:
        raise ValueError('Update metadata does not match the prepared configuration')
    main = github.get('/git/ref/heads/main')['object']['sha']
    if main != base:
        raise RuntimeError('main changed during preparation; rerun the update workflow')
    refs = github.get('/git/matching-refs/heads/' + BRANCH)
    existing = next((ref['object']['sha'] for ref in refs if ref['ref'] == 'refs/heads/' + BRANCH), None)
    if existing:
        guard_branch(github, base, existing)
    base_tree = github.get('/git/commits/' + base)['tree']['sha']
    tree = github.call('POST', '/git/trees', {
        'base_tree': base_tree,
        'tree': [{'path': filename, 'mode': '100644', 'type': 'blob',
                  'content': (bundle / filename).read_text()} for filename in FILES],
    })['sha']
    existing_tree = github.get('/git/commits/' + existing)['tree']['sha'] if existing else None
    changed = tree != existing_tree
    sha = existing
    if changed:
        parents = list(dict.fromkeys([existing, base] if existing else [base]))
        sha = github.call('POST', '/git/commits', {
            'message': PREFIX + metadata['version'], 'tree': tree, 'parents': parents,
        })['sha']
        if existing:
            # Fast-forward only: a concurrent manual commit causes rejection.
            github.call('PATCH', '/git/refs/heads/' + BRANCH, {'sha': sha, 'force': False})
        else:
            github.call('POST', '/git/refs', {'ref': 'refs/heads/' + BRANCH, 'sha': sha})
    owner = repository.split('/')[0]
    query = urlencode({'head': owner + ':' + BRANCH, 'base': 'main', 'state': 'all', 'per_page': 100})
    pulls = github.get('/pulls?' + query)
    current = next((pr for pr in pulls if pr['state'] == 'open'), None)
    if current is None and any(pr['state'] == 'closed' and not pr.get('merged_at') and
                               pr['head']['sha'] == sha for pr in pulls):
        print('This update PR was closed manually; leaving it closed. Reopen it to resume review.')
        return
    body = (
        f'Updates Hermes Agent **{metadata["previous_version"]} → {metadata["version"]}**.\n\n'
        f'Upstream release: [{metadata["upstream_tag"]}]({metadata["upstream_url"]})\n\n'
        f'Pinned commit: `{metadata["upstream_commit"]}`.\n\n'
        f'Electron: `{metadata["previous_electron_version"]}` → `{metadata["electron_version"]}`. '
        'Node.js and the Flatpak runtime remain pinned.\n\n'
        'Sources, archive hashes, AppStream and the manifest were regenerated; '
        'patch applicability and static packaging checks passed. Full package validation runs in CI.\n\n'
        '- [ ] Review the generated changes and successful CI run.\n'
        '- [ ] Complete and record local validation (`docs/LOCAL-TESTS.md`).\n'
        '- [ ] Merge the reviewed PR.\n'
        f'- [ ] Publish tag `v{metadata["version"]}` on the validated merged commit.\n\n'
        'This branch is managed by automation. Make packaging fixes on `main`, then rerun the updater.\n'
    )
    title = 'Update Hermes Agent to ' + metadata['version']
    if current is None:
        current = github.call('POST', '/pulls', {'title': title, 'body': body, 'head': BRANCH, 'base': 'main'})
    elif changed or current['title'] != title:
        github.call('PATCH', f'/pulls/{current["number"]}', {'title': title, 'body': body})
    print(current['html_url'])
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
            stream.write(f'Update PR: {current["html_url"]}\n\nCI commit: [{sha}](https://github.com/{repository}/commit/{sha})\n')
    ensure_ci(github, sha)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--base', required=True)
    parser.add_argument('--repository', required=True)
    args = parser.parse_args()
    publish(GitHub(args.repository), args.bundle, args.base, args.repository)


if __name__ == '__main__':
    main()
