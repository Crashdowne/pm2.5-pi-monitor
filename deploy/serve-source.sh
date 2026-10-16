#!/usr/bin/env bash
# Serve this repository to new PM2.5 monitors over the tailnet, for the DietPi first-boot bootstrap.
# Runs on your dev machine (Linux, macOS, or Git Bash on Windows), not on the device.
#
#   deploy/serve-source.sh [--ref REF] [--port PORT] [--dir DIR]
#   deploy/serve-source.sh --stop [--port PORT]
#
#   --ref REF     commit/branch/tag to package (default: HEAD; uncommitted changes are not included)
#   --port PORT   HTTPS port on this machine's tailnet name (default: 8443)
#   --dir DIR     where to write pm25.bundle (default: ~/.pm25-serve)
#   --bundle-only write pm25.bundle and its checksum but do not start serving (for the SD-card drop-in)
#   --stop        stop serving on PORT
#
# It writes pm25.bundle (a single-file git repository) and serves that directory with
# `tailscale serve`, which only listens on the tailnet: the file never touches the internet.
# Put the printed SOURCE_URL and SOURCE_SHA256 into deploy/dietpi/Automation_Custom_Script.sh.
# Your tailnet policy must let tag:pm25 reach this machine on PORT (see docs/SETUP.md).
set -euo pipefail

REF="HEAD"
PORT=8443
DIR="${HOME}/.pm25-serve"
STOP=0
SERVE=1
while [[ $# -gt 0 ]]; do
	case "$1" in
		--ref) REF="${2:?--ref needs a value}"; shift 2 ;;
		--port) PORT="${2:?--port needs a value}"; shift 2 ;;
		--dir) DIR="${2:?--dir needs a value}"; shift 2 ;;
		--bundle-only) SERVE=0; shift ;;
		--stop) STOP=1; shift ;;
		-h | --help) sed -n '2,18p' "$0"; exit 0 ;;
		*) echo "unknown option: $1" >&2; exit 2 ;;
	esac
done

if [[ "$STOP" == 1 ]]; then
	tailscale serve --https="$PORT" off
	echo "Stopped serving on port $PORT."
	exit 0
fi

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
COMMIT="$(git rev-parse --verify "$REF^{commit}")"
[[ -z "$(git status --porcelain --untracked-files=no)" || "$REF" != "HEAD" ]] ||
	echo "note: you have uncommitted changes; the bundle only contains commit ${COMMIT:0:12}"

mkdir -p "$DIR"
BUNDLE="$DIR/pm25.bundle"
# A named branch inside the bundle; the device checks it out as its local 'main'.
git branch -f pm25-serve "$COMMIT" >/dev/null
git bundle create "$BUNDLE" pm25-serve 2>/dev/null
git branch -D pm25-serve >/dev/null
git bundle verify -q "$BUNDLE" >/dev/null
if command -v sha256sum >/dev/null 2>&1; then
	SHA="$(sha256sum "$BUNDLE" | awk '{print $1}')"
else
	SHA="$(shasum -a 256 "$BUNDLE" | awk '{print $1}')"
fi
echo "$SHA  pm25.bundle" >"$DIR/pm25.bundle.sha256"
echo "Bundle: $BUNDLE (commit ${COMMIT:0:12})"
echo "SOURCE_SHA256=\"$SHA\""

[[ "$SERVE" == 1 ]] || { echo "Copy pm25.bundle to the SD card's boot partition to use it as a drop-in."; exit 0; }

SERVE_DIR="$DIR"
command -v cygpath >/dev/null 2>&1 && SERVE_DIR="$(cygpath -w "$DIR")"
tailscale serve --bg --https="$PORT" "$SERVE_DIR"

NAME="$(tailscale status --json --peers=false 2>/dev/null |
	sed -n 's/.*"DNSName": *"\([^"]*\)".*/\1/p' | head -n1)"
NAME="${NAME%.}"
if [[ -n "$NAME" ]]; then
	echo "SOURCE_URL=\"https://$NAME:$PORT/pm25.bundle\""
else
	echo "SOURCE_URL=\"https://<this-machine>.<tailnet>.ts.net:$PORT/pm25.bundle\""
fi
echo "Leave this machine on and on the tailnet until the device finishes. Stop with: deploy/serve-source.sh --stop"
