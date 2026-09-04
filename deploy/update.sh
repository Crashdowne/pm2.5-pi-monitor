#!/usr/bin/env bash
# Update in place. Run with: sudo deploy/update.sh
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

git pull --ff-only
"$(command -v uv)" sync --extra pi
PYTHON="$REPO/.venv/bin/python"
HARDWARE_GROUPS=""
for group in dialout gpio i2c; do
	getent group "$group" >/dev/null && HARDWARE_GROUPS="${HARDWARE_GROUPS:+$HARDWARE_GROUPS }$group"
done
for u in pm25-reader.service pm25-web.service pm25-sync.service pm25-sync.timer pm25-alert.service pm25-alert.timer; do
	sed -e "s#{{REPO}}#$REPO#g" -e "s#{{PYTHON}}#$PYTHON#g" -e "s#{{HARDWARE_GROUPS}}#$HARDWARE_GROUPS#g" "$REPO/deploy/$u" > "/etc/systemd/system/$u"
done
systemctl daemon-reload
systemctl enable pm25-sync.timer pm25-alert.timer
systemctl restart pm25-reader.service pm25-web.service pm25-sync.timer pm25-alert.timer

echo "Updated to $(git rev-parse --short HEAD)"
