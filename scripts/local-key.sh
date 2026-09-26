#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
install -d -m700 .local-keys
export GNUPGHOME="$PWD/.local-keys"
if ! gpg --list-secret-keys --with-colons 2>/dev/null | grep -q '^sec:'; then
  gpg --batch --pinentry-mode loopback --passphrase '' \
    --quick-generate-key 'Hermes Flatpak LOCAL TEST ONLY' ed25519 sign 0
fi
gpg --list-secret-keys --with-colons 2>/dev/null | awk -F: '$1=="fpr" { print $10; exit }'
