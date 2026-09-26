#!/usr/bin/env python3
"""Install backend source without public entry points, UI-TUI, or installers."""
from pathlib import Path
import shutil
import tomllib

source = Path("upstream")
target = Path("/app/share/hermes-agent")
target.mkdir(parents=True, exist_ok=True)
directories = (
    "agent", "hermes_cli", "tools", "gateway", "tui_gateway", "cron", "providers",
    "plugins", "skills", "optional-skills", "optional-mcps", "acp_adapter", "locales",
    "assets", "hermes_platform",
)
for name in directories:
    if (source / name).is_dir():
        shutil.copytree(source / name, target / name,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "AGENTS.md"))
for pattern in ("*.py", "*.toml", "*.yaml", "*.json", "*.md", "LICENSE"):
    for file in source.glob(pattern):
        if file.is_file():
            shutil.copy2(file, target / file.name)
# Keep distribution metadata used by importlib.metadata, without registering scripts.
version = tomllib.loads((source / "pyproject.toml").read_text())["project"]["version"]
metadata = Path(f"/app/lib/python3.13/site-packages/hermes_agent-{version}.dist-info")
metadata.mkdir(parents=True)
(metadata / "METADATA").write_text(f"Metadata-Version: 2.1\nName: hermes-agent\nVersion: {version}\n")
