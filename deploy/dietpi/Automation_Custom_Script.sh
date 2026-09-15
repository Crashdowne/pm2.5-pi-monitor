#!/bin/bash
# DietPi-Automation post-install hook: install the PM2.5 monitor unattended on first boot.
#
# Copy this file to the FAT boot partition as /boot/Automation_Custom_Script.sh and set
# AUTO_SETUP_CUSTOM_SCRIPT_EXEC=1 in /boot/dietpi.txt. DietPi runs it as root after
# networking and the base install complete.
set -eu

# --- EDIT THESE ---
REPO_URL="https://github.com/crashdowne/pm2.5-pi-monitor.git"   # your fork/clone URL
REF=""                                                     # optional: pin a tag/commit (e.g. v0.2.0) for a reproducible install
TARGET="/opt/pm25"

# Trust note: this clones over HTTPS and runs deploy/install.sh, which fetches the uv and
# Tailscale install scripts via `curl | sh`. Pin REF (and review install.sh) if you need a
# reproducible, audited first boot.

command -v git >/dev/null 2>&1 || { apt-get update; apt-get install -y git; }

if [ ! -d "$TARGET/.git" ]; then
  git clone --depth 1 "$REPO_URL" "$TARGET"
fi

cd "$TARGET"
if [ -n "$REF" ]; then
  git fetch --depth 1 origin "$REF"
  git checkout --quiet FETCH_HEAD
fi
bash deploy/install.sh

# Tailscale is installed by install.sh; join the tailnet after first boot with:
#   sudo tailscale up
