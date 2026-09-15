#!/bin/bash
# DietPi-Automation post-install hook: install the PM2.5 monitor unattended on first boot.
#
# Copy this file to the FAT boot partition as /boot/Automation_Custom_Script.sh and set
# AUTO_SETUP_CUSTOM_SCRIPT_EXEC=1 in /boot/dietpi.txt. DietPi runs it as root after
# networking and the base install complete.
set -eu

# --- EDIT THESE ---
REPO_URL="https://github.com/OWNER/pm2.5-pi-monitor.git"   # your fork/clone URL
TARGET="/opt/pm25"

command -v git >/dev/null 2>&1 || { apt-get update; apt-get install -y git; }

if [ ! -d "$TARGET/.git" ]; then
  git clone --depth 1 "$REPO_URL" "$TARGET"
fi

cd "$TARGET"
bash deploy/install.sh

# Tailscale is installed by install.sh; join the tailnet after first boot with:
#   sudo tailscale up
