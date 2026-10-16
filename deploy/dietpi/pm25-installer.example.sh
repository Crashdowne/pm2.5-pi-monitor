#!/bin/bash
# Example drop-in installer for the DietPi first-boot bootstrap.
#
# If the boot partition contains pm25-installer.sh, deploy/dietpi/Automation_Custom_Script.sh
# runs it (as root, after Tailscale is up) instead of fetching the source and running
# deploy/install.sh itself. Exit 0 marks the install done; any other exit code makes the
# bootstrap retry every 15 minutes. Its output goes to /var/lib/pm25/bootstrap.log.
#
# Environment provided by the bootstrap:
#   PM25_TARGET     install directory (default /opt/pm25)
#   PM25_BRANCH     local branch name for OTA updates (default main)
#   PM25_BOOT_DIR   boot partition mount point (/boot or /boot/firmware)
#   PM25_BOARD      pi, radxa, or empty for auto-detect
#   TS_HOSTNAME     tailnet machine name
#   PM25_TS_HTTPS   1 = publish the dashboard with tailscale serve
#   PM25_LOCKDOWN   1 = install the egress firewall
#
# This example fetches a git bundle from your dev machine over the tailnet. Edit it freely:
# rsync, a private Git server on the tailnet, or a tarball copied next to it all work, as long as
# a git checkout on a branch ends up in $PM25_TARGET (OTA updates fast-forward that branch).
set -euo pipefail

URL="https://devbox.example-tailnet.ts.net:8443/pm25.bundle"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL --retry 5 --retry-delay 10 --retry-all-errors -o "$TMP/pm25.bundle" "$URL"

rm -rf "$PM25_TARGET"
git init -q -b "$PM25_BRANCH" "$PM25_TARGET"
REF="$(git bundle list-heads "$TMP/pm25.bundle" | awk '$2 != "HEAD" {print $2; exit}')"
git -C "$PM25_TARGET" fetch -q "$TMP/pm25.bundle" "${REF:-HEAD}"
git -C "$PM25_TARGET" checkout -q -B "$PM25_BRANCH" FETCH_HEAD

TS_AUTHKEY="" bash "$PM25_TARGET/deploy/install.sh"
