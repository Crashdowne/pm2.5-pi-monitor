#!/usr/bin/env bash
# Install the PM2.5 monitor on a Raspberry Pi running DietPi. Run with: sudo deploy/install.sh
set -euo pipefail

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Please run as root: sudo deploy/install.sh"; exit 1; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "Repo: $REPO"

# --- base OS packages (DietPi minimal ships without git; iw disables Wi-Fi power save) ---
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y || echo "warning: apt-get update failed; continuing with installed packages"
  apt-get install -y --no-install-recommends git ca-certificates curl iw ||
    echo "warning: could not install one or more base packages"
fi

# --- preflight: warn if a dependency would fall back to a slow on-device source build ---
ARCH="$(uname -m)"
if [[ "$ARCH" != "aarch64" && "$ARCH" != "armv7l" ]]; then
  echo "warning: unexpected architecture '$ARCH' (expected aarch64 on a 64-bit DietPi image)"
fi
if [[ "$ARCH" == "aarch64" ]] && command -v dpkg >/dev/null 2>&1; then
  GLIBC_VER="$(getconf GNU_LIBC_VERSION 2>/dev/null | awk '{print $2}')"
  if [[ -n "$GLIBC_VER" ]] && dpkg --compare-versions "$GLIBC_VER" lt 2.34; then
    echo "warning: glibc $GLIBC_VER < 2.34 - lgpio may build from source; prefer a Trixie/Bookworm arm64 image"
  fi
fi

# --- least-privilege service accounts, directories, config, secrets ---
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
install -d -o pm25-reader -g pm25-data -m 2770 /var/lib/pm25
install -d -o root -g pm25-data -m 750 /etc/pm25
[[ -f /etc/pm25/config.toml ]] || install -o root -g pm25-data -m 640 "$REPO/config.example.toml" /etc/pm25/config.toml
if [[ ! -f /etc/pm25/sync.env ]]; then
  printf 'PM25_SYNC_TOKEN=\n' > /etc/pm25/sync.env
  chown root:pm25-secrets /etc/pm25/sync.env
  chmod 640 /etc/pm25/sync.env
fi
chown -R pm25-reader:pm25-data /var/lib/pm25
chmod -R g+rwX /var/lib/pm25
chown root:pm25-data /etc/pm25/config.toml
chown root:pm25-secrets /etc/pm25/sync.env
chmod 640 /etc/pm25/config.toml /etc/pm25/sync.env

# --- uv + dependencies ---
if ! command -v uv >/dev/null 2>&1; then
  echo "Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
UV="$(command -v uv)"
( cd "$REPO" && "$UV" sync --extra pi )
PYTHON="$REPO/.venv/bin/python"

# --- create the complete application schema before services start ---
"$PYTHON" -c 'from pm25 import db; from pm25.config import load_config; cfg = load_config("/etc/pm25/config.toml"); conn = db.connect(cfg.storage.db_path); db.init_db(conn); conn.close()'
chown -R pm25-reader:pm25-data /var/lib/pm25
chmod -R g+rwX /var/lib/pm25

# --- prebuilt dashboard: the web service serves aqi-worker/web/dist when present (no Node on the Pi) ---
if [[ -f "$REPO/aqi-worker/web/dist/index.html" ]]; then
  echo "Dashboard: serving the prebuilt React app from aqi-worker/web/dist"
else
  echo "warning: aqi-worker/web/dist not found; serving the lightweight fallback dashboard."
  echo "         Build on a dev machine: 'npm --prefix aqi-worker/web run build', then commit dist/."
fi

# --- free the UART for the PMS5003 (hand PL011 to the GPIO header) ---
BOOT=/boot/firmware/config.txt;     [[ -f $BOOT ]]    || BOOT=/boot/config.txt
CMDLINE=/boot/firmware/cmdline.txt; [[ -f $CMDLINE ]] || CMDLINE=/boot/cmdline.txt
if [[ -f $BOOT ]]; then
  grep -q '^enable_uart=1'        "$BOOT" || echo 'enable_uart=1'        >> "$BOOT"
  grep -q '^dtoverlay=disable-bt' "$BOOT" || echo 'dtoverlay=disable-bt' >> "$BOOT"
fi
[[ -f $CMDLINE ]] && sed -i 's/console=serial0,[0-9]* //g' "$CMDLINE" || true
systemctl disable --now hciuart 2>/dev/null || true
systemctl disable --now serial-getty@ttyAMA0.service 2>/dev/null || true

# --- enable I2C for the SHT31-D humidity sensor ---
if [[ -f $BOOT ]]; then
  grep -q '^dtparam=i2c_arm=on' "$BOOT" || echo 'dtparam=i2c_arm=on' >> "$BOOT"
fi
grep -q '^i2c-dev' /etc/modules 2>/dev/null || echo 'i2c-dev' >> /etc/modules

# --- systemd units ---
for u in pm25-reader.service pm25-web.service pm25-sync.service pm25-sync.timer pm25-alert.service pm25-alert.timer; do
  sed -e "s#{{REPO}}#$REPO#g" -e "s#{{PYTHON}}#$PYTHON#g" -e "s#{{HARDWARE_GROUPS}}#$HARDWARE_GROUPS#g" "$REPO/deploy/$u" > "/etc/systemd/system/$u"
done
install -m 644 "$REPO/deploy/pm25-wifi-powersave.service" /etc/systemd/system/pm25-wifi-powersave.service
systemctl daemon-reload
systemctl enable --now pm25-reader.service pm25-web.service pm25-sync.timer pm25-wifi-powersave.service
if "$PYTHON" -c 'from pm25.config import load_config; raise SystemExit(not load_config("/etc/pm25/config.toml").alerts.enabled)'; then
  systemctl enable --now pm25-alert.timer
else
  systemctl disable --now pm25-alert.timer
fi

# --- spare the SD card: keep the systemd journal in RAM (database writes still go to disk) ---
install -d /etc/systemd/journald.conf.d
install -m 644 "$REPO/deploy/journald-pm25.conf" /etc/systemd/journald.conf.d/pm25.conf
systemctl restart systemd-journald 2>/dev/null || true

# --- Tailscale: install the client + service (join the tailnet later with `tailscale up`) ---
if ! command -v tailscale >/dev/null 2>&1; then
  echo "Installing Tailscale..."
  curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled 2>/dev/null || true
# memory guardrail for tailscaled (drop-in; the vendor package owns the base unit)
if systemctl list-unit-files tailscaled.service >/dev/null 2>&1; then
  install -d /etc/systemd/system/tailscaled.service.d
  install -m 644 "$REPO/deploy/tailscaled-memory.conf" /etc/systemd/system/tailscaled.service.d/memory.conf
  systemctl daemon-reload
  systemctl try-restart tailscaled 2>/dev/null || true
fi

cat <<EOF

Installed. Next steps:
  1. sudo reboot            # apply the UART / Bluetooth change
  2. sudo $REPO/.venv/bin/pm25-setup   # guided sensor configuration + live test
  3. sudo tailscale up      # join your tailnet (opens a login link)
  4. open http://<pi-ip>:8080
EOF
