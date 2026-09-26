# Hermes Desktop — Community Flatpak

Linux x86_64 packaging of the official Nous Research Desktop, with a private
Python backend. It does not install the Hermes CLI, TUI, or web dashboard. The
upstream code retains its MIT license; this project is not an official Nous
Research distribution.

- App ID: `io.github.jbsanf.HermesDesktop`
- Remote: `https://jbsanf.github.io/hermes-agent-desktop/repo/`
- Channel: `stable`
- Initial upstream release: `v2026.9.24`, pinned by commit and SHA-256.

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

Complete [local validation](docs/LOCAL-TESTS.md) before publishing.

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

## Permissions and data

The application has network, Wayland/fallback X11, audio, GPU, specific Secret
Service access, and access to the **ssh-agent** socket (`--socket=ssh-auth`).
It does not have broad access to the home directory or host files. External
folders are selected through portals. Local processes remain in the sandbox,
without access to the `org.freedesktop.Flatpak` API for launching host processes
or unrestricted D-Bus access.

### Remote gateway over SSH

Load your key into the session's agent before opening the application:

```bash
ssh-add ~/.ssh/id_ed25519
```

If no agent is running, start one and launch the application from the same session:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
flatpak run io.github.jbsanf.HermesDesktop
```

In the SSH connection settings, enter the host, user, and port; leave the key path
empty to use the agent. The private key stays on the host, including when it is
protected by a passphrase. The application can request authentication using
identities loaded into the agent without gaining access to private files in
`~/.ssh`. `SSH_AUTH_SOCK` must point to a running agent in the environment that
launches Flatpak.

Alternatively, store a private key in
`~/.var/app/io.github.jbsanf.HermesDesktop/config/ssh/` and specify its absolute
path. The host's `~/.ssh/config` is not exposed automatically. The `.ssh` directory
seen by the application is private and persistent, stored on the host at
`~/.var/app/io.github.jbsanf.HermesDesktop/.ssh/`. It holds `known_hosts` entries
and, optionally, an application-specific SSH `config` file.

Agent data: `~/.var/app/io.github.jbsanf.HermesDesktop/data/hermes`.
Electron configuration: `~/.var/app/io.github.jbsanf.HermesDesktop/config/hermes-desktop`.
The backend uses loopback, a dynamic port, and Desktop authentication.

Update through your software center or `flatpak update --user io.github.jbsanf.HermesDesktop`.
Uninstall with `flatpak uninstall --user io.github.jbsanf.HermesDesktop`; add
`--delete-data` only if you also want to remove private application data.

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
Results from this run: [docs/VALIDATION.md](docs/VALIDATION.md).

## GitHub Actions → Release → Pages

The workflows build with the same local scripts. Pull requests do not receive
signing keys. Publication uses `v<VERSION>` tags, such as `v2026.9.24-1`, after:

1. Recording local validation approval and setting the repository variable
   `LOCAL_VALIDATION_APPROVED=true`.
2. Enabling Pages with **GitHub Actions** as the source.
3. Creating a permanent GPG signing key and keeping a private backup.
4. Configuring the secrets `FLATPAK_GPG_PRIVATE_KEY` (ASCII-armored export),
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
