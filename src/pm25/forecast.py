"""Heuristic short-term PM2.5 forecast for the dashboard.

Not machine learning and not a substitute for official forecasts (AirNow etc.): each future
hour blends the latest reading (persistence) toward the recent diurnal climatology, with a
confidence band from the hour-of-day spread. Indicative only.
"""
from __future__ import annotations

import sqlite3
import time

from . import aqi as aqilib
from .analytics import PM25
from .config import Config


def _diurnal_profile(conn: sqlite3.Connection, offset: int, days: int = 14) -> dict[int, tuple[float, float]]:
    """hour-of-day -> (mean PM2.5, stddev) over the recent window, from the hourly rollup."""
    rows = conn.execute(
        "SELECT CAST(strftime('%H', ts_hour + ?, 'unixepoch') AS INTEGER) AS hour, "
        f"avg({PM25}) AS mean, avg(({PM25}) * ({PM25})) AS meansq, count(*) AS n "
        "FROM readings_hourly WHERE ts_hour >= ? GROUP BY hour",
        (offset, int(time.time()) - days * 86400),
    ).fetchall()
    profile: dict[int, tuple[float, float]] = {}
    for r in rows:
        if r["mean"] is None:
            continue
        variance = max(0.0, (r["meansq"] or 0.0) - r["mean"] ** 2)
        profile[r["hour"]] = (r["mean"], variance**0.5)
    return profile


def forecast(conn: sqlite3.Connection, cfg: Config, hours: int = 6) -> list[dict]:
    offset = round(cfg.dashboard.tz_offset_hours * 3600)
    latest = conn.execute("SELECT * FROM readings_raw ORDER BY ts DESC LIMIT 1").fetchone()
    if latest is None:
        return []
    last_val = latest["pm2_5_corr"] if latest["pm2_5_corr"] is not None else latest["pm2_5"]
    if last_val is None:
        return []
    profile = _diurnal_profile(conn, offset)
    base_ts = latest["ts"]
    out = []
    for h in range(1, hours + 1):
        target = base_ts + h * 3600
        hod = int(time.strftime("%H", time.gmtime(target + offset)))
        clim_mean, clim_std = profile.get(hod, (last_val, 0.0))
        weight = 0.8**h  # persistence decays toward climatology with horizon
        pred = weight * last_val + (1 - weight) * clim_mean
        spread = clim_std * (1 + 0.15 * h)  # band widens further out
        out.append(
            {
                "t": target,
                "pm2_5": round(pred, 1),
                "pm2_5_lo": round(max(0.0, pred - spread), 1),
                "pm2_5_hi": round(pred + spread, 1),
                "aqi": aqilib.aqi("pm2_5", pred) or 0,
                "basis": "diurnal+persistence",
            }
        )
    return out
