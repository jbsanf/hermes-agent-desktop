#!/usr/bin/env python3
"""Exercise the installed backend and sandbox with disposable application state."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import time
from urllib.request import Request, urlopen

APP = "io.github.jbsanf.HermesDesktop"
root = Path.home() / ".var/app" / APP / "data"
run_id = "smoke-" + secrets.token_hex(6)
state = root / run_id
state.mkdir(parents=True)
token = secrets.token_urlsafe(32)
ready = state / "ready.json"
base = ["flatpak", "run", "--user", "--command=sh", APP]
denied = Path.home() / (".hermes-flatpak-denied-" + secrets.token_hex(6))
try:
    denied.write_text("sandbox boundary fixture")
    subprocess.run([*base, "-ec", 'test -f /.flatpak-info; test ! -e "$1"; ! command -v hermes; ! command -v hermes-agent; test ! -d /app/share/hermes-agent/ui-tui', "sh", str(denied)], check=True)
finally:
    denied.unlink()
native_test = Path(__file__).resolve().parents[1] / "tests/native-pty.cjs"
subprocess.run([
    "flatpak", "run", "--user", "--env=ELECTRON_RUN_AS_NODE=1",
    "--command=/app/lib/hermes-electron/electron", APP, "-e", native_test.read_text(),
], check=True, timeout=30)
log = state / "backend.log"
instance_file = state / "instance"
try:
    with log.open("w") as output, instance_file.open("w+") as instance:
        proc = subprocess.Popen([
            "flatpak", "run", "--user", "--die-with-parent", f"--instance-id-fd={instance.fileno()}", "--command=/app/libexec/hermes-backend",
            f"--env=HERMES_HOME={state}", f"--env=HERMES_DESKTOP_READY_FILE={ready}",
            f"--env=HERMES_DASHBOARD_SESSION_TOKEN={token}", "--env=HERMES_DESKTOP=1",
            APP, "serve", "--host", "127.0.0.1", "--port", "0",
        ], stdout=output, stderr=subprocess.STDOUT, pass_fds=(instance.fileno(),))
        try:
            deadline = time.monotonic() + 90
            while not ready.exists():
                if proc.poll() is not None:
                    raise RuntimeError(f"Backend exited: {log.read_text()[-12000:]}")
                if time.monotonic() > deadline:
                    raise TimeoutError(f"Backend did not become ready: {log.read_text()[-12000:]}")
                time.sleep(0.25)
            port = json.loads(ready.read_text())["port"]
            request = Request(f"http://127.0.0.1:{port}/api/health", headers={"X-Hermes-Session-Token": token})
            with urlopen(request, timeout=15) as response:
                assert response.status == 200
                print("Backend health:", response.read().decode()[:1000])
            print("PASS: private backend boot, health endpoint, no public CLI/TUI, filesystem isolation, sandbox execution")
        finally:
            instance.seek(0)
            instance_id = instance.read().strip()
            if instance_id:
                subprocess.run(["flatpak", "kill", instance_id], check=False)
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
finally:
    print(f"Smoke logs preserved at {state}")
