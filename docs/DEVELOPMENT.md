# Development, builds, tests, and publication

Linux x86_64 packaging of the official Nous Research Desktop, with a private
Python backend. It does not install the Hermes CLI, TUI, or web dashboard. The
upstream code retains its MIT license; this project is not an official Nous
Research distribution.

- App ID: `io.github.jbsanf.HermesDesktop`
- Remote: `https://jbsanf.github.io/hermes-agent-desktop/repo/`
- Channel: `stable`
- Upstream release: Hermes Agent `0.21.5` (tag `v2026.9.24`), pinned by commit and SHA-256.

Run all commands below from the repository root.

## Build and install locally

On Linux x86_64, install `flatpak`, `flatpak-builder`, `ostree`, `gnupg`, `zstd`,
`appstream`, `desktop-file-utils`, Python 3.11+, `python3-packaging`, `python3-gi`,
and `gir1.2-flatpak-1.0` using your distribution's package manager. Scripts use
the `--user` installation scope.

Run the complete workflow with a single command. Any error stops subsequent
steps and preserves the failed step's error message:

```bash
./scripts/build-local.sh
```

If the build has already completed and only the bundle is missing, you do not
need to rebuild:

```bash
./scripts/build-local.sh --skip-build
```

The build step (`build.sh`) prepares `build-dir/`; it **does not generate the
`.flatpak` file**. The export step (`publish-repo.py`) signs the repository and
generates the bundle. Compression can take several minutes; wait for the
`Prepared HermesDesktop-…` message before installing. If `repository.gpg` is the
only file in `dist/release/`, the export is still incomplete. The script reports
the current operation every 30 seconds.

To run the steps individually, use a Bash shell that stops on errors:

```bash
bash -e <<'SH'
scripts/setup.sh
python3 scripts/check.py
scripts/build.sh
KEY=$(scripts/local-key.sh)
export GNUPGHOME="$PWD/.local-keys"
python3 -u scripts/publish-repo.py --key "$KEY"
scripts/install-local.sh
SH
```

After installation, run `python3 scripts/smoke.py` and
`flatpak run io.github.jbsanf.HermesDesktop`.

`install-local.sh` selects the bundle matching the version and architecture in
`packaging/config.json`, even when `dist/release/` contains other versions.
It also accepts an explicit file: `scripts/install-local.sh /path/to/package.flatpak`.
Running it again reinstalls the package while preserving private application data.
The file must exist on the machine where installation runs; `dist/` is not tracked
in Git.

The build downloads verified sources and compiles without network access. It does
not require Python, Node.js, or Hermes to be installed on the end user's host.
The SDK and BaseApp are build dependencies; the application uses the Freedesktop
runtime.

The local bundle already contains the final Pages URL, even before the first
publication. Installation works with the required runtimes available, but updates
through that URL depend on Pages being deployed and on the signing key identity.

Complete [local validation](LOCAL-TESTS.md) before publishing.

## Export fails before generating the bundle

`Bundle not found` means the export did not complete. Check the error from
`publish-repo.py` first. The `build-local.sh` workflow stops at that error.
If `ostree fsck` reports missing objects in the **local development repository**,
preserve the directory for diagnosis and repeat only the export:

```bash
mv repo "repo-backup-$(date +%Y%m%d-%H%M%S)"
./scripts/build-local.sh --skip-build
```

Do not use this procedure to discard production repository history. Restore the
valid snapshot from the last publication instead.

## Update rehearsal

After generating and installing the local bundle, run:

```bash
export GNUPGHOME="$PWD/.local-keys"
python3 scripts/rehearse-update.py --key "$KEY" --replace-local-test-install
```

The rehearsal temporarily replaces the test installation with a bundle pointing
to a loopback HTTP remote, exports a second signed revision, and runs
`flatpak update`. It checks that the commit changes, the origin stays the same,
and data is preserved, recording the results in `dist/update-rehearsal.json`.
It then reinstalls the original bundle with the Pages URL without deleting data.
Use this only for the local development installation.

## Automated tests

```bash
python3 -m unittest discover -s tests -v
dbus-run-session -- python3 scripts/ssh-agent-smoke.py
dbus-run-session -- python3 scripts/smoke.py
xvfb-run -a dbus-run-session -- node scripts/gui-smoke.mjs
```

The SSH agent test requires `ssh-agent`, `ssh-add`, and `ssh-keygen` on the host
(the `openssh-client` package). The GUI test requires Node.js 22+, Xvfb, and D-Bus.
It opens the installed Electron application, sends a chat message to a mock HTTP
provider, and checks streaming, internal update restrictions, and shutdown.
It preserves logs and a screenshot in a test directory within the application's
private data. It does not use real credentials. Testing folder selection through
portals requires a desktop session with working FUSE and manual validation.
Results from this run: [validation results](VALIDATION.md).

## GitHub Actions → Release → Pages

The package version follows the version declared by Hermes Agent in its
`pyproject.toml`. Store it as three numeric components (`0.21.5`) in
`packaging/config.json`, without a `v` prefix, suffixes, or leading zeros.
Keep AppStream metadata in sync and regenerate the manifest with
`python3 scripts/generate-manifest.py`. Tags and release titles use `v0.21.5`;
the bundle is named `HermesDesktop-0.21.5-x86_64.flatpak`.

Upstream Git tags use a separate convention: Hermes Agent `0.21.5` is released
under `v2026.9.24`. Keep that actual tag in `upstream_tag`, together with its
commit and archive hash. Existing tags and historical validation reports retain
their original version numbers.

The workflows build with the same local scripts. Pull requests do not receive
signing keys. Publication uses `v<VERSION>` tags, such as `v0.21.5`, matching
the configured version exactly, after:

1. Recording local validation approval and setting the repository variable
   `LOCAL_VALIDATION_APPROVED=true`.
2. Enabling Pages with **GitHub Actions** as the source.
3. In **Settings → Environments → github-pages → Deployment branches and tags**,
   choosing **Selected branches and tags** and adding a **Tag** rule for `v*`.
   Preserve any existing branch rules that are still needed. The release workflow
   deploys from a tag, so a branch-only rule does not authorize its deployment.
4. Creating a permanent GPG signing key and keeping a private backup.
5. Configuring the secrets `FLATPAK_GPG_PRIVATE_KEY` (ASCII-armored export),
   `FLATPAK_GPG_PASSPHRASE`, and `FLATPAK_GPG_FINGERPRINT` (full fingerprint).

The build restores the snapshot referenced by the last successful Pages
deployment, verifies its integrity and signature, exports the new commit, and
generates the bundle with `--repo-url`. The Release receives the bundle,
descriptors, public key, checksums, provenance, and OSTree snapshot. The next job
deploys that same repository to Pages.

The current commit and one ancestor per ref are retained. The local size limit
for the entire site is 900 MiB. Exceeding it fails publication before any uploads.
Do not use the Actions cache as the authoritative copy of the OSTree repository.

If deployment fails after the Release is published, rerun only the failed jobs.
The existing Pages artifact is reused without rebuilding, and the previous
deployment remains available in the meantime. Do not replace existing Release
assets with a different build under the same tag.

If the `pages` job reports `Tag "v0.21.5" is not allowed to deploy to
github-pages due to environment protection rules`, configure the tag rule above,
then use **Actions → failed workflow run → Re-run jobs → Re-run failed jobs**.
This environment setting is managed in GitHub, not in the workflow YAML. Any
other protection requirements, such as required reviewers, must also be satisfied.

## Update dependencies

Review the commit, hashes, and versions in `packaging/config.json`. From the
matching upstream checkout, with `uv` and `python3-packaging` available:

```bash
python3 scripts/generate-sources.py /path/to/upstream
python3 scripts/generate-manifest.py
python3 scripts/check.py
```

`generate-sources.py` uses the npm/uv lockfiles, includes the MCP extra, and selects
Linux CPython 3.13 wheels. A missing compatible wheel is an error, not an
unrestricted download during the build. Review and commit the generated sources
and requirements. Revalidate the patches and the native `node-pty` module whenever
you change Electron or the upstream version.

This repository distributes Flatpak packages through GitHub Pages. It is not yet
part of the Flathub catalog; submitting it to the catalog is a future step.
