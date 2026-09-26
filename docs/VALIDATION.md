# Local validation — 2026-09-26

Package `2026.9.24-1`, x86_64, upstream `v2026.9.24`.
Built and installed in the user scope **of this development environment**.
The interface ran with Xvfb and D-Bus; this is not equivalent to a physical desktop session.

## Current filesystem and SSH policy

The user revoked the temporary request for broad filesystem access. The current
policy restricts external files again, adding only `--socket=ssh-auth` and
`--persist=.ssh`. There is no `--filesystem=host` permission or access to the host
execution API. The persisted `.ssh` directory is private to the application,
not the user's original `.ssh` directory.

The `scripts/ssh-agent-smoke.py` test creates a temporary key and agent, requests
a signature through the socket from inside Flatpak, and verifies that signature.
It also confirms that the private key file is inaccessible in the sandbox.
The test does not add or remove identities in the user's real agent.

## Confirmed results

- Complete build, offline after downloading verified sources.
- AppStream, desktop entry, manifest, hashes, and permissions validated.
- Installation of the approximately 174 MiB bundle.
- Origin created automatically: `hermesdesktop-origin`, with
  `https://jbsanf.github.io/hermes-agent-desktop/repo/` embedded in the bundle.
- The private Python backend starts and responds to the health endpoint.
- No public `hermes`/`hermes-agent` commands or installed TUI interface.
- A test file in the external home directory remains inaccessible.
- The real Electron application opens, connects to the backend, and receives
  `FLATPAK_STREAMING_OK` streamed by a mock OpenAI-compatible server without real credentials.
- User and assistant messages persisted in the private SQLite database, confirmed
  by a read-only query after shutdown.
- IPC blocks internal updates, bootstrap repair, and opening a session in an
  external terminal. Flatpak manages updates.
- Closing the window normally exits the application. `flatpak ps` was empty
  after the GUI and backend tests.
- The native `node-pty` module, loaded by the installed Electron binary, ran a
  shell in the sandbox and received its output correctly (ABI and PTY validated).
- Two contract tests passed, including signatures and origins of bundles
  generated from successive exports.
- Workflows passed actionlint; scripts passed syntax checks.

Screenshot: `dist/validation/desktop.png`. Text: `dist/validation/renderer.txt`.
Local logs: `.cache/build.log`, `.cache/export.log`, `.cache/smoke.log`,
`.cache/gui-smoke.log`, `.cache/unit-tests.log`, `.cache/update-rehearsal.log`.

Original OSTree commit:
`f0f08b687007311d856f344edec6dbddec9266ed193479982b3a64afa8d038d1`.

Bundle SHA-256:
`afd1257c3fbaaba76ce8e78573bb85c4329a51c66d977015e1e1f063ea59a29b`.

Signed exclusively with a development key. Do not publish this bundle as a
production distribution.

## Update rehearsal passed

A separate bundle embedded the URL of a loopback HTTP server. Installing it
created the remote automatically. A second export, signed with the same key,
was installed by `flatpak update` without changing the origin and while preserving
the test data file. The new revision was also confirmed by reading a file added
to `/app/share`.

- First commit: `f0f08b687007311d856f344edec6dbddec9266ed193479982b3a64afa8d038d1`.
- Second commit: `9066fd8ce80a1218f71f38a0a9ab10d745c03136cb1cec7917f19a3de4f07a26`.
- Evidence: `dist/update-rehearsal.json`.

The script then reinstalled the original bundle. The original commit and Pages
URL were reconfirmed with `flatpak info` and `scripts/verify-origin.py`.
The public Pages repository has not been deployed yet; this test verifies the
signed HTTP remote update mechanism, not the availability of the public site.

## Limitations and outstanding work

The document portal cannot mount in this environment: opening `/dev/fuse` returns
`Operation not permitted`. External folder selection, persistent access grants,
and reading/writing through the portal still need testing on a Linux desktop
with working FUSE. No filesystem permissions were expanded to work around this.

Tests with a real provider, native Wayland, clipboard, external links, audio, and
the integrated terminal remain outstanding. The Xvfb test forces X11 only for the
test invocation. Optional dependencies such as local transcription (faster-whisper),
AWS Bedrock, and Slack integration are not included in the core dependency set.
The runtime uses SQLite 3.50.4; upstream detected the version and applied its
DELETE journal fallback to the affected databases.

Production publication still requires desktop validation, a permanent GPG key
with a backup, secrets, and GitHub Pages configuration.
`LOCAL_VALIDATION_APPROVED=true` has not been set. This project is not yet in
the Flathub catalog.

## Recovery after export failure — 2026-09-26, 16:00 UTC

A subsequent run encountered an error in `flatpak build-update-repo --prune`:
an old OSTree object was missing. The error prevented bundle generation;
`repository.gpg` was the only artifact in `dist/release/`. `ostree fsck` confirmed
the inconsistency. The repository was preserved in `.cache/repo-before-recovery`.

`./scripts/build-local.sh --skip-build` recreated the repository from the existing
build, exported the bundle, and reinstalled it successfully. The Pages origin,
checksums, and backend/PTY/isolation smoke tests were verified again.
Five automated tests passed, including stopping after an export error and
preserving artifacts when repository preflight verification fails.

Artifact generated during that recovery (before the subsequent permission change):

- Commit: `cbf2660f57b915c63d585dac4c79922974c5c2725e3f0712466d63b5435f0c0a`.
- Bundle SHA-256: `42adc7b8c02f8cac056a0e789188eca6cf5c2f5f4b507f26fd7e9399c8c5a59b`.
- Logs: `.cache/export-recovery.log`, `.cache/local-recovery.log`,
  `.cache/recovery-tests.log`, `.cache/recovery-smoke.log`.

## Current bundle — restricted files and ssh-agent

The bundle was regenerated and reinstalled with `ssh-auth` and a private,
persistent `.ssh` directory, without filesystem access grants. Temporary local
overrides were removed. Tests were repeated using only the permissions embedded
in the bundle: agent signing/verification, private key inaccessibility, home
directory isolation, backend, and PTY checks passed. The GitHub Pages origin was
reconfirmed.

- Current commit: `319981c1d4d002a7351ba3569167fe7025f35736de5fe2b478b1cb284951395b`.
- Current SHA-256: `a5e47cf68e005985b93752cb1ba812ee250234070c41abf3b72ecffd42178d14`.
- Logs: `.cache/ssh-agent-export.log`, `.cache/ssh-agent-final.log`,
  `.cache/restricted-final.log`.

No external gateway connection was tested: the test validates the agent protocol
and signing locally without using real identities or contacting servers.
