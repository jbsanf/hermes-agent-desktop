#!/usr/bin/env python3
import json
from pathlib import Path
import subprocess
import time
from urllib.request import urlopen

c = json.loads((Path(__file__).resolve().parents[1] / "packaging/config.json").read_text())
site = c["repo_url"].removesuffix("repo/")
for attempt in range(12):
    try:
        with urlopen(site + "published.json", timeout=15) as response:
            marker = json.load(response)
        assert marker["tag"] == "v" + c["version"]
        for name in ("config", "summary", "summary.sig"):
            with urlopen(c["repo_url"] + name, timeout=15) as response:
                assert response.read(1), name
        break
    except Exception:
        if attempt == 11:
            raise
        time.sleep(10)
subprocess.run(["flatpak", "remote-add", "--user", "--if-not-exists", "hermes-published",
                site + "hermes-desktop.flatpakrepo"], check=True)
actual = subprocess.check_output(["flatpak", "remote-info", "--user", "--show-commit", "hermes-published",
                                  f"{c['app_id']}/{c['arch']}/{c['branch']}"], text=True).strip()
assert actual == marker["ostree_commit"], (actual, marker)
print("Published summary, signature and application commit verified")
