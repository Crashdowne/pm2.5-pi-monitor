#!/usr/bin/env bash
# Push an update to a PM2.5 monitor over Tailscale and apply it. Runs on your dev machine, not the device.
#
#   deploy/ota-push.sh [options] HOST
#
#   HOST              the device's Tailscale name (MagicDNS) or 100.x address
#   --ref REF         commit/branch/tag to deploy (default: HEAD)
#   --wheels          also build an aarch64 wheelhouse and copy it over (needed when dependencies changed,
#                     because the locked-down device cannot reach PyPI)
#   --stage-only      push the code but do not apply it; apply later from the dashboard or with
#                     `sudo /opt/pm25/deploy/update.sh --apply-staged`
#   --user USER       SSH user (default: root; allow it in the tailnet's Tailscale SSH policy)
#   --path DIR        repo path on the device (default: /opt/pm25)
#
# Everything travels over the tailnet: git over SSH to refs/ota/incoming, the wheelhouse over the same
# SSH session. The device needs no internet access.
set -euo pipefail

REF="HEAD"
WHEELS=0
APPLY=1
SSH_USER="root"
DEVICE_REPO="/opt/pm25"
HOST=""
while [[ $# -gt 0 ]]; do
	case "$1" in
		--ref) REF="${2:?--ref needs a value}"; shift 2 ;;
		--wheels) WHEELS=1; shift ;;
		--stage-only) APPLY=0; shift ;;
		--user) SSH_USER="${2:?--user needs a value}"; shift 2 ;;
		--path) DEVICE_REPO="${2:?--path needs a value}"; shift 2 ;;
		-h | --help) sed -n '2,18p' "$0"; exit 0 ;;
		-*) echo "unknown option: $1" >&2; exit 2 ;;
		*) HOST="$1"; shift ;;
	esac
done
[[ -n "$HOST" ]] || { echo "usage: deploy/ota-push.sh [--wheels] [--ref REF] [--stage-only] HOST" >&2; exit 2; }

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
TARGET="${SSH_USER}@${HOST}"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=15)
remote() { "${SSH[@]}" "$TARGET" "$@"; }

SHA="$(git rev-parse --verify "$REF^{commit}")"
if [[ "$REF" == "HEAD" ]] && ! git diff --quiet HEAD; then
	echo "warning: uncommitted changes are NOT included; only commit ${SHA:0:7} is pushed." >&2
fi

echo "Checking $HOST over Tailscale..."
remote "test -d '$DEVICE_REPO/.git'" || { echo "No git checkout at $DEVICE_REPO on $HOST." >&2; exit 1; }

if [[ "$WHEELS" == 1 ]]; then
	command -v uv >/dev/null 2>&1 || { echo "--wheels needs uv on this machine (https://docs.astral.sh/uv/)" >&2; exit 1; }
	PYVER="$(remote "'$DEVICE_REPO/.venv/bin/python' -c 'import sys; print(\"%d.%d\" % sys.version_info[:2])'")"
	BOARD="$(remote "bash -c 'source $DEVICE_REPO/deploy/board.sh && detect_board'")"
	OTA_DIR="$(remote "'$DEVICE_REPO/.venv/bin/python' -c 'from pm25.config import load_config; print(load_config(\"/etc/pm25/config.toml\").update.state_dir)'" 2>/dev/null || echo /var/lib/pm25/ota)"
	echo "Building wheelhouse for CPython $PYVER aarch64, extra '$BOARD'..."
	WORK="$(mktemp -d)"
	trap 'rm -rf "$WORK"' EXIT
	git show "$SHA:pyproject.toml" > "$WORK/pyproject.toml"
	uv pip compile "$WORK/pyproject.toml" --extra "$BOARD" --python-version "$PYVER" \
		--python-platform aarch64-unknown-linux-gnu --quiet --no-header -o "$WORK/requirements.txt"
	PLATFORMS=()
	for p in manylinux2014_aarch64 manylinux_2_17_aarch64 manylinux_2_28_aarch64 manylinux_2_34_aarch64 linux_aarch64; do
		PLATFORMS+=(--platform "$p")
	done
	PIPDL=(uvx --quiet pip download --quiet --dest "$WORK/wheels" --only-binary=:all:
		"${PLATFORMS[@]}" --python-version "$PYVER" --implementation cp)
	"${PIPDL[@]}" --no-deps -r "$WORK/requirements.txt"
	# Build backend for the editable install of the app itself.
	"${PIPDL[@]}" hatchling
	echo "Copying $(find "$WORK/wheels" -name '*.whl' | wc -l) wheels to $HOST:$OTA_DIR/wheels..."
	tar -C "$WORK/wheels" -cf - . | remote "install -d -m 755 '$OTA_DIR/wheels' && rm -f '$OTA_DIR'/wheels/*.whl && tar -C '$OTA_DIR/wheels' -xf - && chown -R root:root '$OTA_DIR/wheels'"
fi

echo "Pushing ${SHA:0:7} to $HOST:$DEVICE_REPO (refs/ota/incoming)..."
git push --quiet --force "ssh://$TARGET$DEVICE_REPO" "$SHA:refs/ota/incoming"

if [[ "$APPLY" == 1 ]]; then
	echo "Applying on $HOST..."
	remote "'$DEVICE_REPO/deploy/update.sh' --apply-staged"
else
	echo "Staged. Apply from the dashboard (Settings > Update) or: ssh $TARGET $DEVICE_REPO/deploy/update.sh --apply-staged"
fi
