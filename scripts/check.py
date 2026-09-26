#!/usr/bin/env python3
"""Validate distribution contracts before downloading or building."""
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
c = json.loads((ROOT / "packaging/config.json").read_text())
manifest_path = ROOT / f"{c['app_id']}.json"
original = manifest_path.read_bytes()
subprocess.run(["python3", str(ROOT / "scripts/generate-manifest.py"), "--check"], check=True)
m = json.loads(original)
assert m["app-id"] == c["app_id"]
assert m["default-branch"] == c["branch"]
assert "--socket=ssh-auth" in m["finish-args"]
assert "--persist=.ssh" in m["finish-args"]
for flag in m["finish-args"]:
    assert not flag.startswith("--filesystem="), f"Unexpected filesystem permission: {flag}"
    assert flag not in ("--socket=session-bus", "--socket=system-bus", "--device=all")
    assert "org.freedesktop.Flatpak" not in flag
assert m["command"] == "hermes-desktop"
assert c["repo_url"] == f"https://{c['repository'].split('/')[0]}.github.io/{c['repository'].split('/')[1]}/repo/"
for filename in ("python-sources.json", "npm-sources.json"):
    sources = json.loads((ROOT / "packaging" / filename).read_text())
    assert sources
    for source in sources:
        assert source["url"].startswith("https://")
        assert any(len(source.get(algo, "")) == size for algo, size in (("sha256", 64), ("sha512", 128)))
xml = ET.parse(ROOT / f"packaging/{c['app_id']}.metainfo.xml").getroot()
assert xml.findtext("id") == c["app_id"]
assert xml.find("releases/release").attrib["version"] == c["version"]
subprocess.run(["desktop-file-validate", str(ROOT / f"packaging/{c['app_id']}.desktop")], check=True)
subprocess.run(["appstreamcli", "validate", "--no-net", str(ROOT / f"packaging/{c['app_id']}.metainfo.xml")], check=True)
subprocess.run(["flatpak-builder", "--show-deps", str(manifest_path)], check=True, stdout=subprocess.DEVNULL)
print("Manifest, identity, restricted files, SSH agent and sandbox execution, locked sources and desktop metadata validated")
