# Hermes Desktop — Community Flatpak

## Install with Flatpak

For Linux x86_64. Install [Flatpak](https://flatpak.org/setup/) using your
distribution's instructions, then add Flathub for the required runtime:

```bash
flatpak remote-add --user --if-not-exists flathub https://flathub.org/repo/flathub.flatpakrepo
```

Install Hermes Desktop from the project's repository:

```bash
flatpak install --user https://jbsanf.github.io/hermes-agent-desktop/hermes-desktop.flatpakref
```

Alternatively, download the `.flatpak` bundle from
[GitHub Releases](https://github.com/jbsanf/hermes-agent-desktop/releases/latest)
and install the downloaded file, replacing the path below with its actual location:

```bash
flatpak install --user /path/to/HermesDesktop.flatpak
```

The bundle includes the update repository URL and public key. Repository
installation and updates require the project's GitHub Pages repository to be
available. Hermes Desktop is not yet listed on Flathub.

Launch the application:

```bash
flatpak run io.github.jbsanf.HermesDesktop
```

## Configure ssh-agent

For remote gateway connections over SSH, install your distribution's OpenSSH
client tools (`ssh-agent` and `ssh-add`). Load your private key into the session's
agent before opening Hermes Desktop, replacing the path if needed:

```bash
ssh-add ~/.ssh/id_ed25519
ssh-add -l
```

Enter the key's passphrase when prompted. `ssh-add -l` lists the identities
available to the agent. If no agent is running, start one, load your key, and
launch Hermes Desktop from the same terminal:

```bash
eval "$(ssh-agent -s)"
ssh-add ~/.ssh/id_ed25519
flatpak run io.github.jbsanf.HermesDesktop
```

Close any existing Hermes Desktop instance before relaunching it.
`SSH_AUTH_SOCK` must point to the running agent in the environment that launches
Flatpak; an agent started in a terminal is not automatically available to
applications launched from the desktop menu.

In Hermes Desktop's SSH connection settings, enter the host, user, and port,
and leave the key path empty to use the agent. The Flatpak already includes
access to the agent socket (`--socket=ssh-auth`). Private keys stay on the host;
the application does not need access to your host's `~/.ssh` directory.

See the [usage guide](docs/USAGE.md#remote-gateway-over-ssh) for details about
SSH configuration and persistent data.
