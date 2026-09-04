"""Stateful one-shot alerts for AQI and monitor health."""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import time
from collections.abc import Callable

import requests

from . import aqi, db
from .config import Config, load_config

log = logging.getLogger("pm25.alerts")

Sender = Callable[[dict], None]


def _current_aqi(conn) -> int | None:
    latest = conn.execute(
        "SELECT COALESCE(pm2_5_corr, pm2_5) AS pm2_5, pm10 FROM readings_raw ORDER BY ts DESC LIMIT 1"
    ).fetchone()
    if latest is None:
        return None
    hourly = conn.execute(
        "SELECT COALESCE(pm2_5_corr, pm2_5) AS pm2_5, pm10 FROM readings_hourly ORDER BY ts_hour DESC LIMIT 12"
    ).fetchall()
    pm25 = aqi.nowcast(list(reversed([row["pm2_5"] for row in hourly]))) or latest["pm2_5"]
    pm10 = aqi.nowcast(list(reversed([row["pm10"] for row in hourly]))) or latest["pm10"]
    return max(aqi.aqi("pm2_5", pm25) or 0, aqi.aqi("pm10", pm10) or 0)


def _state(conn, kind: str):
    conn.execute("INSERT OR IGNORE INTO alert_state (kind) VALUES (?)", (kind,))
    return conn.execute("SELECT * FROM alert_state WHERE kind = ?", (kind,)).fetchone()


def _evaluate(
    conn,
    *,
    kind: str,
    failing: bool,
    value: float | None,
    required_runs: int,
    cooldown_s: int,
    now: int,
    message: str,
    recovery_message: str,
) -> tuple[dict | None, bool, int]:
    state = _state(conn, kind)
    breach_count = state["breach_count"] + 1 if failing else 0
    active = bool(state["active"])
    event = None
    if failing and breach_count >= required_runs:
        should_send = not active or now - state["last_sent_ts"] >= cooldown_s
        active = True
        if should_send:
            event = {"event": kind, "active": True, "message": message, "value": value}
    elif not failing and active:
        active = False
        event = {"event": kind, "active": False, "message": recovery_message, "value": value}
    return event, active, breach_count


def run_once(cfg: Config, *, now: int | None = None, sender: Sender | None = None) -> bool:
    if not cfg.alerts.enabled:
        return True
    if not cfg.alerts.webhook_url and sender is None:
        log.error("alerts enabled but webhook_url is empty")
        return False

    current_time = int(time.time()) if now is None else now
    conn = db.connect(cfg.storage.db_path)
    db.init_db(conn)
    current_aqi = _current_aqi(conn)
    last_ts = conn.execute("SELECT max(ts) FROM readings_raw").fetchone()[0]
    sync = conn.execute("SELECT * FROM sync_state WHERE id = 1").fetchone()
    free_mb = shutil.disk_usage(os.path.dirname(cfg.storage.db_path) or ".").free / 1e6

    aqi_state = _state(conn, "aqi_high")
    aqi_failing = current_aqi is not None and (
        current_aqi > cfg.alerts.recovery_aqi if aqi_state["active"] else current_aqi >= cfg.alerts.threshold_aqi
    )
    conditions = [
        (
            "aqi_high",
            aqi_failing,
            current_aqi,
            cfg.alerts.consecutive_runs,
            f"AQI is {current_aqi}, above the configured threshold of {cfg.alerts.threshold_aqi}.",
            f"AQI recovered to {current_aqi}.",
        ),
        (
            "sensor_stale",
            last_ts is not None and current_time - last_ts > cfg.alerts.stale_after_s,
            current_time - last_ts if last_ts else None,
            1,
            "The particulate sensor has stopped producing fresh readings.",
            "Particulate readings are fresh again.",
        ),
        (
            "sync_delayed",
            bool(cfg.sync.enabled and sync and (sync["last_error"] or (sync["last_success_ts"] and current_time - sync["last_success_ts"] > cfg.alerts.sync_lag_s))),
            sync["backlog_rows"] if sync else 0,
            1,
            "Offload is delayed or failing.",
            "Offload is healthy again.",
        ),
        (
            "disk_low",
            free_mb < cfg.alerts.disk_free_mb,
            round(free_mb, 1),
            1,
            f"Free disk space is below {cfg.alerts.disk_free_mb} MB.",
            "Free disk space recovered.",
        ),
    ]

    pending: list[tuple[str, dict, bool, int, float | None]] = []
    for kind, failing, value, required_runs, message, recovery_message in conditions:
        event, active, breach_count = _evaluate(
            conn,
            kind=kind,
            failing=failing,
            value=value,
            required_runs=required_runs,
            cooldown_s=cfg.alerts.cooldown_s,
            now=current_time,
            message=message,
            recovery_message=recovery_message,
        )
        if event:
            event.update({"source": "pm25-monitor", "sensor_id": cfg.sync.sensor_id, "ts": current_time})
            pending.append((kind, event, active, breach_count, value))
        else:
            conn.execute(
                "UPDATE alert_state SET active = ?, breach_count = ?, last_value = ? WHERE kind = ?",
                (active, breach_count, value, kind),
            )
    conn.commit()

    if sender is None:
        token = os.environ.get(cfg.alerts.token_env, "") if cfg.alerts.token_env else ""

        def sender(payload: dict) -> None:
            headers = {"Authorization": f"Bearer {token}"} if token else {}
            response = requests.post(
                cfg.alerts.webhook_url,
                json=payload,
                headers=headers,
                timeout=cfg.alerts.request_timeout_s,
            )
            response.raise_for_status()

    try:
        for kind, event, active, breach_count, value in pending:
            sender(event)
            conn.execute(
                "UPDATE alert_state SET active = ?, breach_count = ?, last_sent_ts = ?, last_value = ?, last_error = '' WHERE kind = ?",
                (active, breach_count, current_time, value, kind),
            )
        conn.commit()
    except Exception as exc:
        log.error("alert delivery failed: %s", exc)
        conn.execute("UPDATE alert_state SET last_error = ? WHERE kind = ?", (str(exc)[:500], kind))
        conn.commit()
        conn.close()
        return False
    conn.close()
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    parser = argparse.ArgumentParser(description="Evaluate PM2.5 and monitor health alerts")
    parser.add_argument("--config", default="/etc/pm25/config.toml")
    args = parser.parse_args()
    if not run_once(load_config(args.config)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()