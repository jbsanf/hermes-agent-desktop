#!/usr/bin/env python3
"""Check agent-backed signatures without exposing a private key to the app."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

APP = "io.github.jbsanf.HermesDesktop"


def main():
    data = Path.home() / ".var/app" / APP / "data"
    data.mkdir(parents=True, exist_ok=True)
    # Never load test identities into the user's real agent.
    with tempfile.TemporaryDirectory(prefix="hermes-agent-private-") as private, \
            tempfile.TemporaryDirectory(prefix="ssh-agent-smoke-", dir=data) as public:
        private, public = Path(private), Path(public)
        key = private / "identity"
        sock = private / "agent.sock"
        subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
        public_key = public / "identity.pub"
        shutil.copy2(key.with_suffix(".pub"), public_key)
        env = {**os.environ, "SSH_AUTH_SOCK": str(sock)}
        with (private / "agent.log").open("w") as log:
            agent = subprocess.Popen(["ssh-agent", "-D", "-a", str(sock)], stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 10
                while not sock.exists():
                    if agent.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError("Test SSH agent did not start")
                    time.sleep(0.1)
                subprocess.run(["ssh-add", str(key)], env=env, check=True, capture_output=True)
                subprocess.run([
                    "flatpak", "run", "--user", "--command=sh", APP, "-ec",
                    'test -f /.flatpak-info; test ! -e "$1"; test -S "$SSH_AUTH_SOCK"; ssh-add -T "$2"',
                    "sh", str(key), str(public_key),
                ], env=env, check=True, timeout=30)
                print("PASS: sandbox used SSH agent to sign and verify; private key file remained inaccessible")
            finally:
                agent.terminate()
                try:
                    agent.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    agent.kill()
                    agent.wait()


if __name__ == "__main__":
    main()
