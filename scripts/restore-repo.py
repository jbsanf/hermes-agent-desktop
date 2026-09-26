#!/usr/bin/env python3
"""Restore only the snapshot referenced by the last successful Pages deployment."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import tarfile
import tempfile
from urllib.error import HTTPError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--key-file", type=Path, required=True)
    args = parser.parse_args()
    config = json.loads((ROOT / "packaging/config.json").read_text())
    if (ROOT / "repo").exists():
        raise RuntimeError("repo/ already exists; use a clean publication workspace")
    url = config["repo_url"].removesuffix("repo/") + "published.json"
    try:
        with urlopen(url, timeout=30) as response:
            marker = json.load(response)
    except HTTPError as error:
        if error.code != 404:
            raise
        releases = subprocess.check_output([
            "gh", "api", f"repos/{config['repository']}/releases", "--paginate",
            "--jq", '.[].assets[] | select(.name == "repository.tar.zst") | .id',
        ], text=True).strip()
        if releases:
            raise RuntimeError("Pages marker is missing but published snapshots exist; restore Pages before continuing")
        print("First publication: no previous repository or release snapshot")
        return
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        subprocess.run(["gh", "release", "download", marker["tag"], "--repo", config["repository"],
                        "--pattern", "repository.tar.zst", "--dir", str(directory)], check=True)
        archive = directory / "repository.tar.zst"
        with archive.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if digest != marker["snapshot_sha256"]:
            raise RuntimeError("Previous repository checksum mismatch")
        raw_tar = directory / "repository.tar"
        with raw_tar.open("wb") as output:
            subprocess.run(["zstd", "-dc", str(archive)], check=True, stdout=output)
        with tarfile.open(raw_tar) as tar:
            for member in tar.getmembers():
                parts = PurePosixPath(member.name).parts
                if not parts or parts[0] != "repo" or ".." in parts or not (member.isfile() or member.isdir()):
                    raise RuntimeError(f"Unexpected snapshot archive entry: {member.name}")
            tar.extractall(ROOT, filter="data")
    repo = f"--repo={ROOT / 'repo'}"
    subprocess.run(["ostree", repo, "fsck"], check=True)
    subprocess.run(["ostree", repo, "remote", "add", "--if-not-exists",
                    f"--gpg-import={args.key_file.resolve()}", "previous", config["repo_url"]], check=True)
    ref = f"app/{config['app_id']}/{config['arch']}/{config['branch']}"
    actual = subprocess.check_output(["ostree", repo, "rev-parse", ref], text=True).strip()
    if actual != marker["ostree_commit"]:
        raise RuntimeError("Snapshot ref does not match published commit")
    subprocess.run(["ostree", repo, "show", "--gpg-verify-remote=previous", actual], check=True)


if __name__ == "__main__":
    main()
