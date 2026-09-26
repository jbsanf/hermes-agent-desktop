#!/bin/bash
set -euo pipefail
python3 -c 'import sys; assert sys.version_info[:2] == (3, 13), sys.version'
export npm_config_cache="$PWD/npm-cache"
export npm_config_offline=true
export npm_config_audit=false
export npm_config_fund=false
export ELECTRON_SKIP_BINARY_DOWNLOAD=1
electron_headers="$PWD/electron-headers"
python3 - <<'PY'
from pathlib import Path
import subprocess
files = sorted(str(p.resolve()) for p in Path('npm-sources').glob('*.tgz'))
for offset in range(0, len(files), 64):
    subprocess.run(['npm', 'cache', 'add', '--ignore-scripts', '--offline', *files[offset:offset+64]], check=True)
PY
cd upstream
# Upstream has renderer imports supplied by other workspace declarations
# (including lucide-react). Install the locked workspace graph, but build and
# ship only Desktop. Lifecycle scripts are never run implicitly.
npm ci --offline --ignore-scripts
node node_modules/node-gyp/bin/node-gyp.js rebuild --directory=node_modules/node-pty \
  --target=40.10.2 --arch=x64 --nodedir="$electron_headers" --dist-url=''
# Only the renderer, main/preload and their native dependencies are built.
cd apps/desktop
mkdir -p build
node scripts/write-build-stamp.mjs
../../node_modules/.bin/vite build
node scripts/bundle-electron-main.mjs
node scripts/stage-native-deps.mjs linux x64
node scripts/assert-dist-built.mjs
mkdir -p /app/lib/hermes-electron/resources/app
cp -a dist assets public package.json /app/lib/hermes-electron/resources/app/
cp build/install-stamp.json /app/lib/hermes-electron/resources/install-stamp.json
node - <<'JS'
const fs = require('fs');
const p = '/app/lib/hermes-electron/resources/app/package.json';
const metadata = JSON.parse(fs.readFileSync(p));
metadata.name = 'io.github.jbsanf.HermesDesktop';
metadata.productName = 'Hermes Desktop';
metadata.version = process.env.FLATPAK_PACKAGE_VERSION;
fs.writeFileSync(p, JSON.stringify(metadata, null, 2));
JS
