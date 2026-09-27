## Hermes Desktop v0.21.5

The package version now matches Hermes Agent `0.21.5`, with project release tags
in `vx.x.x` format. The upstream release uses the tag `v2026.9.24`; its pinned
code and dependencies are unchanged from the previous package.

Community Flatpak of Hermes Desktop for Linux x86_64, with a private local backend,
restricted permissions, ssh-agent access, and local execution inside the sandbox.
It does not install the Hermes CLI/TUI.

Install the `.flatpak` file. It contains the URL of the update repository on
GitHub Pages and its public key. Once Pages is deployed, update through your
software center or with `flatpak update`.

The `.flatpakref` and `.flatpakrepo` files also let you install the application
and add the repository. See the [installation instructions](../README.md) and the
[usage guide](USAGE.md) for permissions and data storage.
