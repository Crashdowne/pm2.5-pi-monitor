"""Alerting: evaluate the mask level per sensor and push to ntfy / a webhook.

The warehouse stays read-only; alert state (last level, last-fired time) and runtime
overrides live in the sidecar's own SQLite database. Firing uses hysteresis (only on
escalation or after a min interval) and honours quiet hours so it will not spam.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path

try:  # requests ships with the pm25 core deps; guard so imports never fail
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore[assignment]

from . import analytics, db, mask
from .config import AlertsConfig, Config

log = logging.getLogger("aqi_site.alerts")

_STATE_SCHEMA = (
    "CREATE TABLE IF NOT EXISTS alert_state ("
    "sensor_id TEXT PRIMARY KEY, last_level TEXT NOT NULL DEFAULT 'none', "
    "last_fired_ts INTEGER NOT NULL DEFAULT 0)",
    "CREATE TABLE IF NOT EXISTS alert_overrides ("
    "id INTEGER PRIMARY KEY CHECK (id=1), data TEXT NOT NULL)",
)

_OVERRIDE_KEYS = {
    "enabled",
    "notify_from",
    "min_interval_s",
    "quiet_start_hour",
    "quiet_end_hour",
}

_PRIORITY = {"indoors": "urgent", "strong": "high", "recommended": "default"}
_TAGS = {"indoors": "no_entry", "strong": "rotating_light", "recommended": "mask"}


def open_state(path: str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    for statement in _STATE_SCHEMA:
        conn.execute(statement)
    conn.commit()
    return conn


def get_state(conn: sqlite3.Connection, sensor_id: str) -> tuple[str, int]:
    row = conn.execute(
        "SELECT last_level, last_fired_ts FROM alert_state WHERE sensor_id=?",
        (sensor_id,),
    ).fetchone()
    if row is None:
        return "none", 0
    return row["last_level"], row["last_fired_ts"]


def set_state(conn: sqlite3.Connection, sensor_id: str, level: str, fired_ts: int) -> None:
    conn.execute(
        "INSERT INTO alert_state (sensor_id, last_level, last_fired_ts) VALUES (?, ?, ?) "
        "ON CONFLICT(sensor_id) DO UPDATE SET last_level=excluded.last_level, "
        "last_fired_ts=excluded.last_fired_ts",
        (sensor_id, level, fired_ts),
    )
    conn.commit()


def load_overrides(conn: sqlite3.Connection) -> dict:
    row = conn.execute("SELECT data FROM alert_overrides WHERE id=1").fetchone()
    if row is None:
        return {}
    try:
        data = json.loads(row["data"])
    except (json.JSONDecodeError, TypeError):
        return {}
    return {k: v for k, v in data.items() if k in _OVERRIDE_KEYS} if isinstance(data, dict) else {}


def save_overrides(conn: sqlite3.Connection, data: dict) -> dict:
    clean = {k: data[k] for k in _OVERRIDE_KEYS if k in data}
    conn.execute(
        "INSERT INTO alert_overrides (id, data) VALUES (1, ?) "
        "ON CONFLICT(id) DO UPDATE SET data=excluded.data",
        (json.dumps(clean),),
    )
    conn.commit()
    return clean


def effective_alerts(base: AlertsConfig, overrides: dict) -> AlertsConfig:
    if not overrides:
        return base
    return replace(
        base,
        enabled=bool(overrides.get("enabled", base.enabled)),
        notify_from=str(overrides.get("notify_from", base.notify_from)).lower(),
        min_interval_s=int(overrides.get("min_interval_s", base.min_interval_s)),
        quiet_start_hour=int(overrides.get("quiet_start_hour", base.quiet_start_hour)),
        quiet_end_hour=int(overrides.get("quiet_end_hour", base.quiet_end_hour)),
    )


def in_quiet_hours(now: int, cfg: AlertsConfig, offset: int = 0) -> bool:
    if cfg.quiet_start_hour < 0 or cfg.quiet_end_hour < 0:
        return False
    hour = ((now + offset) // 3600) % 24
    start, end = cfg.quiet_start_hour, cfg.quiet_end_hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def should_fire(
    prev_level: str, new_level: str, cfg: AlertsConfig, last_fired_ts: int, now: int
) -> tuple[bool, str]:
    if mask.severity(new_level) < mask.severity(cfg.notify_from):
        return False, "below-threshold"
    if mask.severity(new_level) > mask.severity(prev_level):
        return True, "escalated"
    if now - last_fired_ts >= cfg.min_interval_s:
        return True, "reminder"
    return False, "debounced"


def send_ntfy(cfg: AlertsConfig, title: str, message: str, level: str) -> bool:
    if requests is None or not cfg.ntfy_url or not cfg.ntfy_topic:
        return False
    headers = {
        "Title": title,
        "Priority": _PRIORITY.get(level, "default"),
        "Tags": _TAGS.get(level, "mask"),
    }
    if cfg.ntfy_token:
        headers["Authorization"] = f"Bearer {cfg.ntfy_token}"
    try:
        resp = requests.post(
            f"{cfg.ntfy_url}/{cfg.ntfy_topic}",
            data=message.encode("utf-8"),
            headers=headers,
            timeout=10,
        )
        return resp.ok
    except Exception as exc:  # network failures must not crash the poller
        log.warning("ntfy push failed: %s", exc)
        return False


def send_webhook(cfg: AlertsConfig, payload: dict) -> bool:
    if requests is None or not cfg.webhook_url:
        return False
    try:
        resp = requests.post(cfg.webhook_url, json=payload, timeout=10)
        return resp.ok
    except Exception as exc:
        log.warning("webhook push failed: %s", exc)
        return False


def notify(cfg: AlertsConfig, sensor_id: str, snapshot: dict) -> bool:
    reco = snapshot["mask"]
    aqi_value = snapshot["nowcast_aqi"]
    title = f"{reco['label']} — AQI {aqi_value}"
    message = f"[{sensor_id}] {reco['action']} (dominant {snapshot['dominant']})."
    payload = {
        "sensor_id": sensor_id,
        "aqi": aqi_value,
        "level": reco["level"],
        "label": reco["label"],
        "action": reco["action"],
        "ts": snapshot["ts"],
    }
    sent_ntfy = send_ntfy(cfg, title, message, reco["level"])
    sent_webhook = send_webhook(cfg, payload)
    return sent_ntfy or sent_webhook


def poll_once(config: Config, state_conn: sqlite3.Connection) -> list[dict]:
    """Evaluate every sensor once and fire alerts as needed. Returns per-sensor events."""
    cfg = effective_alerts(config.alerts, load_overrides(state_conn))
    if not cfg.enabled:
        return []
    offset = int(round(config.display.tz_offset_hours * 3600))
    now = int(time.time())
    events: list[dict] = []
    try:
        conn = db.connect(config.db_path, config.db_immutable)
    except sqlite3.OperationalError as exc:
        log.warning("alert poll skipped, warehouse unavailable: %s", exc)
        return []
    try:
        for sensor_id in db.distinct_sensors(conn):
            snapshot = analytics.current(conn, sensor_id, config.mask, offset)
            if snapshot is None:
                continue
            level = snapshot["mask"]["level"]
            prev_level, last_fired = get_state(state_conn, sensor_id)
            fire, reason = should_fire(prev_level, level, cfg, last_fired, now)
            quiet = in_quiet_hours(now, cfg, offset)
            sent = False
            if fire and not quiet:
                sent = notify(cfg, sensor_id, snapshot)
            set_state(state_conn, sensor_id, level, now if sent else last_fired)
            if fire or level != prev_level:
                events.append(
                    {
                        "sensor_id": sensor_id,
                        "level": level,
                        "prev_level": prev_level,
                        "reason": "quiet" if (fire and quiet) else reason,
                        "sent": sent,
                    }
                )
    finally:
        conn.close()
    return events


def run_poller(config: Config, stop_event: threading.Event) -> None:
    """Background loop: poll on an interval until ``stop_event`` is set."""
    state_conn = open_state(config.state_db_path)
    try:
        while not stop_event.is_set():
            try:
                poll_once(config, state_conn)
            except Exception as exc:  # keep the thread alive across unexpected errors
                log.warning("alert poll error: %s", exc)
            stop_event.wait(config.alerts.poll_interval_s)
    finally:
        state_conn.close()
