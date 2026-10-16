#!/usr/bin/env bash
# Update in place (OTA). Run as root; normally started by pm25-update.service / pm25-autoupdate.service.
#
#   sudo deploy/update.sh                  same as --pull
#   sudo deploy/update.sh --pull           fetch [update].branch from [update].remote (default: origin), then apply
#   sudo deploy/update.sh --apply-staged   apply refs/ota/incoming, pushed over Tailscale by deploy/ota-push.sh
#   sudo deploy/update.sh --request        apply the request the dashboard dropped in [update].state_dir
#   sudo deploy/update.sh --reinstall      re-render units / permissions at the current commit, no git changes
#
# Updates are fast-forward only. Phase 1 (this file, old version) fetches and merges; phase 2 re-execs the
# *new* deploy/update.sh with --finish so new units and steps take effect. Any failure in phase 2 resets
# the checkout to the previous commit and restarts the services on it. Status is written to
# <state_dir>/status.json and <state_dir>/version.json for the dashboard.
set -Eeuo pipefail

[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "Please run as root: sudo deploy/update.sh"; exit 1; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
# shellcheck source=deploy/board.sh
source "$REPO/deploy/board.sh"
# shellcheck source=deploy/common.sh
source "$REPO/deploy/common.sh"

export PATH="/root/.local/bin:/usr/local/bin:$PATH"
PYTHON="$REPO/.venv/bin/python"
OTA_DIR="$(pm25_config_value "$PYTHON" 'c.update.state_dir' /var/lib/pm25/ota)"
MODE="pull"
SOURCE="${PM25_UPDATE_SOURCE:-cli}"
FROM=""
STEP="starting"
case "${1:-}" in
	"" | --pull) MODE="pull" ;;
	--apply-staged) MODE="apply_staged" ;;
	--reinstall) MODE="reinstall" ;;
	--request) MODE="request" ;;
	--finish) MODE="${2:?}"; SOURCE="${3:?}"; FROM="${4:?}" ;;
	-h | --help) sed -n '2,14p' "$0"; exit 0 ;;
	*) echo "unknown option: $1 (see --help)" >&2; exit 2 ;;
esac

install -d -o root -g pm25-data -m 2770 "$OTA_DIR" 2>/dev/null || install -d -m 2770 "$OTA_DIR"

fail() {
	local msg="$1"
	echo "update failed: $msg" >&2
	pm25_write_status "$OTA_DIR" failed "$MODE" "$SOURCE" "$msg" "${FROM:-}" "$(git rev-parse HEAD 2>/dev/null || true)"
	exit 1
}

# ---------------------------------------------------------------- phase 1: fetch + fast-forward
if [[ "${1:-}" != "--finish" ]]; then
	# One update at a time; the lock fd is inherited across the exec into phase 2.
	if [[ "${PM25_UPDATE_LOCKED:-0}" != 1 ]]; then
		exec 9>/run/pm25-update.lock
		flock -n 9 || { echo "another update is already running" >&2; exit 0; }
	fi

	if [[ "$MODE" == "request" ]]; then
		SOURCE="web"
		[[ -f "$OTA_DIR/request" ]] || { echo "no pending request"; exit 0; }
		MODE="$("$PYTHON" -c 'import json,sys; print(json.load(open(sys.argv[1])).get("action",""))' "$OTA_DIR/request" 2>/dev/null || true)"
		rm -f "$OTA_DIR/request"
		[[ "$MODE" == "pull" || "$MODE" == "apply_staged" ]] || fail "invalid request action"
	fi
	[[ "$MODE" == "apply_staged" && "$SOURCE" == "cli" ]] && SOURCE="push"

	FROM="$(git rev-parse HEAD)"
	pm25_write_status "$OTA_DIR" running "$MODE" "$SOURCE" "fetching" "$FROM" ""

	case "$MODE" in
		pull)
			REMOTE="$(pm25_config_value "$PYTHON" 'c.update.remote' '')"
			BRANCH="$(pm25_config_value "$PYTHON" 'c.update.branch' main)"
			git fetch --quiet "${REMOTE:-origin}" "$BRANCH" || fail "git fetch from ${REMOTE:-origin} failed (is it reachable over Tailscale?)"
			TARGET="$(git rev-parse FETCH_HEAD)"
			;;
		apply_staged)
			TARGET="$(git rev-parse --verify --quiet 'refs/ota/incoming^{commit}')" || fail "nothing staged: push with deploy/ota-push.sh first"
			;;
		reinstall)
			TARGET="$FROM"
			;;
	esac

	if [[ "$TARGET" != "$FROM" ]]; then
		git merge-base --is-ancestor "$FROM" "$TARGET" || fail "${TARGET:0:7} is not a fast-forward of ${FROM:0:7}; refusing"
		# uv may have created an untracked uv.lock; never let it block a merge that adds one.
		if [[ -f uv.lock ]] && git cat-file -e "$TARGET:uv.lock" 2>/dev/null && ! git ls-files --error-unmatch uv.lock >/dev/null 2>&1; then rm -f uv.lock; fi
		git merge --ff-only --quiet "$TARGET" || fail "fast-forward merge failed (local changes in $REPO?)"
	elif [[ "$MODE" != "reinstall" ]]; then
		pm25_write_status "$OTA_DIR" success "$MODE" "$SOURCE" "already up to date" "$FROM" "$FROM"
		pm25_write_version "$REPO" "$OTA_DIR" "$SOURCE"
		[[ "$MODE" == "apply_staged" ]] && git update-ref -d refs/ota/incoming
		echo "Already up to date at ${FROM:0:7}"
		exit 0
	fi
	[[ "$MODE" == "apply_staged" ]] && git update-ref -d refs/ota/incoming
	exec "$REPO/deploy/update.sh" --finish "$MODE" "$SOURCE" "$FROM"
fi

# ---------------------------------------------------------------- phase 2: install at the new commit
TO="$(git rev-parse HEAD)"
ROLLING_BACK=0

rollback() {
	local rc=$? msg="failed while $STEP"
	trap - ERR
	set +e
	[[ "$ROLLING_BACK" == 1 ]] && exit "$rc"
	ROLLING_BACK=1
	echo "update failed ($msg)" >&2
	if [[ "$FROM" == "$TO" ]]; then
		pm25_write_status "$OTA_DIR" failed "$MODE" "$SOURCE" "$msg" "$FROM" "$TO"
		exit 1
	fi
	echo "rolling back to ${FROM:0:7}" >&2
	pm25_write_status "$OTA_DIR" running "$MODE" "$SOURCE" "rolling back: $msg" "$FROM" "$TO"
	git reset --hard --quiet "$FROM"
	if grep -q -- '--reinstall' "$REPO/deploy/update.sh"; then
		# Re-render units and dependencies with the previous release's own installer.
		PM25_UPDATE_LOCKED=1 PM25_UPDATE_SOURCE=rollback "$REPO/deploy/update.sh" --reinstall
	else
		git diff --quiet "$FROM" "$TO" -- pyproject.toml uv.lock || sync_deps
		systemctl daemon-reload
		systemctl restart pm25-reader.service pm25-web.service
	fi
	pm25_write_status "$OTA_DIR" failed "$MODE" "$SOURCE" "$msg; rolled back to ${FROM:0:7}" "$FROM" "$TO"
	pm25_write_version "$REPO" "$OTA_DIR" "$SOURCE"
	exit 1
}

# Dependencies come from the wheelhouse pushed by ota-push.sh (offline), so the device never needs PyPI.
sync_deps() {
	local board uv
	board="$(detect_board)"
	uv="$(command -v uv)"
	if compgen -G "$OTA_DIR/wheels/*.whl" >/dev/null; then
		# Resolve only for this device, from the pushed wheels; a universal `uv sync` lock would need
		# wheels for every platform and extra.
		"$uv" pip install --python "$REPO/.venv/bin/python" --offline --no-index \
			--find-links "$OTA_DIR/wheels" -e ".[$board]" && return 0
	fi
	"$uv" sync --extra "$board" --offline && return 0
	echo "Offline dependency install failed. Push a wheelhouse (deploy/ota-push.sh --wheels HOST)," >&2
	echo "or open egress briefly (sudo pm25-firewall open 15) and re-run sudo deploy/update.sh --reinstall." >&2
	[[ "${PM25_UPDATE_ALLOW_NETWORK:-0}" == 1 ]] || return 1
	"$uv" sync --extra "$board"
}

trap rollback ERR
pm25_write_status "$OTA_DIR" running "$MODE" "$SOURCE" "installing ${TO:0:7}" "$FROM" "$TO"

STEP="installing dependencies"
if [[ "$MODE" == "reinstall" ]] || ! git diff --quiet "$FROM" "$TO" -- pyproject.toml uv.lock; then
	sync_deps
fi
STEP="importing the new code"
"$PYTHON" -c 'import pm25.api, pm25.reader, pm25.ota' >/dev/null
STEP="installing units and permissions"

if [[ -f "$REPO/aqi-worker/web/dist/index.html" ]]; then
	echo "Dashboard: serving the prebuilt React app from aqi-worker/web/dist"
else
	echo "warning: aqi-worker/web/dist not found; serving the lightweight fallback dashboard."
fi

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
# Data files belong to the reader; the OTA dir stays root-owned so services cannot forge update status.
find /var/lib/pm25 -path "$OTA_DIR" -prune -o -exec chown pm25-reader:pm25-data {} + -exec chmod g+rwX {} +
chown root:pm25-data /etc/pm25/config.toml
chown root:pm25-secrets /etc/pm25/sync.env
chmod 640 /etc/pm25/config.toml /etc/pm25/sync.env
pm25_prepare_ota "$OTA_DIR"

pm25_install_units "$REPO" "$PYTHON" "$HARDWARE_GROUPS" "$OTA_DIR"
install -d /etc/systemd/journald.conf.d
install -m 644 "$REPO/deploy/journald-pm25.conf" /etc/systemd/journald.conf.d/pm25.conf
systemctl restart systemd-journald 2>/dev/null || true
pm25_install_tailscaled_dropins "$REPO"
systemctl daemon-reload
systemctl enable pm25-sync.timer pm25-wifi-powersave.service >/dev/null 2>&1
systemctl restart pm25-reader.service pm25-web.service pm25-sync.timer pm25-wifi-powersave.service
if "$PYTHON" -c 'from pm25.config import load_config; raise SystemExit(not load_config("/etc/pm25/config.toml").alerts.enabled)'; then
	systemctl enable pm25-alert.timer >/dev/null 2>&1
	systemctl restart pm25-alert.timer
else
	systemctl disable --now pm25-alert.timer >/dev/null 2>&1 || true
fi
pm25_enable_ota_units "$PYTHON"
if [[ -f /etc/pm25/firewall.env ]]; then
	systemctl enable pm25-firewall.service >/dev/null 2>&1
	/usr/local/sbin/pm25-firewall apply
fi

STEP="waiting for the services to become healthy"
# Health check: both services must stay up and the dashboard API must answer.
PORT="$(pm25_config_value "$PYTHON" 'c.web.port' 8080)"
healthy=0
for _ in $(seq 1 20); do
	sleep 3
	if systemctl is-active --quiet pm25-web.service && systemctl is-active --quiet pm25-reader.service &&
		curl -fsS -o /dev/null --max-time 5 "http://127.0.0.1:$PORT/api/health"; then
		healthy=1
		break
	fi
done
[[ "$healthy" == 1 ]] || false

trap - ERR
pm25_write_status "$OTA_DIR" success "$MODE" "$SOURCE" "updated to ${TO:0:7}" "$FROM" "$TO"
pm25_write_version "$REPO" "$OTA_DIR" "$SOURCE"
echo "Updated ${FROM:0:7} -> ${TO:0:7}"
