#!/usr/bin/env python3
"""Real bundle → signed HTTP remote → update, using the local test installation."""
import argparse
import functools
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading

ROOT = Path(__file__).resolve().parents[1]


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def output(*args):
    return subprocess.check_output(args, text=True).strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", required=True)
    parser.add_argument("--replace-local-test-install", action="store_true", required=True)
    args = parser.parse_args()
    c = json.loads((ROOT / "packaging/config.json").read_text())
    app, arch, branch = (c[k] for k in ("app_id", "arch", "branch"))
    production_bundle = next((ROOT / "dist/release").glob("*.flatpak"))
    public_key = ROOT / "dist/release/repository.gpg"
    with tempfile.TemporaryDirectory(prefix="rehearsal-", dir=ROOT / ".cache") as directory:
        directory = Path(directory)
        repo = directory / "repo"
        shutil.copytree(ROOT / "repo", repo)
        handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        bundle = directory / "first.flatpak"
        origin = None
        replaced = False
        marker = Path.home() / ".var/app" / app / "data/update-rehearsal.txt"
        if marker.exists():
            raise RuntimeError(f"Refusing to overwrite existing test fixture: {marker}")
        try:
            url = f"http://127.0.0.1:{server.server_port}/repo/"
            run("flatpak", "build-bundle", f"--arch={arch}", f"--repo-url={url}",
                "--runtime-repo=https://flathub.org/repo/flathub.flatpakrepo", f"--gpg-keys={public_key}",
                str(repo), str(bundle), app, branch)
            run("flatpak", "uninstall", "--user", "--noninteractive", "-y", app)
            replaced = True
            run("flatpak", "install", "--user", "--noninteractive", "-y", str(bundle))
            first = output("flatpak", "info", "--user", "--show-commit", app)
            origin = output("flatpak", "info", "--user", "--show-origin", app)
            marker.write_text("must survive the update\n")
            build = directory / "build"
            shutil.copytree(ROOT / "build-dir", build, copy_function=os.link, symlinks=True)
            (build / "files/share/hermes-flatpak-rehearsal").write_text("revision two\n")
            run("flatpak", "build-export", f"--gpg-sign={args.key}", str(repo), str(build), branch)
            run("flatpak", "build-update-repo", f"--gpg-sign={args.key}", str(repo))
            run("flatpak", "update", "--user", "--noninteractive", "-y", app)
            second = output("flatpak", "info", "--user", "--show-commit", app)
            assert second != first, "Application did not update"
            assert output("flatpak", "info", "--user", "--show-origin", app) == origin
            assert marker.read_text() == "must survive the update\n"
            installed = output("flatpak", "run", "--user", "--command=cat", app, "/app/share/hermes-flatpak-rehearsal")
            assert installed == "revision two"
            report = {"first_commit": first, "second_commit": second, "origin": origin,
                      "same_origin": True, "data_preserved": True}
            (ROOT / "dist/update-rehearsal.json").write_text(json.dumps(report, indent=2) + "\n")
            print("PASS: installed bundle updated through its embedded signed remote; data preserved")
        finally:
            server.shutdown()
            server.server_close()
            # Restore the original Pages-origin bundle; never delete application data.
            if replaced:
                subprocess.run(["flatpak", "uninstall", "--user", "--noninteractive", "-y", app], check=False)
                if origin:
                    remotes = output("flatpak", "remotes", "--user", "--columns=name,url")
                    urls = dict(line.split("\t", 1) for line in remotes.splitlines())
                    if urls.get(origin, "").rstrip("/") == url.rstrip("/"):
                        run("flatpak", "remote-delete", "--user", origin)
                run("flatpak", "install", "--user", "--noninteractive", "-y", str(production_bundle))
            marker.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
