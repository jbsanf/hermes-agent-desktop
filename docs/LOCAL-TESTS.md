# Required local validation

Do not enable production publication before recording the results below in
`docs/VALIDATION.md`. Backend tests do not replace GUI validation.

1. Run `scripts/setup.sh`, `python3 scripts/check.py`, and `scripts/build.sh`.
2. Generate a local key with `scripts/local-key.sh`. Export `GNUPGHOME="$PWD/.local-keys"`.
3. Run `python3 scripts/publish-repo.py --key FINGERPRINT`, then `scripts/install-local.sh`.
4. Run `python3 scripts/smoke.py`. Check the backend, absence of CLI/TUI entry points,
   filesystem isolation, and sandbox execution.
5. Open `flatpak run io.github.jbsanf.HermesDesktop` in a real Linux desktop session.
6. Configure a provider in the interface, send a message, and confirm streaming.
   Do not include credentials in logs, commits, or screenshots.
7. Create a project by selecting a folder through the portal. Read and write a file
   in that folder, restart the application, and repeat. Confirm that an unauthorized
   folder remains inaccessible.
8. Check history, settings, the integrated terminal, opening links in a browser,
   the clipboard, and the notice that updates are managed by Flatpak.
9. Close the application and confirm that no backend processes remain running.
10. Run the [update rehearsal](DEVELOPMENT.md#update-rehearsal) without manually changing
    the remote between revisions. Preserve test data and record the before/after commits.

The development key must never sign a public release. Remove installations signed
with that key before installing the distribution signed with the production key.

Features that depend on external host tools are not guaranteed in this sandbox.
The agent runs commands inside Flatpak. Private directories under
`~/.var/app/io.github.jbsanf.HermesDesktop` remain separate from other Hermes installations.

Also run `python3 scripts/ssh-agent-smoke.py`: it validates signing through the
agent with a temporary key and confirms that the private key file is inaccessible.
