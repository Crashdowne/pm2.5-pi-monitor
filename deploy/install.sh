#!/usr/bin/env bash
# Install the PM2.5 monitor on a Raspberry Pi running DietPi. Run with: sudo deploy/install.sh
set -euo pipefail

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Please run as root: sudo deploy/install.sh"; exit 1; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "Repo: $REPO"

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
systemctl daemon-reload
systemctl enable --now pm25-reader.service pm25-web.service pm25-sync.timer pm25-alert.timer

cat <<EOF

Installed. Next steps:
  1. sudo reboot            # apply the UART / Bluetooth change
  2. sudo tailscale up      # join your tailnet
  3. open http://<pi-ip>:8080
EOF
