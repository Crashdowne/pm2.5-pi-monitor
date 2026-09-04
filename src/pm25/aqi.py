"""US EPA Air Quality Index for PM2.5 and PM10.

PM2.5 breakpoints use the revision effective May 2024. Current-conditions AQI uses the
EPA NowCast (a variance-weighted average of recent hourly values); daily AQI uses a plain
24-hour mean.
"""
from __future__ import annotations

from math import floor

# (C_low, C_high, I_low, I_high) - concentration in ug/m3, index unitless.
_PM25 = [
    (0.0, 9.0, 0, 50),
    (9.1, 35.4, 51, 100),
    (35.5, 55.4, 101, 150),
    (55.5, 125.4, 151, 200),
    (125.5, 225.4, 201, 300),
    (225.5, 500.4, 301, 500),
]
_PM10 = [
    (0, 54, 0, 50),
    (55, 154, 51, 100),
    (155, 254, 101, 150),
    (255, 354, 151, 200),
    (355, 424, 201, 300),
    (425, 604, 301, 500),
]

# (I_high, label, color)
_CATEGORIES = [
    (50, "Good", "#00e400"),
    (100, "Moderate", "#ffff00"),
    (150, "Unhealthy for Sensitive Groups", "#ff7e00"),
    (200, "Unhealthy", "#ff0000"),
    (300, "Very Unhealthy", "#8f3f97"),
    (500, "Hazardous", "#7e0023"),
]


def _truncate(c: float, pollutant: str) -> float:
    """EPA truncation: PM2.5 to 0.1 ug/m3, PM10 to whole ug/m3, before lookup."""
    if pollutant == "pm2_5":
        return floor(c * 10) / 10.0
    return float(floor(c))


def aqi(pollutant: str, c: float | None) -> int | None:
    if c is None:
        return None
    c = _truncate(max(0.0, c), pollutant)
    table = _PM25 if pollutant == "pm2_5" else _PM10
    for c_low, c_high, i_low, i_high in table:
        if c <= c_high:
            c = max(c, c_low)
            return round((i_high - i_low) / (c_high - c_low) * (c - c_low) + i_low)
    return 500  # above the highest breakpoint


def category(a: int | None) -> dict:
    if a is None:
        return {"label": "Unknown", "color": "#9ca3af"}
    for i_high, label, color in _CATEGORIES:
        if a <= i_high:
            return {"label": label, "color": color}
    return {"label": "Hazardous", "color": "#7e0023"}


def nowcast(hourly_values: list[float | None]) -> float | None:
    """EPA NowCast from recent hourly concentrations (oldest first, most-recent last)."""
    recent = [v for v in reversed(hourly_values) if v is not None][:12]
    if len(recent) < 2:
        return None
    c_min, c_max = min(recent), max(recent)
    if c_max == 0:
        return 0.0
    weight = max(0.5, 1.0 - (c_max - c_min) / c_max)
    num = sum(c * weight**i for i, c in enumerate(recent))
    den = sum(weight**i for i in range(len(recent)))
    return num / den if den else None


def correct_pm25(pm_cf1: float | None, rh: float | None) -> float | None:
    """EPA/Barkjohn US-wide humidity correction for PMS5003-class sensors.

    Input is the CF=1 (standard) PM2.5 channel; ``rh`` is relative humidity %.
    """
    if pm_cf1 is None or rh is None:
        return None
    return round(max(0.0, 0.524 * pm_cf1 - 0.0862 * rh + 5.75), 1)
