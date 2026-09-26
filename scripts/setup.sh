#!/bin/bash
set -euo pipefail
flatpak remote-add --user --if-not-exists flathub https://dl.flathub.org/repo/flathub.flatpakrepo
flatpak install --user --noninteractive -y flathub \
  org.freedesktop.Platform//25.08 org.freedesktop.Sdk//25.08 \
  org.electronjs.Electron2.BaseApp//25.08
