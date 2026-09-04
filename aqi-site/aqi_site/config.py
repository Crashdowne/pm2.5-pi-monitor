"""Configuration: defaults, optional TOML file, and environment overrides.

Everything is read-only with respect to the warehouse. Mask thresholds come from a
sensitivity preset (``general`` / ``asthma`` / ``very_sensitive``) that individual
keys can override.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, replace
from pathlib import Path

# Conservative, asthma-tuned by default. Values are NowCast-AQI thresholds for the
# (carry, recommended, strong, indoors) mask levels.
MASK_PRESETS: dict[str, tuple[int, int, int, int]] = {
    "general": (76, 101, 151, 301),
    "asthma": (51, 76, 101, 201),
    "very_sensitive": (26, 51, 76, 151),
}
DEFAULT_SENSITIVITY = "asthma"


@dataclass(frozen=True)
class MaskConfig:
    sensitivity: str = DEFAULT_SENSITIVITY
    carry_aqi: int = 51
    recommended_aqi: int = 76
    strong_aqi: int = 101
    indoors_aqi: int = 201

    @property
    def thresholds(self) -> tuple[int, int, int, int]:
        return (self.carry_aqi, self.recommended_aqi, self.strong_aqi, self.indoors_aqi)


@dataclass(frozen=True)
class AlertsConfig:
    enabled: bool = False
    notify_from: str = "recommended"  # mask level at/above which to notify
    ntfy_url: str = ""
    ntfy_topic: str = ""
    ntfy_token: str = ""
    webhook_url: str = ""
    min_interval_s: int = 3600
    quiet_start_hour: int = -1  # -1 disables quiet hours
    quiet_end_hour: int = -1
    poll_interval_s: int = 300


@dataclass(frozen=True)
class DisplayConfig:
    site_title: str = "Air Quality"
    tz_offset_hours: float = 0.0
    temp_unit: str = "c"  # "c" or "f"


@dataclass(frozen=True)
class Config:
    db_path: str = "/data/pm25.db"
    db_immutable: bool = False
    state_db_path: str = "/data/aqi-site-state.db"
    host: str = "127.0.0.1"
    port: int = 8080
    web_dist: str = ""  # empty -> resolved to <package>/web/dist at serve time
    default_sensor: str = ""  # empty -> most-recently-active device
    mask: MaskConfig = field(default_factory=MaskConfig)
    alerts: AlertsConfig = field(default_factory=AlertsConfig)
    display: DisplayConfig = field(default_factory=DisplayConfig)


def _mask_from(d: dict) -> MaskConfig:
    sensitivity = str(d.get("sensitivity", DEFAULT_SENSITIVITY)).lower()
    if sensitivity not in MASK_PRESETS:
        sensitivity = DEFAULT_SENSITIVITY
    carry, recommended, strong, indoors = MASK_PRESETS[sensitivity]
    return MaskConfig(
        sensitivity=sensitivity,
        carry_aqi=int(d.get("carry_aqi", carry)),
        recommended_aqi=int(d.get("recommended_aqi", recommended)),
        strong_aqi=int(d.get("strong_aqi", strong)),
        indoors_aqi=int(d.get("indoors_aqi", indoors)),
    )


def _alerts_from(d: dict) -> AlertsConfig:
    base = AlertsConfig()
    return AlertsConfig(
        enabled=bool(d.get("enabled", base.enabled)),
        notify_from=str(d.get("notify_from", base.notify_from)).lower(),
        ntfy_url=str(d.get("ntfy_url", base.ntfy_url)).rstrip("/"),
        ntfy_topic=str(d.get("ntfy_topic", base.ntfy_topic)),
        ntfy_token=str(d.get("ntfy_token", base.ntfy_token)),
        webhook_url=str(d.get("webhook_url", base.webhook_url)),
        min_interval_s=int(d.get("min_interval_s", base.min_interval_s)),
        quiet_start_hour=int(d.get("quiet_start_hour", base.quiet_start_hour)),
        quiet_end_hour=int(d.get("quiet_end_hour", base.quiet_end_hour)),
        poll_interval_s=max(30, int(d.get("poll_interval_s", base.poll_interval_s))),
    )


def _display_from(d: dict) -> DisplayConfig:
    base = DisplayConfig()
    unit = str(d.get("temp_unit", base.temp_unit)).lower()
    return DisplayConfig(
        site_title=str(d.get("site_title", base.site_title)),
        tz_offset_hours=float(d.get("tz_offset_hours", base.tz_offset_hours)),
        temp_unit="f" if unit == "f" else "c",
    )


def _from_toml(path: Path) -> Config:
    with path.open("rb") as fh:
        data = tomllib.load(fh)
    base = Config()
    server = data.get("server", {})
    return replace(
        base,
        db_path=str(server.get("db_path", base.db_path)),
        db_immutable=bool(server.get("db_immutable", base.db_immutable)),
        state_db_path=str(server.get("state_db_path", base.state_db_path)),
        host=str(server.get("host", base.host)),
        port=int(server.get("port", base.port)),
        web_dist=str(server.get("web_dist", base.web_dist)),
        default_sensor=str(server.get("default_sensor", base.default_sensor)),
        mask=_mask_from(data.get("mask", {})),
        alerts=_alerts_from(data.get("alerts", {})),
        display=_display_from(data.get("display", {})),
    )


def _env_bool(name: str, current: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return current
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _apply_env(cfg: Config) -> Config:
    return replace(
        cfg,
        db_path=os.environ.get("AQI_SITE_DB", cfg.db_path),
        db_immutable=_env_bool("AQI_SITE_DB_IMMUTABLE", cfg.db_immutable),
        state_db_path=os.environ.get("AQI_SITE_STATE_DB", cfg.state_db_path),
        host=os.environ.get("AQI_SITE_HOST", cfg.host),
        port=int(os.environ.get("AQI_SITE_PORT", cfg.port)),
        web_dist=os.environ.get("AQI_SITE_WEB_DIST", cfg.web_dist),
        default_sensor=os.environ.get("AQI_SITE_DEFAULT_SENSOR", cfg.default_sensor),
    )


def load(path: str | os.PathLike[str] | None = None) -> Config:
    """Build config from defaults, an optional TOML file, then environment overrides."""
    candidate = path or os.environ.get("AQI_SITE_CONFIG")
    cfg = Config()
    if candidate:
        toml_path = Path(candidate)
        if toml_path.is_file():
            cfg = _from_toml(toml_path)
    return _apply_env(cfg)
