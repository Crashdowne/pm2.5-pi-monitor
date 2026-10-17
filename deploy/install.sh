#!/usr/bin/env bash
# Install the PM2.5 monitor on DietPi (Raspberry Pi or Radxa ZERO 3W). Run with: sudo deploy/install.sh
# The board is auto-detected; override with PM25_BOARD=pi or PM25_BOARD=radxa.
#
# Optional environment (all off by default; see docs/OTA.md):
#   TS_AUTHKEY=tskey-...   join the tailnet unattended (or put the key in /etc/pm25/tailscale-authkey)
#   TS_HOSTNAME=pm25       tailnet machine name (default: pm25)
#   PM25_TS_HTTPS=1        serve the dashboard at https://<host>.<tailnet>.ts.net via `tailscale serve`
#   PM25_LOCKDOWN=1        install the egress firewall: only Tailscale and the local network are reachable
set -euo pipefail

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Please run as root: sudo deploy/install.sh"; exit 1; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "Repo: $REPO"

# shellcheck source=deploy/board.sh
source "$REPO/deploy/board.sh"
# shellcheck source=deploy/common.sh
source "$REPO/deploy/common.sh"
BOARD="$(detect_board)"
echo "Board: $BOARD"

# --- base OS packages (DietPi minimal ships without git; iw disables Wi-Fi power save) ---
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  EXTRA_PKGS=""
  [[ "$BOARD" == "radxa" ]] && EXTRA_PKGS="i2c-tools gpiod"
  apt-get update -y || echo "warning: apt-get update failed; continuing with installed packages"
  # shellcheck disable=SC2086
  apt-get install -y --no-install-recommends git ca-certificates curl iw nftables $EXTRA_PKGS ||
    echo "warning: could not install one or more base packages"
fi

# --- preflight: warn if a dependency would fall back to a slow on-device source build ---
ARCH="$(uname -m)"
if [[ "$ARCH" != "aarch64" && "$ARCH" != "armv7l" ]]; then
  echo "warning: unexpected architecture '$ARCH' (expected aarch64 on a 64-bit DietPi image)"
fi
if [[ "$BOARD" == "pi" && "$ARCH" == "aarch64" ]] && command -v dpkg >/dev/null 2>&1; then
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
if [[ ! -f /etc/pm25/config.toml ]]; then
  install -o root -g pm25-data -m 640 "$REPO/config.example.toml" /etc/pm25/config.toml
  [[ "$BOARD" == "radxa" ]] && apply_radxa_defaults /etc/pm25/config.toml
fi
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
( cd "$REPO" && "$UV" sync --extra "$BOARD" )
PYTHON="$REPO/.venv/bin/python"
OTA_DIR="$(pm25_config_value "$PYTHON" 'c.update.state_dir' /var/lib/pm25/ota)"

# --- create the complete application schema before services start ---
"$PYTHON" -c 'from pm25 import db; from pm25.config import load_config; cfg = load_config("/etc/pm25/config.toml"); conn = db.connect(cfg.storage.db_path); db.init_db(conn); conn.close()'
chown -R pm25-reader:pm25-data /var/lib/pm25
chmod -R g+rwX /var/lib/pm25
# OTA state: root-owned, pm25-web may only drop an update request (re-applied after the chown above).
pm25_prepare_ota "$OTA_DIR"

# --- prebuilt dashboard: the web service serves aqi-worker/web/dist when present (no Node on the Pi) ---
if [[ -f "$REPO/aqi-worker/web/dist/index.html" ]]; then
  echo "Dashboard: serving the prebuilt React app from aqi-worker/web/dist"
else
  echo "warning: aqi-worker/web/dist not found; serving the lightweight fallback dashboard."
  echo "         Build on a dev machine: 'npm --prefix aqi-worker/web run build', then commit dist/."
fi

if [[ "$BOARD" == "pi" ]]; then
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
else
  # Radxa overlay names vary by image, so print instructions instead of editing dietpiEnv.txt.
  systemctl disable --now serial-getty@ttyS4.service 2>/dev/null || true
  print_radxa_overlay_help
fi
grep -q '^i2c-dev' /etc/modules 2>/dev/null || echo 'i2c-dev' >> /etc/modules

# --- systemd units ---
pm25_install_units "$REPO" "$PYTHON" "$HARDWARE_GROUPS" "$OTA_DIR"
systemctl daemon-reload
systemctl enable --now pm25-reader.service pm25-web.service pm25-sync.timer pm25-wifi-powersave.service
if "$PYTHON" -c 'from pm25.config import load_config; raise SystemExit(not load_config("/etc/pm25/config.toml").alerts.enabled)'; then
  systemctl enable --now pm25-alert.timer
else
  systemctl disable --now pm25-alert.timer
fi
# OTA: dashboard-triggered updates (pm25-update.path) and the optional nightly pull (pm25-autoupdate.timer)
pm25_enable_ota_units "$PYTHON"

# --- spare the SD card: keep the systemd journal in RAM (database writes still go to disk) ---
install -d /etc/systemd/journald.conf.d
install -m 644 "$REPO/deploy/journald-pm25.conf" /etc/systemd/journald.conf.d/pm25.conf
systemctl restart systemd-journald 2>/dev/null || true

# --- Tailscale: install the client + service; it carries all OTA updates and off-device data ---
if ! command -v tailscale >/dev/null 2>&1; then
  echo "Installing Tailscale..."
  curl -fsSL https://tailscale.com/install.sh | sh
fi
systemctl enable --now tailscaled 2>/dev/null || true
# memory guardrail + firewall ordering for tailscaled (drop-ins; the vendor package owns the base unit)
pm25_install_tailscaled_dropins "$REPO"
systemctl daemon-reload
systemctl try-restart tailscaled 2>/dev/null || true
# Optional unattended join. The key is passed via a root-only file and never echoed.
TS_HOSTNAME="${TS_HOSTNAME:-pm25}"
TS_JOINED=0
if tailscale status >/dev/null 2>&1; then
  TS_JOINED=1
else
  KEYFILE=""
  if [[ -n "${TS_AUTHKEY:-}" ]]; then
    KEYFILE="$(mktemp)"
    chmod 600 "$KEYFILE"
    printf '%s' "$TS_AUTHKEY" > "$KEYFILE"
  elif [[ -s /etc/pm25/tailscale-authkey ]]; then
    KEYFILE=/etc/pm25/tailscale-authkey
  fi
  if [[ -n "$KEYFILE" ]]; then
    echo "Joining the tailnet as '$TS_HOSTNAME' (Tailscale SSH enabled for OTA pushes)..."
    if tailscale up --auth-key="file:$KEYFILE" --ssh --hostname="$TS_HOSTNAME"; then
      TS_JOINED=1
    else
      echo "warning: tailscale up failed; join later with: sudo tailscale up --ssh"
    fi
    # One-shot keys are useless after a join; remove both copies.
    shred -u "$KEYFILE" 2>/dev/null || rm -f "$KEYFILE"
  fi
fi

WEB_PORT="$(pm25_config_value "$PYTHON" 'c.web.port' 8080)"
if [[ "${PM25_TS_HTTPS:-0}" == 1 ]]; then
  if [[ "$TS_JOINED" == 1 ]]; then
    # tailscaled obtains and renews the Let's Encrypt cert itself; nothing else needs internet access.
    tailscale serve --bg --https=443 "http://127.0.0.1:$WEB_PORT" ||
      echo "warning: tailscale serve failed; enable MagicDNS + HTTPS certificates in the tailnet admin console"
  else
    echo "note: PM25_TS_HTTPS=1 needs a joined tailnet; after 'tailscale up' run:"
    echo "      sudo tailscale serve --bg --https=443 http://127.0.0.1:$WEB_PORT"
  fi
fi

# --- optional egress lockdown (last, so the downloads above still work) ---
if [[ "${PM25_LOCKDOWN:-0}" == 1 ]]; then
  if [[ ! -f /etc/pm25/firewall.env ]]; then
    install -o root -g root -m 644 "$REPO/deploy/firewall.env.example" /etc/pm25/firewall.env
  fi
  systemctl enable pm25-firewall.service >/dev/null 2>&1
  if /usr/local/sbin/pm25-firewall apply; then
    echo "Egress firewall active: only Tailscale and the local network are reachable."
  else
    echo "warning: firewall rules failed to load; see: sudo pm25-firewall print"
  fi
fi

cat <<EOF

Installed. Next steps:
  1. sudo reboot            # apply the UART / I2C changes (Radxa: after editing the overlays above)
  2. sudo $REPO/.venv/bin/pm25-setup   # guided sensor configuration + live test
  3. sudo tailscale up --ssh           # join your tailnet if not already joined (Tailscale SSH enables OTA pushes)
  4. open http://<device-ip>:$WEB_PORT  (or https://$TS_HOSTNAME.<tailnet>.ts.net with PM25_TS_HTTPS=1)

Updates (over Tailscale; see docs/OTA.md):
  - from your dev machine:   deploy/ota-push.sh [--wheels] $TS_HOSTNAME
  - on the device:           sudo $REPO/deploy/update.sh
  - from the dashboard:      needs the token in /etc/pm25/update.env (sudo cat /etc/pm25/update.env)
  - egress lockdown:         sudo pm25-firewall status | open 15 | apply
EOF
