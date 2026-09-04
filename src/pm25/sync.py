"""Offload raw readings to the server over Tailscale, then prune locally.

Push is incremental (by watermark). Pruning enforces the local retention window and,
when sync is enabled, never deletes rows the server has not yet acknowledged.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import shutil
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from . import db
from .config import Config, load_config

log = logging.getLogger("pm25.sync")


def _session(cfg: Config) -> requests.Session:
    retry = Retry(
        total=cfg.sync.retry_total,
        connect=cfg.sync.retry_total,
        read=cfg.sync.retry_total,
        status=cfg.sync.retry_total,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(("GET", "POST")),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("http://", HTTPAdapter(max_retries=retry))
    session.mount("https://", HTTPAdapter(max_retries=retry))
    return session


def _push(cfg: Config, conn, session: requests.Session) -> None:
    token = os.environ.get(cfg.sync.token_env, "")
    if not token:
        raise RuntimeError(f"no sync token in env {cfg.sync.token_env}")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/x-ndjson",
        "X-PM25-Sensor-ID": cfg.sync.sensor_id,
        "X-PM25-Sample-Period": str(cfg.sensor.period_s if cfg.sensor.mode == "duty_cycle" else 60),
    }
    url = cfg.sync.server_url.rstrip("/") + "/ingest"
    while True:
        rows = conn.execute(
            "SELECT * FROM readings_raw WHERE synced = 0 ORDER BY ts LIMIT ?", (cfg.sync.batch_size,)
        ).fetchall()
        if not rows:
            break
        payload: bytes = "\n".join(json.dumps(dict(r)) for r in rows).encode("utf-8")
        if cfg.sync.gzip_enabled:
            payload = gzip.compress(payload, compresslevel=3)
            headers["Content-Encoding"] = "gzip"
        resp = session.post(url, data=payload, headers=headers, timeout=30)
        resp.raise_for_status()
        ack = resp.json()
        if int(ack.get("received", -1)) != len(rows) or int(ack.get("max_ts", 0)) < rows[-1]["ts"]:
            raise RuntimeError("server did not acknowledge the complete ingest batch")
        timestamps = [row["ts"] for row in rows]
        last = max(timestamps)
        conn.executemany("UPDATE readings_raw SET synced = 1 WHERE ts = ?", ((ts,) for ts in timestamps))
        conn.execute("UPDATE sync_state SET last_pushed_ts = ? WHERE id = 1", (last,))
        conn.commit()
        log.info("pushed %d rows (through ts=%d)", len(rows), last)


def _refresh_server_max(cfg: Config, conn, session: requests.Session) -> int:
    token = os.environ.get(cfg.sync.token_env, "")
    resp = session.get(
        cfg.sync.server_url.rstrip("/") + "/max_ts",
        headers={"Authorization": f"Bearer {token}", "X-PM25-Sensor-ID": cfg.sync.sensor_id},
        timeout=15,
    )
    resp.raise_for_status()
    server_max = int(resp.json().get("max_ts", 0))
    conn.execute("UPDATE sync_state SET server_max_ts = ? WHERE id = 1", (server_max,))
    conn.commit()
    return server_max


def _under_pressure(cfg: Config) -> bool:
    path = cfg.storage.db_path
    db_mb = db.database_bytes(path) / 1e6
    free_mb = shutil.disk_usage(os.path.dirname(path) or ".").free / 1e6
    return db_mb > cfg.sync.trigger_db_size_mb or free_mb < cfg.sync.trigger_disk_free_mb


def _prune(cfg: Config, conn, server_max: int) -> None:
    keep_days = cfg.sync.pressure_keep_days if _under_pressure(cfg) else cfg.storage.raw_retention_days
    cutoff = int(time.time()) - keep_days * 86400
    if cfg.sync.enabled:
        if not cfg.sync.server_url or server_max <= 0:
            raise RuntimeError("refusing to prune without a verified server watermark")
        cur = conn.execute("DELETE FROM readings_raw WHERE ts < ? AND synced = 1", (cutoff,))
    else:
        cur = conn.execute("DELETE FROM readings_raw WHERE ts < ?", (cutoff,))
    conn.commit()
    db.maintain(conn)
    if cur.rowcount:
        log.info("pruned %d raw rows older than ts=%d", cur.rowcount, cutoff)


def run_once(cfg: Config) -> bool:
    conn = db.connect(cfg.storage.db_path)
    db.init_db(conn)
    if cfg.sync.enabled and not cfg.sync.server_url:
        log.error("sync is enabled but server_url is empty; refusing to prune")
        conn.close()
        return False
    now = int(time.time())
    conn.execute("UPDATE sync_state SET last_attempt_ts = ? WHERE id = 1", (now,))
    conn.commit()
    server_max = 0
    if cfg.sync.enabled and cfg.sync.server_url:
        session = _session(cfg)
        try:
            _push(cfg, conn, session)
            server_max = _refresh_server_max(cfg, conn, session)
        except Exception as e:
            log.error("sync failed, skipping prune of unarchived data: %s", e)
            backlog = conn.execute("SELECT count(*) FROM readings_raw WHERE synced = 0").fetchone()[0]
            conn.execute(
                "UPDATE sync_state SET last_error = ?, backlog_rows = ? WHERE id = 1",
                (str(e)[:500], backlog),
            )
            conn.commit()
            conn.close()
            session.close()
            return False
        session.close()
    _prune(cfg, conn, server_max)
    backlog = conn.execute("SELECT count(*) FROM readings_raw WHERE synced = 0").fetchone()[0]
    conn.execute(
        "UPDATE sync_state SET last_success_ts = ?, last_error = '', backlog_rows = ? WHERE id = 1",
        (int(time.time()), backlog),
    )
    conn.commit()
    conn.close()
    return True


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description="Offload + prune job")
    ap.add_argument("--config", default="/etc/pm25/config.toml")
    args = ap.parse_args()
    if not run_once(load_config(args.config)):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
