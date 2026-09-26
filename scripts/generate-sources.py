#!/usr/bin/env python3
"""Regenerate reviewed Flatpak sources from upstream's npm and uv locks."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import re
import subprocess
import tomllib
from urllib.request import urlopen

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.tags import compatible_tags, cpython_tags
from packaging.utils import parse_wheel_filename

ROOT = Path(__file__).resolve().parents[1]


def python_sources(source):
    result = subprocess.run([
        "uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--extra", "mcp",
        "--format", "requirements-txt",
    ], cwd=source, check=True, capture_output=True, text=True)
    lock = tomllib.loads((source / "uv.lock").read_text())
    env = default_environment()
    env.update(python_version="3.13", python_full_version="3.13.7", sys_platform="linux",
               platform_system="Linux", platform_machine="x86_64", os_name="posix",
               platform_python_implementation="CPython", implementation_name="cpython")
    platforms = [f"manylinux_2_{n}_x86_64" for n in range(41, 16, -1)]
    platforms += ["manylinux2014_x86_64", "manylinux2010_x86_64", "manylinux1_x86_64"]
    tags = list(cpython_tags((3, 13), platforms=platforms))
    tags += list(compatible_tags((3, 13), interpreter="cp313", platforms=platforms))
    rank = {tag: i for i, tag in enumerate(tags)}
    sources, requirements = [], []
    for line in re.sub(r"\\\n\s*", " ", result.stdout).splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        req = Requirement(line.split("--hash")[0].strip())
        if req.marker and not req.marker.evaluate(env):
            continue
        package = next(p for p in lock["package"]
                       if p["name"] == req.name and req.specifier.contains(p["version"]))
        candidates = []
        for wheel in package.get("wheels", []):
            filename = wheel["url"].rsplit("/", 1)[1]
            matches = parse_wheel_filename(filename)[3] & rank.keys()
            if matches:
                candidates.append((min(rank[t] for t in matches), filename, wheel))
        if not candidates:
            raise RuntimeError(f"No locked Linux CPython 3.13 wheel for {req}")
        _, filename, wheel = min(candidates)
        digest = wheel["hash"].removeprefix("sha256:")
        sources.append({"type": "file", "url": wheel["url"], "sha256": digest,
                        "dest": "python-wheels", "dest-filename": filename})
        requirements.append(f"{req.name}=={package['version']} --hash=sha256:{digest}")
    (ROOT / "packaging/requirements.txt").write_text("\n".join(requirements) + "\n")
    return sources


def npm_sources(source):
    packages = json.loads((source / "package-lock.json").read_text())["packages"]
    sources = {}
    for package in packages.values():
        url = package.get("resolved", "")
        if not url.startswith("https://"):
            continue
        algorithm, digest = package["integrity"].split("-", 1)
        if algorithm not in ("sha512", "sha256"):
            raise ValueError(f"Unsupported integrity algorithm: {algorithm}")
        sources[url] = {"type": "file", "url": url,
                        algorithm: base64.b64decode(digest).hex(), "dest": "npm-sources",
                        "dest-filename": hashlib.sha256(url.encode()).hexdigest() + ".tgz"}
    return [sources[url] for url in sorted(sources)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    for name, sources in (("python", python_sources(args.source)), ("npm", npm_sources(args.source))):
        (ROOT / f"packaging/{name}-sources.json").write_text(json.dumps(sources, indent=2) + "\n")
        print(f"{name}: {len(sources)} locked sources")


if __name__ == "__main__":
    main()
