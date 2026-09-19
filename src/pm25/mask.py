"""Asthma-aware mask advisor — Python port of the aqi-worker ``mask.ts`` logic.

NowCast-AQI thresholds pick a mask level; sensitivity presets can be overridden per
threshold from config. Informational only — not medical advice.
"""
from __future__ import annotations

DISCLAIMER = "Informational only — not medical advice. Follow your asthma action plan."

LEVELS = ["none", "carry", "recommended", "strong", "indoors"]

# level -> (label, action, color)
_META: dict[str, tuple[str, str, str]] = {
    "none": ("No mask needed", "Air is good — enjoy normal activity.", "#2ea043"),
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

# NowCast-AQI thresholds for (carry, recommended, strong, indoors).
PRESETS: dict[str, tuple[int, int, int, int]] = {
    "general": (76, 101, 151, 301),
    "asthma": (51, 76, 101, 201),
    "very_sensitive": (26, 51, 76, 151),
}
DEFAULT_SENSITIVITY = "asthma"


def resolve_thresholds(
    sensitivity: str, overrides: tuple[int, int, int, int]
) -> tuple[int, int, int, int]:
    """Preset thresholds for a sensitivity, with per-value overrides (negative = keep preset)."""
    base = PRESETS.get(sensitivity, PRESETS[DEFAULT_SENSITIVITY])
    return tuple(o if o >= 0 else b for o, b in zip(overrides, base))  # type: ignore[return-value]


def severity(level: str) -> int:
    return LEVELS.index(level) if level in LEVELS else 0


def level_for(aqi_value: float | None, thresholds: tuple[int, int, int, int]) -> str:
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
    aqi_value: float | None,
    thresholds: tuple[int, int, int, int],
    *,
    dominant: str | None = None,
    trend: str | None = None,
) -> dict:
    payload = describe(level_for(aqi_value, thresholds))
    payload.update({"aqi": aqi_value, "dominant": dominant, "trend": trend, "disclaimer": DISCLAIMER})
    return payload
