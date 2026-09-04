#!/usr/bin/env bash
# Update in place. Run with: sudo deploy/update.sh
set -euo pipefail

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Please run as root: sudo deploy/update.sh"; exit 1; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

git pull --ff-only
"$(command -v uv)" sync --extra pi
PYTHON="$REPO/.venv/bin/python"

getent group pm25-data >/dev/null || groupadd --system pm25-data
getent group pm25-secrets >/dev/null || groupadd --system pm25-secrets
for user in pm25-reader pm25-web pm25-sync pm25-alert; do
	id -u "$user" >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin "$user"
	usermod -a -G pm25-data "$user"
done
HARDWARE_GROUPS=""
for group in dialout gpio i2c; do
	if getent group "$group" >/dev/null; then
		usermod -a -G "$group" pm25-reader
		HARDWARE_GROUPS="${HARDWARE_GROUPS:+$HARDWARE_GROUPS }$group"
	fi
done
usermod -a -G pm25-secrets pm25-sync
usermod -a -G pm25-secrets pm25-alert
chown -R pm25-reader:pm25-data /var/lib/pm25
chmod -R g+rwX /var/lib/pm25
chown root:pm25-data /etc/pm25/config.toml
chown root:pm25-secrets /etc/pm25/sync.env
chmod 640 /etc/pm25/config.toml /etc/pm25/sync.env

for u in pm25-reader.service pm25-web.service pm25-sync.service pm25-sync.timer pm25-alert.service pm25-alert.timer; do
	sed -e "s#{{REPO}}#$REPO#g" -e "s#{{PYTHON}}#$PYTHON#g" -e "s#{{HARDWARE_GROUPS}}#$HARDWARE_GROUPS#g" "$REPO/deploy/$u" > "/etc/systemd/system/$u"
done
systemctl daemon-reload
systemctl enable pm25-sync.timer
systemctl restart pm25-reader.service pm25-web.service pm25-sync.timer
if "$PYTHON" -c 'from pm25.config import load_config; raise SystemExit(not load_config("/etc/pm25/config.toml").alerts.enabled)'; then
	systemctl enable pm25-alert.timer
	systemctl restart pm25-alert.timer
else
	systemctl disable --now pm25-alert.timer
fi

echo "Updated to $(git rev-parse --short HEAD)"
