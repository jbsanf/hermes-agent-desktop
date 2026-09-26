#!/usr/bin/env python3
"""Export one signed OSTree snapshot for both Release and Pages; never upload."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import time
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CONFIG = json.loads((ROOT / "packaging/config.json").read_text())


def run(*args, **kwargs):
    print("Running: " + shlex.join(args), flush=True)
    if kwargs.get("capture_output"):
        return subprocess.run(args, check=True, **kwargs)
    start = time.monotonic()
    with subprocess.Popen(args, **kwargs) as process:
        while True:
            try:
                result = process.wait(timeout=30)
                break
            except KeyboardInterrupt:
                process.kill()
                process.wait()
                raise
            except subprocess.TimeoutExpired:
                print(f"Still running: {' '.join(args[:2])} ({int(time.monotonic() - start)}s)", flush=True)
        if result:
            raise subprocess.CalledProcessError(result, args)
        return subprocess.CompletedProcess(args, result)


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key", required=True, help="Signing key fingerprint in GNUPGHOME")
    parser.add_argument("--repo-url", default=CONFIG["repo_url"], help="Override for local rehearsal only")
    parser.add_argument("--production", action="store_true")
    args = parser.parse_args()
    if args.production and args.repo_url != CONFIG["repo_url"]:
        parser.error("Production bundles must point to the configured GitHub Pages URL")
    if args.production and not os.environ.get("LOCAL_VALIDATION_APPROVED") == "true":
        parser.error("Set LOCAL_VALIDATION_APPROVED=true only after completing docs/LOCAL-TESTS.md")
    import gi
    gi.require_version("Flatpak", "1.0")
    from gi.repository import Flatpak, Gio
    if not (ROOT / "build-dir/metadata").is_file():
        parser.error("No completed build found. Run scripts/build.sh first.")
    os.chdir(ROOT)
    if (ROOT / "repo").exists():
        try:
            run("ostree", "--repo=repo", "fsck")
        except subprocess.CalledProcessError:
            parser.error("repo/ failed integrity verification; existing artifacts were preserved. "
                         "Restore a valid repository snapshot. For local development only, "
                         "move repo/ aside and rerun scripts/build-local.sh --skip-build.")
    app, branch, arch = (CONFIG[k] for k in ("app_id", "branch", "arch"))
    release = ROOT / "dist/release"
    pages = ROOT / "dist/pages"
    for directory in (release, pages):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
    public_key = release / "repository.gpg"
    with public_key.open("wb") as output:
        run("gpg", "--batch", "--export", args.key, stdout=output)
    if not public_key.stat().st_size:
        raise RuntimeError("Signing key export was empty")
    run("flatpak", "build-export", f"--arch={arch}", f"--gpg-sign={args.key}", "repo", "build-dir", branch)
    run("flatpak", "build-update-repo", f"--gpg-sign={args.key}", "--prune", "--prune-depth=1",
        "--title=Hermes Desktop", "repo")
    run("ostree", "--repo=repo", "fsck")
    bundle = release / f"HermesDesktop-{CONFIG['version']}-{arch}.flatpak"
    run("flatpak", "build-bundle", f"--arch={arch}", f"--repo-url={args.repo_url}",
        "--runtime-repo=https://flathub.org/repo/flathub.flatpakrepo", f"--gpg-keys={public_key}",
        "repo", str(bundle), app, branch)
    reference = Flatpak.BundleRef.new(Gio.File.new_for_path(str(bundle)))
    if reference.get_origin() != args.repo_url or reference.get_name() != app:
        raise RuntimeError("Bundle identity or embedded origin is incorrect")
    encoded_key = base64.b64encode(public_key.read_bytes()).decode()
    descriptor = ("[Flatpak Repo]\nTitle=Hermes Desktop\nComment=Community Hermes Desktop packages\n"
                  f"Url={args.repo_url}\nGPGKey={encoded_key}\nDefaultBranch={branch}\n")
    (release / "hermes-desktop.flatpakrepo").write_text(descriptor)
    (release / "hermes-desktop.flatpakref").write_text(
        f"[Flatpak Ref]\nName={app}\nBranch={branch}\nTitle=Hermes Desktop\nIsRuntime=false\n"
        f"Url={args.repo_url}\nGPGKey={encoded_key}\n"
        "RuntimeRepo=https://flathub.org/repo/flathub.flatpakrepo\n")
    commit = run("ostree", "--repo=repo", "rev-parse", f"app/{app}/{arch}/{branch}",
                 capture_output=True, text=True).stdout.strip()
    provenance = {**CONFIG, "repo_url": args.repo_url, "ostree_commit": commit,
                  "signing_key": args.key, "production": args.production}
    (release / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    run("tar", "--zstd", "-cf", str(release / "repository.tar.zst"), "repo")
    assets = sorted(p for p in release.iterdir() if p.is_file())
    (release / "SHA256SUMS").write_text("".join(f"{sha256(p)}  {p.name}\n" for p in assets))
    shutil.copytree(ROOT / "repo", pages / "repo")
    for filename in ("hermes-desktop.flatpakrepo", "hermes-desktop.flatpakref", "repository.gpg"):
        shutil.copy2(release / filename, pages / filename)
    (pages / ".nojekyll").touch()
    (pages / "published.json").write_text(json.dumps({
        "tag": f"v{CONFIG['version']}", "snapshot_sha256": sha256(release / "repository.tar.zst"),
        "ostree_commit": commit,
    }, indent=2) + "\n")
    (pages / "index.html").write_text(
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>Hermes Desktop</title>'
        '<h1>Hermes Desktop</h1><p>Community distribution for Linux.</p>'
        '<p><a href="hermes-desktop.flatpakref">Install with Flatpak</a></p>'
        f'<p><a href="https://github.com/{CONFIG["repository"]}/releases">Bundles and releases</a></p>'
        '<p>Desktop and local backend included. External files require permission; authentication uses ssh-agent; local execution stays in the sandbox.</p></html>')
    size = sum(p.stat().st_size for p in pages.rglob("*") if p.is_file())
    if size > 900 * 1024 * 1024:
        raise RuntimeError(f"Pages snapshot is {size / 1024**2:.1f} MiB; limit is 900 MiB. Nothing uploaded.")
    print(f"Prepared {bundle.name}; Pages {size / 1024**2:.1f} MiB; commit {commit}")


if __name__ == "__main__":
    main()
