"""Heuristic PM event + source detection.

Flags contiguous PM2.5 excursions above a robust baseline and labels each by particle-size
signature and time-of-day. This is *indicative* pattern-matching, not calibrated source
apportionment — the fine fraction (PM2.5/PM10) and hour are weak proxies for source.
"""
from __future__ import annotations

import sqlite3
import time
from statistics import median

from . import aqi as aqilib
from .config import Config

SOURCES = {
    "wildfire_smoke": "Wildfire / regional smoke",
    "cooking_or_local": "Local combustion (e.g. cooking / bonfire)",
    "traffic_or_dust": "Traffic or coarse dust",
    "unclassified": "Elevated PM (source unclear)",
}


def _coalesce(row: sqlite3.Row) -> float | None:
    return row["pm2_5_corr"] if row["pm2_5_corr"] is not None else row["pm2_5"]


def _fine_fraction(pm2_5: float | None, pm10: float | None) -> float | None:
    if pm2_5 is None or not pm10 or pm10 <= 0:
        return None
    return min(1.0, pm2_5 / pm10)


def _classify_run(run: list[sqlite3.Row], offset: int, now_ts: int, gap: int) -> dict | None:
    values = [_coalesce(r) for r in run if _coalesce(r) is not None]
    if not values:
        return None
    peak = max(values)
    start, end = run[0]["ts"], run[-1]["ts"]
    duration = max(0, end - start)
    fractions = [f for f in (_fine_fraction(_coalesce(r), r["pm10"]) for r in run) if f is not None]
    fine = median(fractions) if fractions else None
    mid_hour = int(time.strftime("%H", time.gmtime((start + end) // 2 + offset)))

    if fine is not None and fine >= 0.7 and duration >= 3600 and peak >= 55:
        source, confidence = "wildfire_smoke", 0.7
    elif fine is not None and fine >= 0.6 and duration < 3600 and mid_hour in (17, 18, 19, 20, 21):
        source, confidence = "cooking_or_local", 0.55
    elif fine is not None and fine < 0.5 and mid_hour in (7, 8, 9, 16, 17, 18, 19):
        source, confidence = "traffic_or_dust", 0.5
    else:
        source, confidence = "unclassified", 0.35

    return {
        "start": start,
        "end": end,
        "duration_s": duration,
        "peak_pm2_5": round(peak, 1),
        "peak_aqi": aqilib.aqi("pm2_5", peak) or 0,
        "fine_fraction": round(fine, 2) if fine is not None else None,
        "hour_local": mid_hour,
        "source": source,
        "label": SOURCES[source],
        "confidence": confidence,
        "ongoing": now_ts - end <= gap,
    }


def classify_events(conn: sqlite3.Connection, cfg: Config, hours: int = 24) -> list[dict]:
    now_ts = int(time.time())
    offset = round(cfg.dashboard.tz_offset_hours * 3600)
    period = max(1, cfg.sensor.period_s if cfg.sensor.mode == "duty_cycle" else cfg.sensor.sample_interval_s)
    rows = conn.execute(
        "SELECT ts, pm2_5, pm2_5_corr, pm10 FROM readings_raw WHERE ts >= ? ORDER BY ts",
        (now_ts - hours * 3600,),
    ).fetchall()
    values = [v for v in (_coalesce(r) for r in rows) if v is not None]
    if len(values) < 5:
        return []
    baseline = median(values)
    threshold = baseline * 1.5 + 8  # excursion = well above the robust baseline
    gap = max(2 * period, 600)

    runs: list[list[sqlite3.Row]] = []
    current: list[sqlite3.Row] = []
    for r in rows:
        v = _coalesce(r)
        if v is not None and v >= threshold:
            current.append(r)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)

    events = []
    for run in runs:
        if len(run) < 2:  # ignore single-sample blips
            continue
        event = _classify_run(run, offset, now_ts, gap)
        if event is not None:
            events.append(event)
    events.sort(key=lambda e: e["peak_aqi"], reverse=True)
    return events
