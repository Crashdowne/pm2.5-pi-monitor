#!/bin/bash
# PM2.5 monitor first-boot bootstrap for DietPi (Raspberry Pi Zero 2 W or Radxa ZERO 3W).
#
# Copy this file to the boot partition as Automation_Custom_Script.sh (and, recommended,
# Automation_Custom_PreScript.sh next to it) and set AUTO_SETUP_CUSTOM_SCRIPT_EXEC=1 in
# dietpi.txt. DietPi runs it once, as root, at the end of its first-run setup. The script:
#
#   1. installs Tailscale and joins your tailnet (Tailscale SSH on), before anything else, so
#      the device is reachable for rescue even if a later step fails;
#   2. gets the app source, trying in order:
#        a. a drop-in installer   pm25-installer.sh   (runs instead of steps 2-3)
#        b. a drop-in bundle      pm25.bundle         (from deploy/serve-source.sh --bundle-only)
#        c. SOURCE_URL            a git bundle served from your dev machine over the tailnet
#        d. REPO_URL              a git clone over the internet (empty = disabled)
#      Drop-ins are read from /boot or /boot/firmware, so they only work on images whose boot
#      partition is FAT (Raspberry Pi). Radxa images import only DietPi's own files.
#   3. runs deploy/install.sh (HTTPS via tailscale serve, egress lockdown).
#
# It installs itself as /usr/local/sbin/pm25-bootstrap with a systemd timer that retries every
# 15 minutes until step 3 succeeds, so a dev machine that is offline at first boot is fine.
# Automation_Custom_PreScript.sh runs `<this script> --persist` early in the first boot, so the
# timer exists (and later installs Tailscale and the app) even if DietPi's first run fails.
# Log: /var/lib/pm25/bootstrap.log, copied to the boot partition as pm25-bootstrap.log.
# Full guide: docs/SETUP.md.
set -u
PERSIST_ONLY=0
[ "${1:-}" = "--persist" ] && PERSIST_ONLY=1

# --- EDIT THESE ------------------------------------------------------------------------------
TS_AUTHKEY=""         # tskey-auth-... (one-off, pre-approved, tagged). Moved off /boot on first run.
TS_HOSTNAME="pm25"    # tailnet machine name -> https://pm25.<tailnet>.ts.net
TS_HTTPS=1            # 1 = serve the dashboard over HTTPS with `tailscale serve`
LOCKDOWN=1            # 1 = block all internet egress except Tailscale, DNS, and NTP after install
BOARD=""              # "pi" or "radxa"; empty = auto-detect

SOURCE_URL=""         # e.g. https://devbox.<tailnet>.ts.net:8443/pm25.bundle (printed by serve-source.sh)
SOURCE_SHA256=""      # optional: bundle checksum (printed by serve-source.sh); a mismatch is refused
REPO_URL=""           # optional internet fallback, e.g. https://github.com/<you>/pm2.5-pi-monitor.git
REF=""                # optional tag/commit for REPO_URL
BRANCH="main"         # local branch for OTA fast-forwards
TARGET="/opt/pm25"
# ---------------------------------------------------------------------------------------------

SELF_PATH=/usr/local/sbin/pm25-bootstrap
CONF=/etc/pm25/bootstrap.env
STATE=/var/lib/pm25
DONE="$STATE/bootstrap.done"
LOG="$STATE/bootstrap.log"
KEYFILE=/etc/pm25/tailscale-authkey

[ "$(id -u)" -eq 0 ] || { echo "run as root" >&2; exit 1; }
# Settings saved by the first run win over the (now blanked) inline values in this copy.
# shellcheck disable=SC1090
[ -f "$CONF" ] && . "$CONF"

BOOT_DIRS=""
for d in /boot/firmware /boot; do [ -d "$d" ] && BOOT_DIRS="$BOOT_DIRS $d"; done
# First match of a drop-in file across the boot partition candidates.
dropin() {
	local d
	for d in $BOOT_DIRS; do [ -s "$d/$1" ] && { echo "$d/$1"; return 0; }; done
	return 1
}

install -d -m 755 "$STATE" /etc/pm25
exec 9>/run/pm25-bootstrap.lock
flock -n 9 || { echo "pm25-bootstrap is already running"; exit 0; }
exec >>"$LOG" 2>&1
echo "=== pm25-bootstrap $(date -Is) ${1:-} ==="
save_log() {
	local d
	for d in $BOOT_DIRS; do cp -f "$LOG" "$d/pm25-bootstrap.log" 2>/dev/null || true; done
}
trap save_log EXIT

log() { echo "[pm25-bootstrap] $*"; }

# DietPi runs us once; the systemd service sets PM25_BOOTSTRAP_SERVICE=1 and wants a real exit code.
finish() {
	local rc=$1
	[ "$rc" -eq 0 ] || log "not finished (rc=$rc); the pm25-bootstrap.timer retries every 15 minutes"
	[ "${PM25_BOOTSTRAP_SERVICE:-0}" = 1 ] && exit "$rc"
	exit 0
}

[ -f "$DONE" ] && { log "already installed ($DONE exists)"; finish 0; }

persist() {
	[ "$(readlink -f "${BASH_SOURCE[0]}")" = "$SELF_PATH" ] && return 0
	log "installing $SELF_PATH and the retry timer"
	if [ -n "$TS_AUTHKEY" ] && [ ! -s "$KEYFILE" ]; then
		(umask 077; printf '%s' "$TS_AUTHKEY" >"$KEYFILE")
	fi
	local kf
	if kf="$(dropin pm25-tailscale-authkey)" && [ ! -s "$KEYFILE" ]; then
		(umask 077; tr -d '\r\n' <"$kf" >"$KEYFILE")
	fi
	for d in $BOOT_DIRS; do rm -f "$d/pm25-tailscale-authkey"; done
	local src
	src="$(readlink -f "${BASH_SOURCE[0]}")"
	install -m 700 "$src" "$SELF_PATH"
	# The auth key must not linger on the world-readable FAT partition or in any saved copy.
	for f in "$SELF_PATH" "$src" /boot/Automation_Custom_Script.sh /boot/firmware/Automation_Custom_Script.sh; do
		[ -f "$f" ] && sed -i 's/^TS_AUTHKEY=.*/TS_AUTHKEY=""/' "$f"
	done
	{
		for v in TS_HOSTNAME TS_HTTPS LOCKDOWN BOARD SOURCE_URL SOURCE_SHA256 REPO_URL REF BRANCH TARGET; do
			printf '%s=%q\n' "$v" "${!v}"
		done
	} >"$CONF"
	chmod 600 "$CONF"
	cat >/etc/systemd/system/pm25-bootstrap.service <<EOF
[Unit]
Description=PM2.5 monitor first-boot bootstrap (retries until installed)
Wants=network-online.target
After=network-online.target tailscaled.service
ConditionPathExists=!$DONE

[Service]
Type=oneshot
Environment=PM25_BOOTSTRAP_SERVICE=1
ExecStart=$SELF_PATH
TimeoutStartSec=2h
EOF
	cat >/etc/systemd/system/pm25-bootstrap.timer <<EOF
[Unit]
Description=Retry the PM2.5 monitor bootstrap until it succeeds
ConditionPathExists=!$DONE

[Timer]
OnBootSec=3min
OnUnitInactiveSec=15min

[Install]
WantedBy=timers.target
EOF
	systemctl daemon-reload
	# A run that fires while this one still holds the lock exits at once; the next is 15 min later.
	systemctl enable --now pm25-bootstrap.timer >/dev/null 2>&1 || true
}

ensure_packages() {
	local missing=""
	for p in git curl ca-certificates; do
		dpkg -s "$p" >/dev/null 2>&1 || missing="$missing $p"
	done
	[ -z "$missing" ] && return 0
	log "installing$missing"
	export DEBIAN_FRONTEND=noninteractive
	apt-get -o DPkg::Lock::Timeout=600 update -y &&
		apt-get -o DPkg::Lock::Timeout=600 install -y --no-install-recommends $missing
}

# The retry service must not race DietPi's own first-run apt work; give up waiting after an hour
# in case the first run is stuck.
firstrun_pending() {
	[ "${PM25_BOOTSTRAP_SERVICE:-0}" = 1 ] || return 1
	[ -f /boot/dietpi/.install_stage ] || return 1
	[ "$(cat /boot/dietpi/.install_stage 2>/dev/null)" = 2 ] && return 1
	[ "$(cut -d. -f1 /proc/uptime)" -lt 3600 ]
}

ts_running() { tailscale status >/dev/null 2>&1; }

ensure_tailscale() {
	if ! command -v tailscale >/dev/null 2>&1; then
		log "installing Tailscale"
		curl -fsSL https://tailscale.com/install.sh | sh || return 1
	fi
	systemctl enable --now tailscaled >/dev/null 2>&1 || true
	ts_running && { log "tailnet: already joined"; return 0; }
	if [ -s "$KEYFILE" ]; then
		log "joining the tailnet as '$TS_HOSTNAME' (Tailscale SSH on)"
		if tailscale up --auth-key="file:$KEYFILE" --ssh --hostname="$TS_HOSTNAME" --timeout=120s; then
			shred -u "$KEYFILE" 2>/dev/null || rm -f "$KEYFILE"
		else
			log "tailscale up failed; check the key (expired? already used?)"
			return 1
		fi
	else
		log "no auth key: join by hand over SSH with 'sudo tailscale up --ssh --hostname $TS_HOSTNAME'"
		return 1
	fi
	for _ in $(seq 30); do ts_running && return 0; sleep 2; done
	return 1
}

# Clone a git bundle into $TARGET on branch $BRANCH.
repo_from_bundle() {
	local bundle=$1 tmp="$TARGET.new" ref
	rm -rf "$tmp"
	git init -q -b "$BRANCH" "$tmp" || return 1
	if ! git -C "$tmp" bundle verify -q "$bundle" >/dev/null 2>&1; then
		log "invalid git bundle: $bundle"
		rm -rf "$tmp"
		return 1
	fi
	ref="$(git bundle list-heads "$bundle" | awk '$2 != "HEAD" {print $2; exit}')"
	[ -n "$ref" ] || ref=HEAD
	git -C "$tmp" fetch -q "$bundle" "$ref" && git -C "$tmp" checkout -q -B "$BRANCH" FETCH_HEAD || {
		rm -rf "$tmp"
		return 1
	}
	[ -n "$REPO_URL" ] && git -C "$tmp" remote add origin "$REPO_URL"
	place_repo "$tmp"
}

place_repo() {
	[ -e "$TARGET" ] && mv "$TARGET" "$TARGET.old.$(date +%s)"
	mv "$1" "$TARGET"
	log "source ready: $(git -C "$TARGET" log -1 --format='%h %s')"
}

fetch_source() {
	[ -d "$TARGET/.git" ] && git -C "$TARGET" rev-parse -q --verify HEAD >/dev/null && {
		log "source already present at $TARGET"
		return 0
	}
	local b
	if b="$(dropin pm25.bundle)"; then
		log "using drop-in bundle $b"
		repo_from_bundle "$b" && return 0
	fi
	if [ -n "$SOURCE_URL" ]; then
		log "downloading $SOURCE_URL over the tailnet"
		local dl="$STATE/pm25.bundle"
		if curl -fsSL --retry 5 --retry-delay 10 --retry-all-errors --connect-timeout 20 -o "$dl" "$SOURCE_URL"; then
			if [ -n "$SOURCE_SHA256" ] && ! echo "$SOURCE_SHA256  $dl" | sha256sum -c --quiet -; then
				log "checksum mismatch for $SOURCE_URL; refusing (re-run serve-source.sh and update SOURCE_SHA256)"
			elif repo_from_bundle "$dl"; then
				rm -f "$dl"
				return 0
			fi
		else
			log "could not download $SOURCE_URL (is serve-source.sh running, and does the ACL allow tag:pm25 to reach it?)"
		fi
		rm -f "$dl"
	fi
	if [ -n "$REPO_URL" ]; then
		log "cloning $REPO_URL"
		local tmp="$TARGET.new"
		rm -rf "$tmp"
		if git clone -q --depth 1 ${REF:+--branch "$REF"} "$REPO_URL" "$tmp" 2>/dev/null ||
			{ rm -rf "$tmp"; git clone -q "$REPO_URL" "$tmp" && { [ -z "$REF" ] || git -C "$tmp" checkout -q "$REF"; }; }; then
			git -C "$tmp" checkout -q -B "$BRANCH"
			place_repo "$tmp"
			return 0
		fi
		rm -rf "$tmp"
	fi
	log "no source available yet (drop-in bundle, SOURCE_URL, REPO_URL)"
	return 1
}

mark_done() {
	touch "$DONE"
	systemctl disable pm25-bootstrap.timer >/dev/null 2>&1 || true
	log "done. Dashboard: https://$TS_HOSTNAME.<tailnet>.ts.net (or http://<device-ip>:8080 on the LAN)"
}

main() {
	persist
	[ "$PERSIST_ONLY" = 1 ] && { log "retry timer installed; the bootstrap itself runs later"; return 0; }
	if firstrun_pending; then
		log "DietPi first-run setup still in progress; waiting"
		return 1
	fi
	ensure_packages || log "warning: apt install failed; continuing with what is installed"
	# Tailscale comes first so the device is reachable even if the app install fails.
	ensure_tailscale || log "warning: not on the tailnet yet"

	local inst
	if inst="$(dropin pm25-installer.sh)"; then
		log "running drop-in installer $inst"
		cp -f "$inst" "$STATE/pm25-installer.sh"
		if PM25_TARGET="$TARGET" PM25_BRANCH="$BRANCH" PM25_BOARD="$BOARD" PM25_BOOT_DIR="$(dirname "$inst")" \
			TS_HOSTNAME="$TS_HOSTNAME" PM25_TS_HTTPS="$TS_HTTPS" PM25_LOCKDOWN="$LOCKDOWN" \
			bash "$STATE/pm25-installer.sh"; then
			mv -f "$inst" "$inst.done" 2>/dev/null || true
			mark_done
			return 0
		fi
		log "drop-in installer failed"
		return 1
	fi

	fetch_source || return 1
	log "running $TARGET/deploy/install.sh"
	PM25_BOARD="$BOARD" TS_AUTHKEY="" TS_HOSTNAME="$TS_HOSTNAME" PM25_TS_HTTPS="$TS_HTTPS" \
		PM25_LOCKDOWN="$LOCKDOWN" bash "$TARGET/deploy/install.sh" || { log "install.sh failed"; return 1; }
	mark_done
}

main
finish $?
