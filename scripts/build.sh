#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
flatpak-builder --user --force-clean --disable-rofiles-fuse --jobs=4 \
  build-dir io.github.jbsanf.HermesDesktop.json "$@"
