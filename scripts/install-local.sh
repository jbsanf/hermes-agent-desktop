#!/bin/bash
set -euo pipefail
project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ $# -gt 1 ]]; then
  echo "Usage: $0 [path/to/application.flatpak]" >&2
  exit 2
fi
if [[ $# -eq 1 ]]; then
  bundle=$1
else
  filename=$(python3 - "$project_root/packaging/config.json" <<'PY'
import json
import sys
with open(sys.argv[1]) as source:
    config = json.load(source)
print(f"HermesDesktop-{config['version']}-{config['arch']}.flatpak")
PY
  )
  bundle="$project_root/dist/release/$filename"
fi
if [[ ! -f "$bundle" ]]; then
  printf 'Bundle not found: %s\n' "$bundle" >&2
  if [[ -f "$project_root/build-dir/metadata" ]]; then
    printf 'The build exists, but its bundle has not been exported successfully.\nRun: %q --skip-build\n' "$project_root/scripts/build-local.sh" >&2
  else
    printf 'Run: %q\n' "$project_root/scripts/build-local.sh" >&2
  fi
  exit 1
fi
bundle=$(realpath -- "$bundle")
printf 'Installing bundle: %s\n' "$bundle"
flatpak install --user --noninteractive --reinstall -y "$bundle"
flatpak info --user io.github.jbsanf.HermesDesktop
