"""Interactive sensor setup wizard.

Guides the operator through configuring the PMS5003 (and optional SHT31), live-probes the
hardware to confirm wiring, writes ``config.toml``, then restarts the reader and verifies a
fresh reading lands in the database. Run on the Pi with ``sudo pm25-setup``.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from .config import Config, SHT31Config, SensorConfig, _validate_config, load_config


@dataclass
class ProbeResult:
    ok: bool
    detail: str


# --- prompt helpers ---------------------------------------------------------

def _input(prompt: str) -> str:
    try:
        return input(prompt)
    except EOFError:
        return ""


def _ask_str(label: str, default: str) -> str:
    return _input(f"{label} [{default}]: ").strip() or default


def _ask_bool(label: str, default: bool) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        resp = _input(f"{label} [{hint}]: ").strip().lower()
        if not resp:
            return default
        if resp in ("y", "yes"):
            return True
        if resp in ("n", "no"):
            return False
        print("  Please answer y or n.")


def _ask_int(label: str, default: int, lo: int | None = None, hi: int | None = None) -> int:
    while True:
        resp = _input(f"{label} [{default}]: ").strip()
        if not resp:
            return default
        try:
            value = int(resp)
        except ValueError:
            print("  Enter a whole number.")
            continue
        if lo is not None and value < lo:
            print(f"  Must be >= {lo}.")
            continue
        if hi is not None and value > hi:
            print(f"  Must be <= {hi}.")
            continue
        return value


def _ask_choice(label: str, options: list[str], default: str) -> str:
    joined = "/".join(options)
    while True:
        resp = _input(f"{label} ({joined}) [{default}]: ").strip().lower()
        if not resp:
            return default
        if resp in options:
            return resp
        print(f"  Choose one of: {joined}")


def _ask_pin(label: str, default: int | None) -> int | None:
    shown = str(default) if default is not None else "none"
    while True:
        resp = _input(f"{label} (BCM number, or 'none') [{shown}]: ").strip().lower()
        if not resp:
            return default
        if resp in ("none", "no", "n", "-1"):
            return None
        try:
            value = int(resp)
        except ValueError:
            print("  Enter a BCM pin number or 'none'.")
            continue
        if not 0 <= value <= 27:
            print("  BCM pin must be between 0 and 27.")
            continue
        return value


# --- configuration prompts --------------------------------------------------

def prompt_sensor(existing: SensorConfig) -> SensorConfig:
    print("\n== PMS5003 particulate sensor ==")
    device = _ask_str("Serial device", existing.device)
    mode = _ask_choice("Sampling mode", ["duty_cycle", "continuous"], existing.mode)
    period_s, warmup_s, sample_s = existing.period_s, existing.warmup_s, existing.sample_s
    if mode == "duty_cycle":
        print("  Duty-cycling wakes the sensor briefly to extend fan/laser life.")
        while True:
            period_s = _ask_int("  Seconds between samples", existing.period_s, lo=1)
            warmup_s = _ask_int("  Fan warm-up seconds before reading", existing.warmup_s, lo=0)
            sample_s = _ask_int("  Averaging burst seconds", existing.sample_s, lo=1)
            if period_s > warmup_s + sample_s:
                break
            print("  Period must be greater than warm-up + burst; try again.")
    print("  SET/RESET are optional GPIO lines that sleep/wake and reset the sensor.")
    pin_enable = _ask_pin("  SET pin (enable/sleep)", existing.pin_enable)
    pin_reset = _ask_pin("  RESET pin", existing.pin_reset)
    use_atmospheric = _ask_bool("  Use atmospheric PM values (recommended outdoors)", existing.use_atmospheric)
    return replace(
        existing,
        device=device,
        mode=mode,
        period_s=period_s,
        warmup_s=warmup_s,
        sample_s=sample_s,
        pin_enable=pin_enable,
        pin_reset=pin_reset,
        use_atmospheric=use_atmospheric,
    )


def prompt_sht31(existing: SHT31Config) -> SHT31Config:
    print("\n== SHT31-D temperature / humidity sensor (optional) ==")
    enabled = _ask_bool("Is an SHT31 wired (adds humidity + PM2.5 correction)?", existing.enabled)
    address = existing.address
    if enabled:
        address = int(_ask_choice("  I2C address", ["0x44", "0x45"], hex(existing.address)), 16)
    return SHT31Config(enabled=enabled, address=address)


# --- hardware probes --------------------------------------------------------

def probe_pms(sensor: SensorConfig, settle_s: float = 3.0, timeout_s: float = 20.0) -> ProbeResult:
    try:
        from .pms5003 import PMS5003, ChecksumError, SensorTransportError
    except Exception as exc:  # pragma: no cover - driver module import
        return ProbeResult(False, f"PMS5003 driver unavailable: {exc}")
    try:
        device = PMS5003(sensor.device, sensor.baud, sensor.pin_enable, sensor.pin_reset)
    except Exception as exc:
        return ProbeResult(False, f"could not open {sensor.device}: {exc}")
    try:
        device.reset()
        device.wake()
        time.sleep(settle_s)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                frame = device.read()
            except ChecksumError:
                continue
            except SensorTransportError as exc:
                return ProbeResult(False, f"serial transport error: {exc}")
            if frame:
                return ProbeResult(True, f"PM2.5 {frame['pm2_5_atm']} ug/m3, PM10 {frame['pm10_atm']} ug/m3")
        return ProbeResult(False, "no valid frame (check 5V power and TXD -> Pi RXD wiring)")
    finally:
        try:
            device.sleep()
        except Exception:
            pass
        device.close()


def probe_sht31(address: int) -> ProbeResult:
    try:
        from .sensor_sht31 import SHT31
    except Exception as exc:  # pragma: no cover - driver module import
        return ProbeResult(False, f"SHT31 driver unavailable: {exc}")
    try:
        sensor = SHT31(address=address)
    except Exception as exc:
        return ProbeResult(False, f"could not open I2C at {hex(address)}: {exc}")
    try:
        rh, temp = sensor.read()
        return ProbeResult(True, f"{temp:.1f} C, {rh:.1f}% RH")
    except Exception as exc:
        return ProbeResult(False, f"read failed: {exc}")
    finally:
        sensor.close()


def _probe_loop(label: str, probe: Callable[[], ProbeResult]) -> bool:
    while True:
        print(f"  Probing {label} ...")
        result = probe()
        if result.ok:
            print(f"  OK  {label}: {result.detail}")
            return True
        print(f"  --  {label}: {result.detail}")
        choice = _ask_choice("  [r]etry, [s]kip, or [a]bort", ["r", "s", "a"], "r")
        if choice == "r":
            continue
        if choice == "s":
            return False
        raise SystemExit("Setup aborted.")


# --- config rendering + activation ------------------------------------------

def render_config(cfg: Config) -> str:
    s, h, st, w, y, a = cfg.sensor, cfg.sensor.sht31, cfg.storage, cfg.web, cfg.sync, cfg.alerts

    def pin(value: int | None) -> int:
        return value if value is not None else -1

    def boolean(value: bool) -> str:
        return "true" if value else "false"

    def quoted(value: str) -> str:
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'

    return f"""# PM2.5 / PM10 monitor - configuration
# Generated by `pm25-setup`. Re-run the wizard or edit values to change the setup.

[sensor]
device = {quoted(s.device)}
baud = {s.baud}
mode = {quoted(s.mode)}
period_s = {s.period_s}
warmup_s = {s.warmup_s}
sample_s = {s.sample_s}
reset_after_failures = {s.reset_after_failures}
reopen_after_failures = {s.reopen_after_failures}
use_atmospheric = {boolean(s.use_atmospheric)}
pin_enable = {pin(s.pin_enable)}   # BCM pin -> PMS5003 SET; -1 = not wired
pin_reset = {pin(s.pin_reset)}   # BCM pin -> PMS5003 RESET; -1 = not wired

[sensor.sht31]
enabled = {boolean(h.enabled)}
address = {hex(h.address)}

[storage]
db_path = {quoted(st.db_path)}
raw_retention_days = {st.raw_retention_days}

[web]
host = {quoted(w.host)}
port = {w.port}

[sync]
enabled = {boolean(y.enabled)}
server_url = {quoted(y.server_url)}
token_env = {quoted(y.token_env)}
access_client_id_env = {quoted(y.access_client_id_env)}
access_client_secret_env = {quoted(y.access_client_secret_env)}
sensor_id = {quoted(y.sensor_id)}
batch_size = {y.batch_size}
pressure_keep_days = {y.pressure_keep_days}
trigger_db_size_mb = {y.trigger_db_size_mb}
trigger_disk_free_mb = {y.trigger_disk_free_mb}
retry_total = {y.retry_total}
gzip_enabled = {boolean(y.gzip_enabled)}

[alerts]
enabled = {boolean(a.enabled)}
webhook_url = {quoted(a.webhook_url)}
token_env = {quoted(a.token_env)}
threshold_aqi = {a.threshold_aqi}
recovery_aqi = {a.recovery_aqi}
consecutive_runs = {a.consecutive_runs}
cooldown_s = {a.cooldown_s}
stale_after_s = {a.stale_after_s}
sync_lag_s = {a.sync_lag_s}
disk_free_mb = {a.disk_free_mb}
request_timeout_s = {a.request_timeout_s}
"""


def _summary(cfg: Config) -> str:
    s = cfg.sensor
    pins = f"SET={s.pin_enable if s.pin_enable is not None else 'none'}, RESET={s.pin_reset if s.pin_reset is not None else 'none'}"
    timing = f"{s.period_s}s period / {s.warmup_s}s warm-up / {s.sample_s}s burst" if s.mode == "duty_cycle" else "continuous"
    sht = f"enabled @ {hex(s.sht31.address)}" if s.sht31.enabled else "disabled"
    return (
        f"  PMS5003 : {s.device} @ {s.baud}, {s.mode} ({timing})\n"
        f"            pins {pins}, atmospheric={s.use_atmospheric}\n"
        f"  SHT31   : {sht}\n"
        f"  Database: {cfg.storage.db_path}"
    )


def _write_config(path: str, text: str) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))
    target.write_text(text)


def _hardware_notes(cfg: Config) -> list[str]:
    notes: list[str] = []
    if not Path(cfg.sensor.device).exists():
        notes.append(f"{cfg.sensor.device} is missing - enable the UART: run `sudo deploy/install.sh`, then reboot.")
    if cfg.sensor.sht31.enabled and not any(Path(f"/dev/i2c-{n}").exists() for n in (1, 0)):
        notes.append("No /dev/i2c-* bus found - enable I2C: run `sudo deploy/install.sh`, then reboot.")
    return notes


def _restart_reader() -> bool:
    if shutil.which("systemctl") is None:
        return False
    return subprocess.run(["systemctl", "restart", "pm25-reader.service"]).returncode == 0


def verify_live_reading(cfg: Config, timeout_s: float) -> ProbeResult:
    from . import db

    started = int(time.time())
    conn = db.connect(cfg.storage.db_path)
    try:
        db.init_db(conn)
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            row = conn.execute(
                "SELECT ts, pm2_5, pm2_5_corr, rh, temp FROM readings_raw ORDER BY ts DESC LIMIT 1"
            ).fetchone()
            if row is not None and row["ts"] >= started:
                pm = row["pm2_5_corr"] if row["pm2_5_corr"] is not None else row["pm2_5"]
                climate = f", {row['temp']:.1f} C {row['rh']:.1f}% RH" if row["rh"] is not None else ""
                return ProbeResult(True, f"PM2.5 {pm} ug/m3{climate}")
            time.sleep(3)
        return ProbeResult(False, "no fresh row yet")
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Interactive PM2.5 sensor setup wizard")
    parser.add_argument("--config", default="/etc/pm25/config.toml")
    parser.add_argument("--no-restart", action="store_true", help="do not restart pm25-reader after saving")
    parser.add_argument("--no-verify", action="store_true", help="do not wait for a live reading after restart")
    args = parser.parse_args(argv)

    print("PM2.5 monitor - sensor setup wizard")
    print("Configures the PMS5003 (+ optional SHT31), tests them, then activates the reader.")

    cfg = load_config(args.config)  # returns defaults when the file is absent

    if hasattr(os, "geteuid") and os.geteuid() != 0:
        print(f"\nNote: not running as root; writing {args.config} or restarting services may need sudo.")

    sensor = prompt_sensor(cfg.sensor)
    print()
    _probe_loop("PMS5003", lambda: probe_pms(sensor))

    sht31 = prompt_sht31(cfg.sensor.sht31)
    if sht31.enabled:
        print()
        if not _probe_loop("SHT31", lambda: probe_sht31(sht31.address)):
            if _ask_bool("  Disable the SHT31 for now?", True):
                sht31 = SHT31Config(enabled=False, address=sht31.address)

    new_cfg = replace(cfg, sensor=replace(sensor, sht31=sht31))
    try:
        _validate_config(new_cfg)
    except ValueError as exc:
        raise SystemExit(f"Configuration invalid: {exc}")

    print("\n== Summary ==")
    print(_summary(new_cfg))
    if not _ask_bool(f"\nWrite this to {args.config}?", True):
        raise SystemExit("Nothing written.")

    _write_config(args.config, render_config(new_cfg))
    print(f"OK  wrote {args.config}")

    for note in _hardware_notes(new_cfg):
        print(f"!   {note}")

    if args.no_restart:
        print("\nSkipped restart. Apply with: sudo systemctl restart pm25-reader.service")
    elif _restart_reader():
        print("OK  restarted pm25-reader.service")
        if not args.no_verify:
            budget = max(new_cfg.sensor.warmup_s + new_cfg.sensor.sample_s, 60) + 30
            print(f"    Waiting up to {budget}s for the first live reading ...")
            result = verify_live_reading(new_cfg, budget)
            if result.ok:
                print(f"OK  sensor is live: {result.detail}")
            else:
                print("!   no reading yet - check `journalctl -u pm25-reader -f`.")
    else:
        print("!   could not restart pm25-reader (no systemd or insufficient privileges).")
        print("    Start it with: sudo systemctl restart pm25-reader.service")

    print("\nDone. Open the dashboard at http://<pi-ip>:8080")


if __name__ == "__main__":
    main()
