"""Typed configuration loaded from a TOML file (stdlib ``tomllib``, Python 3.11+)."""
from __future__ import annotations

import tomllib
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SHT31Config:
    enabled: bool = False
    address: int = 0x44


@dataclass(frozen=True)
class SensorConfig:
    device: str = "/dev/ttyAMA0"
    baud: int = 9600
    mode: str = "duty_cycle"  # "duty_cycle" | "continuous"
    period_s: int = 180
    warmup_s: int = 30
    sample_s: int = 8
    sample_interval_s: int = 60  # continuous mode: seconds per averaged/written sample
    reset_after_failures: int = 3
    reopen_after_failures: int = 6
    use_atmospheric: bool = True
    # int = BCM pin (gpiozero, Raspberry Pi); "gpiochipN:line" = libgpiod line (Radxa etc.)
    pin_enable: int | str | None = 22
    pin_reset: int | str | None = 27
    i2c_bus: int = 1  # SHT31 I2C bus: 1 on the Raspberry Pi, 3 on the Radxa ZERO 3W
    sht31: SHT31Config = field(default_factory=SHT31Config)


@dataclass(frozen=True)
class StorageConfig:
    db_path: str = "/var/lib/pm25/pm25.db"
    raw_retention_days: int = 30
    commit_interval_s: int = 0  # 0 = commit every sample; >0 batches SD writes (Tier 1 write-min)


@dataclass(frozen=True)
class WebConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    threads: int = 2  # waitress worker threads (raise on the Pi 4; each SSE client holds one)


@dataclass(frozen=True)
class SyncConfig:
    enabled: bool = False
    server_url: str = ""
    token_env: str = "PM25_SYNC_TOKEN"
    sensor_id: str = "default"
    batch_size: int = 200  # <=329 keeps one aqi-worker ingest under the free-tier D1 query cap
    pressure_keep_days: int = 7
    trigger_db_size_mb: int = 200
    trigger_disk_free_mb: int = 200
    retry_total: int = 3
    gzip_enabled: bool = True
    access_client_id_env: str = ""
    access_client_secret_env: str = ""


@dataclass(frozen=True)
class AlertConfig:
    enabled: bool = False
    webhook_url: str = ""
    token_env: str = ""
    threshold_aqi: int = 101
    recovery_aqi: int = 80
    consecutive_runs: int = 2
    cooldown_s: int = 3600
    stale_after_s: int = 600
    sync_lag_s: int = 28800
    disk_free_mb: int = 150
    request_timeout_s: int = 10


@dataclass(frozen=True)
class DashboardConfig:
    """Presentation + mask-advisor settings for the local React dashboard."""

    site_title: str = "Air Quality"
    temp_unit: str = "c"  # "c" | "f"
    tz_offset_hours: float = 0.0
    live_interval_s: int = 10  # SSE live-tile refresh cadence (seconds)
    mask_sensitivity: str = "asthma"  # general | asthma | very_sensitive
    # Per-threshold NowCast-AQI overrides; negative means "use the sensitivity preset".
    mask_carry_aqi: int = -1
    mask_recommended_aqi: int = -1
    mask_strong_aqi: int = -1
    mask_indoors_aqi: int = -1


@dataclass(frozen=True)
class UpdateConfig:
    """Over-the-air updates, delivered over Tailscale (see deploy/ota-push.sh)."""

    allow_web_trigger: bool = True  # dashboard/API may request an update (tailnet + token only)
    token_env: str = "PM25_UPDATE_TOKEN"  # env var holding the bearer token for POST /api/update
    state_dir: str = "/var/lib/pm25/ota"  # request + status files shared with pm25-update.service
    remote: str = ""  # git remote for "pull" updates; empty = origin (must be reachable over the tailnet)
    branch: str = "main"
    auto_pull: bool = False  # pm25-autoupdate.timer pulls nightly when true


@dataclass(frozen=True)
class Config:
    sensor: SensorConfig
    storage: StorageConfig
    web: WebConfig
    sync: SyncConfig
    alerts: AlertConfig = field(default_factory=AlertConfig)
    dashboard: DashboardConfig = field(default_factory=DashboardConfig)
    update: UpdateConfig = field(default_factory=UpdateConfig)


_SENSOR_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _validate_config(cfg: Config) -> None:
    sensor = cfg.sensor
    if sensor.mode not in ("duty_cycle", "continuous"):
        raise ValueError("sensor.mode must be 'duty_cycle' or 'continuous'")
    if sensor.period_s < 1 or sensor.warmup_s < 0 or sensor.sample_s < 1:
        raise ValueError("sensor timing values must be positive")
    if sensor.sample_interval_s < 1:
        raise ValueError("sensor.sample_interval_s must be at least 1")
    if sensor.mode == "duty_cycle" and sensor.period_s <= sensor.warmup_s + sensor.sample_s:
        raise ValueError("sensor.period_s must exceed warmup_s + sample_s in duty_cycle mode")
    if sensor.reset_after_failures < 0 or sensor.reopen_after_failures < 0:
        raise ValueError("sensor recovery thresholds cannot be negative")
    if sensor.i2c_bus < 0:
        raise ValueError("sensor.i2c_bus cannot be negative")
    if cfg.storage.raw_retention_days < 1:
        raise ValueError("storage.raw_retention_days must be at least 1")
    if cfg.storage.commit_interval_s < 0:
        raise ValueError("storage.commit_interval_s cannot be negative")
    if not 1 <= cfg.web.port <= 65535:
        raise ValueError("web.port must be between 1 and 65535")
    if not 1 <= cfg.web.threads <= 64:
        raise ValueError("web.threads must be between 1 and 64")

    sync = cfg.sync
    if not _SENSOR_ID_RE.fullmatch(sync.sensor_id):
        raise ValueError("sync.sensor_id must contain only letters, digits, '.', '_' or '-'")
    if not 1 <= sync.batch_size <= 1000:
        raise ValueError("sync.batch_size must be between 1 and 1000")
    if not 1 <= sync.pressure_keep_days <= cfg.storage.raw_retention_days:
        raise ValueError("sync.pressure_keep_days must be between 1 and raw_retention_days")
    if sync.trigger_db_size_mb < 0 or sync.trigger_disk_free_mb < 0 or not 0 <= sync.retry_total <= 10:
        raise ValueError("sync thresholds must be non-negative and retry_total cannot exceed 10")

    alerts = cfg.alerts
    if not 0 <= alerts.recovery_aqi <= alerts.threshold_aqi <= 500:
        raise ValueError("alert AQI thresholds must satisfy 0 <= recovery <= threshold <= 500")
    if alerts.consecutive_runs < 1 or alerts.cooldown_s < 0:
        raise ValueError("alert consecutive_runs must be positive and cooldown_s cannot be negative")
    if alerts.stale_after_s < 1 or alerts.sync_lag_s < 1 or alerts.disk_free_mb < 0 or alerts.request_timeout_s < 1:
        raise ValueError("alert health thresholds must be positive")

    dash = cfg.dashboard
    if dash.temp_unit not in ("c", "f"):
        raise ValueError("dashboard.temp_unit must be 'c' or 'f'")
    if not -14.0 <= dash.tz_offset_hours <= 14.0:
        raise ValueError("dashboard.tz_offset_hours must be between -14 and 14")
    if dash.live_interval_s < 1:
        raise ValueError("dashboard.live_interval_s must be at least 1")

    upd = cfg.update
    if not _GIT_NAME_RE.fullmatch(upd.branch):
        raise ValueError("update.branch must be a plain branch name")
    if upd.remote and not _GIT_REMOTE_RE.fullmatch(upd.remote):
        raise ValueError("update.remote must be a remote name or an ssh/https/git URL without spaces")
    if not upd.state_dir.startswith("/"):
        raise ValueError("update.state_dir must be an absolute path")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", upd.token_env):
        raise ValueError("update.token_env must be an environment variable name")


_GIT_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,99}$")
_GIT_REMOTE_RE = re.compile(r"^[A-Za-z0-9@:/._~+-]{1,255}$")


GPIOD_PIN_RE = re.compile(r"^(?:/dev/)?gpiochip\d+:\d+$")


def parse_pin(value: object) -> int | str | None:
    """Parse a control-pin setting.

    TOML has no null, so a negative number (or an empty string) means 'not wired'.
    An int is a BCM pin driven via gpiozero; a "gpiochipN:line" string is a
    libgpiod line (used on non-Pi boards such as the Radxa ZERO 3W).
    """
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if GPIOD_PIN_RE.fullmatch(text):
            return text
        try:
            n = int(text)
        except ValueError:
            raise ValueError(
                f"invalid pin {value!r}: use a BCM number, -1, or 'gpiochipN:line'"
            ) from None
    else:
        n = int(value)  # type: ignore[arg-type]
    return None if n < 0 else n


_pin = parse_pin


def load_config(path: str | Path) -> Config:
    data: dict = {}
    p = Path(path)
    if p.exists():
        with open(p, "rb") as f:
            data = tomllib.load(f)

    s = data.get("sensor", {})
    h = s.get("sht31", {})
    sensor = SensorConfig(
        device=s.get("device", "/dev/ttyAMA0"),
        baud=int(s.get("baud", 9600)),
        mode=s.get("mode", "duty_cycle"),
        period_s=int(s.get("period_s", 180)),
        warmup_s=int(s.get("warmup_s", 30)),
        sample_s=int(s.get("sample_s", 8)),
        sample_interval_s=int(s.get("sample_interval_s", 60)),
        reset_after_failures=int(s.get("reset_after_failures", 3)),
        reopen_after_failures=int(s.get("reopen_after_failures", 6)),
        use_atmospheric=bool(s.get("use_atmospheric", True)),
        pin_enable=_pin(s.get("pin_enable", 22)),
        pin_reset=_pin(s.get("pin_reset", 27)),
        i2c_bus=int(s.get("i2c_bus", 1)),
        sht31=SHT31Config(
            enabled=bool(h.get("enabled", False)),
            address=int(h.get("address", 0x44)),
        ),
    )

    st = data.get("storage", {})
    storage = StorageConfig(
        db_path=st.get("db_path", "/var/lib/pm25/pm25.db"),
        raw_retention_days=int(st.get("raw_retention_days", 30)),
        commit_interval_s=int(st.get("commit_interval_s", 0)),
    )

    w = data.get("web", {})
    web = WebConfig(host=w.get("host", "0.0.0.0"), port=int(w.get("port", 8080)), threads=int(w.get("threads", 2)))

    y = data.get("sync", {})
    sync = SyncConfig(
        enabled=bool(y.get("enabled", False)),
        server_url=y.get("server_url", ""),
        token_env=y.get("token_env", "PM25_SYNC_TOKEN"),
        sensor_id=str(y.get("sensor_id", "default")),
        batch_size=int(y.get("batch_size", 200)),
        pressure_keep_days=int(y.get("pressure_keep_days", 7)),
        trigger_db_size_mb=int(y.get("trigger_db_size_mb", 200)),
        trigger_disk_free_mb=int(y.get("trigger_disk_free_mb", 200)),
        retry_total=int(y.get("retry_total", 3)),
        gzip_enabled=bool(y.get("gzip_enabled", True)),
        access_client_id_env=str(y.get("access_client_id_env", "")),
        access_client_secret_env=str(y.get("access_client_secret_env", "")),
    )

    a = data.get("alerts", {})
    alerts = AlertConfig(
        enabled=bool(a.get("enabled", False)),
        webhook_url=str(a.get("webhook_url", "")),
        token_env=str(a.get("token_env", "")),
        threshold_aqi=int(a.get("threshold_aqi", 101)),
        recovery_aqi=int(a.get("recovery_aqi", 80)),
        consecutive_runs=int(a.get("consecutive_runs", 2)),
        cooldown_s=int(a.get("cooldown_s", 3600)),
        stale_after_s=int(a.get("stale_after_s", 600)),
        sync_lag_s=int(a.get("sync_lag_s", 28800)),
        disk_free_mb=int(a.get("disk_free_mb", 150)),
        request_timeout_s=int(a.get("request_timeout_s", 10)),
    )

    dash = data.get("dashboard", {})
    dashboard = DashboardConfig(
        site_title=str(dash.get("site_title", "Air Quality")),
        temp_unit=str(dash.get("temp_unit", "c")).lower(),
        tz_offset_hours=float(dash.get("tz_offset_hours", 0.0)),
        live_interval_s=int(dash.get("live_interval_s", 10)),
        mask_sensitivity=str(dash.get("mask_sensitivity", "asthma")).lower(),
        mask_carry_aqi=int(dash.get("mask_carry_aqi", -1)),
        mask_recommended_aqi=int(dash.get("mask_recommended_aqi", -1)),
        mask_strong_aqi=int(dash.get("mask_strong_aqi", -1)),
        mask_indoors_aqi=int(dash.get("mask_indoors_aqi", -1)),
    )

    u = data.get("update", {})
    update = UpdateConfig(
        allow_web_trigger=bool(u.get("allow_web_trigger", True)),
        token_env=str(u.get("token_env", "PM25_UPDATE_TOKEN")),
        state_dir=str(u.get("state_dir", "/var/lib/pm25/ota")),
        remote=str(u.get("remote", "")),
        branch=str(u.get("branch", "main")),
        auto_pull=bool(u.get("auto_pull", False)),
    )

    cfg = Config(
        sensor=sensor, storage=storage, web=web, sync=sync, alerts=alerts, dashboard=dashboard, update=update
    )
    _validate_config(cfg)
    return cfg
