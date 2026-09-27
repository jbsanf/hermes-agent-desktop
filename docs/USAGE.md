# Usage, permissions, and data

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
