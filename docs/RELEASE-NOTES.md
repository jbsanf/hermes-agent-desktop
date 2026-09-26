Community Flatpak of Hermes Desktop for Linux x86_64, with a private local backend,
restricted permissions, ssh-agent access, and local execution inside the sandbox.
It does not install the Hermes CLI/TUI.

Install the `.flatpak` file. It contains the URL of the update repository on
GitHub Pages and its public key. Once Pages is deployed, update through your
software center or with `flatpak update`.

The `.flatpakref` and `.flatpakrepo` files also let you install the application
and add the repository. See the README for dependencies, permissions, and data storage.
