#!/usr/bin/env python3
"""Render the manifest from the reviewed release configuration."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
c = json.loads((ROOT / "packaging/config.json").read_text())
app = c["app_id"]

manifest = {
    "app-id": app, "runtime": "org.freedesktop.Platform", "runtime-version": c["runtime_version"],
    "sdk": "org.freedesktop.Sdk", "base": "org.electronjs.Electron2.BaseApp",
    "base-version": c["runtime_version"], "command": "hermes-desktop",
    "default-branch": c["branch"], "separate-locales": False,
    "finish-args": ["--share=ipc", "--share=network", "--socket=wayland", "--socket=fallback-x11",
                    "--socket=pulseaudio", "--device=dri", "--socket=ssh-auth", "--persist=.ssh", "--talk-name=org.freedesktop.secrets",
                    "--env=XCURSOR_PATH=/run/host/user-share/icons:/run/host/share/icons"],
    "cleanup": ["/include", "/share/man", "/lib/pkgconfig", "/lib/debug"],
    "build-options": {"strip": True, "no-debuginfo": True,
                      "env": {"GITHUB_SHA": c["upstream_commit"], "GITHUB_REF_NAME": c["upstream_tag"],
                              "FLATPAK_PACKAGE_VERSION": c["version"], "ELECTRON_VERSION": c["electron_version"]}},
    "modules": [
        {"name": "git", "buildsystem": "simple", "build-commands": [
            "make -j${FLATPAK_BUILDER_N_JOBS} prefix=/app NO_RUST=YesPlease NO_GETTEXT=YesPlease NO_TCLTK=YesPlease NO_PERL=YesPlease all",
            "make prefix=/app INSTALL_SYMLINKS=YesPlease NO_RUST=YesPlease NO_GETTEXT=YesPlease NO_TCLTK=YesPlease NO_PERL=YesPlease install"],
         "sources": [{"type": "archive", "archive-type": "tar-gzip", "url": "https://api.github.com/repos/git/git/tarball/refs/tags/v2.55.0",
                      "sha256": "8585abb7ea9636dd9bf95b04301a19f503acddc5140ec4f5659a71d40ee2aed2"}]},
        {"name": "node", "buildsystem": "simple", "build-commands": ["cp -a bin include lib share /app/"],
         "sources": [{"type": "archive", "url": f"https://nodejs.org/dist/v{c['node_version']}/node-v{c['node_version']}-linux-x64.tar.xz",
                      "sha256": c["node_sha256"]}]},
        {"name": "electron", "buildsystem": "simple",
         "build-commands": ["mkdir -p /app/lib/hermes-electron", "cp -a . /app/lib/hermes-electron/"],
         "sources": [{"type": "archive", "url": f"https://github.com/electron/electron/releases/download/v{c['electron_version']}/electron-v{c['electron_version']}-linux-x64.zip",
                      "sha256": c["electron_sha256"], "strip-components": 0}]},
        {"name": "python-dependencies", "buildsystem": "simple", "build-commands": [
            'python3 -c "import sys; assert sys.version_info[:2] == (3, 13), sys.version"',
            "pip3 install --no-index --no-deps --no-compile --require-hashes --ignore-installed --prefix=/app --find-links=python-wheels -r requirements.txt"],
         "sources": ["packaging/python-sources.json", {"type": "file", "path": "packaging/requirements.txt"}]},
        {"name": "hermes-desktop", "buildsystem": "simple", "build-commands": [
            "bash build-desktop.sh", "python3 install-payload.py",
            "install -Dm755 hermes-desktop /app/bin/hermes-desktop",
            "install -Dm755 hermes-backend /app/libexec/hermes-backend",
            "install -Dm644 hermes-backend.py /app/libexec/hermes-backend.py",
            f"install -Dm644 {app}.desktop /app/share/applications/{app}.desktop",
            f"install -Dm644 {app}.metainfo.xml /app/share/metainfo/{app}.metainfo.xml",
            f"install -Dm644 upstream/apps/desktop/assets/icon.png /app/share/icons/hicolor/1024x1024/apps/{app}.png",
            "install -Dm644 upstream/LICENSE /app/share/licenses/hermes-desktop/LICENSE"],
         "sources": [
            {"type": "archive", "archive-type": "tar-gzip", "url": f"https://api.github.com/repos/NousResearch/hermes-agent/tarball/{c['upstream_commit']}",
             "sha256": c["upstream_sha256"], "dest": "upstream"},
            {"type": "patch", "path": "patches/flatpak-integration.patch", "options": ["-d", "upstream"]},
            {"type": "archive", "url": f"https://artifacts.electronjs.org/headers/dist/v{c['electron_version']}/node-v{c['electron_version']}-headers.tar.gz",
             "sha256": c["electron_headers_sha256"], "dest": "electron-headers"},
            "packaging/npm-sources.json",
            *[{"type": "file", "path": p} for p in [
                "scripts/build-desktop.sh", "scripts/install-payload.py", "packaging/hermes-desktop",
                "packaging/hermes-backend", "packaging/hermes-backend.py", f"packaging/{app}.desktop",
                f"packaging/{app}.metainfo.xml"]]]},
        {"name": "desktop-icons", "buildsystem": "simple", "build-commands": [
            "PYTHONPATH=/app/lib/python3.13/site-packages python3 install-icons.py"],
         "sources": [{"type": "file", "path": "scripts/install-icons.py"}]}
    ]
}
target = ROOT / f"{app}.json"
rendered = json.dumps(manifest, indent=2) + "\n"
if "--check" in sys.argv:
    if target.read_text() != rendered:
        sys.exit("Manifest is stale; run scripts/generate-manifest.py and commit the result")
else:
    target.write_text(rendered)
