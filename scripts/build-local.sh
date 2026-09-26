#!/bin/bash
# Local development only: never publishes or uses production signing credentials.
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."
if [[ $# -gt 1 || ( $# -eq 1 && $1 != --skip-build ) ]]; then
  echo "Usage: $0 [--skip-build]" >&2
  exit 2
fi
if [[ ${1:-} != --skip-build ]]; then
  scripts/setup.sh
  python3 scripts/check.py
  scripts/build.sh
elif [[ ! -f build-dir/metadata || ! -x build-dir/files/bin/hermes-desktop ]]; then
  echo 'No completed build found. Run scripts/build-local.sh without --skip-build.' >&2
  exit 1
fi
local_key=$(scripts/local-key.sh)
export GNUPGHOME="$PWD/.local-keys"
python3 -u scripts/publish-repo.py --key "$local_key"
scripts/install-local.sh
