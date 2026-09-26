#!/usr/bin/env python3
"""Check the origin created by installing the actual release bundle."""
import json
from pathlib import Path
import subprocess

c = json.loads((Path(__file__).resolve().parents[1] / "packaging/config.json").read_text())
origin = subprocess.check_output(["flatpak", "info", "--user", "--show-origin", c["app_id"]], text=True).strip()
remotes = subprocess.check_output(["flatpak", "remotes", "--user", "--columns=name,url"], text=True)
urls = dict(line.split("\t", 1) for line in remotes.splitlines())
assert urls[origin].rstrip("/") == c["repo_url"].rstrip("/"), (origin, urls[origin])
print(f"Installed bundle origin verified: {origin} → {urls[origin]}")
