"""Over-the-air update requests and status, shared between the web app and pm25-update.service.

The web app runs unprivileged, so it never updates the code itself. It only drops a request
file into ``update.state_dir``; the root ``pm25-update.path`` unit sees it and runs
``deploy/update.sh``, which writes ``status.json`` and ``version.json`` back to the same
directory. Code reaches the device over Tailscale: either pushed by ``deploy/ota-push.sh``
(staged as ``refs/ota/incoming``) or pulled from a git remote that is reachable on the tailnet.
"""
from __future__ import annotations

import hmac
import ipaddress
import json
import os
import time
from pathlib import Path

from . import __version__

ACTIONS = ("pull", "apply_staged")
REQUEST_FILE = "request"
STATUS_FILE = "status.json"
VERSION_FILE = "version.json"

# Tailscale CGNAT range and ULA prefix; loopback covers requests proxied by `tailscale serve`.
_TAILNET_NETS = (ipaddress.ip_network("100.64.0.0/10"), ipaddress.ip_network("fd7a:115c:a1e0::/48"))


def package_version() -> str:
    try:
        from importlib.metadata import version

        return version("pm25-pi-monitor")
    except Exception:
        return __version__


def is_trusted_address(addr: str | None) -> bool:
    """True for loopback (incl. `tailscale serve`) and tailnet peers; LAN and public peers are refused."""
    if not addr:
        return False
    try:
        ip = ipaddress.ip_address(addr.split("%", 1)[0])
    except ValueError:
        return False
    if getattr(ip, "ipv4_mapped", None):
        ip = ip.ipv4_mapped
    return ip.is_loopback or any(ip in net for net in _TAILNET_NETS)


def token_matches(expected: str, authorization: str | None) -> bool:
    if not expected or not authorization:
        return False
    scheme, _, supplied = authorization.partition(" ")
    if scheme.lower() != "bearer":
        return False
    return hmac.compare_digest(supplied.strip().encode(), expected.encode())


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def read_status(state_dir: str | Path) -> dict:
    d = Path(state_dir)
    pending = _read_json(d / REQUEST_FILE) if (d / REQUEST_FILE).exists() else None
    return {
        "package_version": package_version(),
        "installed": _read_json(d / VERSION_FILE),
        "last_run": _read_json(d / STATUS_FILE),
        "pending_request": pending,
    }


def request_update(state_dir: str | Path, action: str, now: float | None = None) -> dict:
    """Atomically write the request file that pm25-update.path watches."""
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {', '.join(ACTIONS)}")
    d = Path(state_dir)
    target = d / REQUEST_FILE
    if target.exists():
        raise RuntimeError("an update request is already pending")
    if _read_json(d / STATUS_FILE).get("state") == "running":
        raise RuntimeError("an update is already running")
    request = {"action": action, "ts": int(now if now is not None else time.time())}
    tmp = d / f".{REQUEST_FILE}.{os.getpid()}.tmp"
    tmp.write_text(json.dumps(request), encoding="utf-8")
    os.replace(tmp, target)
    return request
