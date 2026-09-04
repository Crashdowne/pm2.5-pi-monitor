"""Asthma-aware mask advisor.

Maps a NowCast AQI value to a mask recommendation using configurable, conservative
thresholds. Informational only -- not medical advice.
"""
from __future__ import annotations

DISCLAIMER = "Informational only — not medical advice. Follow your asthma action plan."

# Ascending severity.
LEVELS = ["none", "carry", "recommended", "strong", "indoors"]

# level -> (short label, action text, color)
_META: dict[str, tuple[str, str, str]] = {
    "none": (
        "No mask needed",
        "Air is good — enjoy normal activity.",
        "#2ea043",
    ),
    "carry": (
        "Carry one",
        "Carry an N95 and watch for symptoms; ease heavy or prolonged exertion.",
        "#d4a72c",
    ),
    "recommended": (
        "Mask recommended",
        "Wear a well-fitted N95/KN95 for outdoor exertion and limit prolonged activity.",
        "#fb8500",
    ),
    "strong": (
        "Strongly recommended",
        "Wear an N95/KN95 outdoors, keep trips short, and keep your reliever inhaler handy.",
        "#e5484d",
    ),
    "indoors": (
        "Stay indoors",
        "Stay inside with HEPA filtration; wear an N95/KN95 only if you must go out.",
        "#a371f7",
    ),
}


def severity(level: str) -> int:
    try:
        return LEVELS.index(level)
    except ValueError:
        return 0


def level_for(aqi_value: int | None, thresholds: tuple[int, int, int, int]) -> str:
    """Return the mask level for an AQI value given (carry, recommended, strong, indoors)."""
    if aqi_value is None:
        return "none"
    carry, recommended, strong, indoors = thresholds
    if aqi_value >= indoors:
        return "indoors"
    if aqi_value >= strong:
        return "strong"
    if aqi_value >= recommended:
        return "recommended"
    if aqi_value >= carry:
        return "carry"
    return "none"


def describe(level: str) -> dict:
    """Static metadata for a mask level (label, action text, color, mask type)."""
    label, action, color = _META[level]
    mask_type = "N95 optional" if level in ("none", "carry") else "Well-fitted N95 or KN95"
    return {
        "level": level,
        "severity": severity(level),
        "label": label,
        "action": action,
        "color": color,
        "mask_type": mask_type,
    }


def all_levels() -> list[dict]:
    return [describe(level) for level in LEVELS]


def recommend(
    aqi_value: int | None,
    thresholds: tuple[int, int, int, int],
    *,
    dominant: str | None = None,
    trend: str | None = None,
) -> dict:
    """Full recommendation payload for the given AQI value."""
    payload = describe(level_for(aqi_value, thresholds))
    payload.update(
        {
            "aqi": aqi_value,
            "dominant": dominant,
            "trend": trend,
            "disclaimer": DISCLAIMER,
        }
    )
    return payload
