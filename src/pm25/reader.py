"""Sensor reader daemon: PMS5003 -> averaged samples -> SQLite (raw + rollups)."""
from __future__ import annotations

import argparse
import logging
import signal
import time
from typing import Protocol

from . import aqi, db
from .config import Config, load_config
from .pms5003 import PMS5003, ChecksumError, SensorTransportError

log = logging.getLogger("pm25.reader")

_stop = False


class ParticleSensor(Protocol):
    def reset(self) -> None: ...
    def reopen(self) -> None: ...
    def wake(self) -> None: ...
    def sleep(self) -> None: ...
    def read(self) -> dict | None: ...
    def close(self) -> None: ...


def _handle_stop(*_: object) -> None:
    global _stop
    _stop = True


def _sleep(seconds: float) -> None:
    """Interruptible sleep that returns early on SIGTERM/SIGINT."""
    end = time.monotonic() + seconds
    while not _stop:
        remaining = end - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.5, remaining))


def _avg(samples: list[dict], use_atmospheric: bool) -> dict:
    suffix = "atm" if use_atmospheric else "std"
    n = len(samples)

    def mean(key: str) -> float:
        return sum(s[key] for s in samples) / n

    return {
        "pm1_0": round(mean(f"pm1_0_{suffix}"), 1),
        "pm2_5": round(mean(f"pm2_5_{suffix}"), 1),
        "pm10": round(mean(f"pm10_{suffix}"), 1),
        "pm2_5_std": round(mean("pm2_5_std"), 1),  # CF=1 channel, input to humidity correction
        "n0_3": round(mean("n0_3")), "n0_5": round(mean("n0_5")), "n1_0": round(mean("n1_0")),
        "n2_5": round(mean("n2_5")), "n5_0": round(mean("n5_0")), "n10": round(mean("n10")),
    }


def _write(conn, ts: int, avg: dict, sht) -> bool | None:
    sht31_ok = None
    if sht is not None:
        try:
            rh, temp = sht.read()
            avg = {
                **avg,
                "rh": round(rh, 1),
                "temp": round(temp, 1),
                "pm2_5_corr": aqi.correct_pm25(avg["pm2_5_std"], rh),
            }
            sht31_ok = True
        except Exception as e:  # humidity sensor must never take down sampling
            log.warning("SHT31 read failed: %s", e)
            sht31_ok = False
    db.insert_raw(conn, ts, avg)
    db.update_rollups(conn, ts)
    return sht31_ok


def _collect_burst(sensor: ParticleSensor, seconds: float) -> tuple[list[dict], int, int, int]:
    samples: list[dict] = []
    checksum_errors = 0
    timeout_reads = 0
    transport_errors = 0
    end = time.monotonic() + seconds
    while not _stop and time.monotonic() < end:
        try:
            r = sensor.read()
        except ChecksumError:
            checksum_errors += 1
            continue
        except SensorTransportError:
            transport_errors += 1
            break
        if r:
            samples.append(r)
        else:
            timeout_reads += 1
    return samples, checksum_errors, timeout_reads, transport_errors


def _recover_sensor(sensor: ParticleSensor, cfg: Config, consecutive_failures: int) -> str | None:
    sensor_cfg = cfg.sensor
    if sensor_cfg.reopen_after_failures > 0 and consecutive_failures % sensor_cfg.reopen_after_failures == 0:
        sensor.reopen()
        sensor.reset()
        log.warning("reopened PMS5003 UART after %d failed cycles", consecutive_failures)
        return "reopen"
    if sensor_cfg.reset_after_failures > 0 and consecutive_failures % sensor_cfg.reset_after_failures == 0:
        sensor.reset()
        log.warning("reset PMS5003 after %d failed cycles", consecutive_failures)
        return "reset"
    return None


def _run_duty_cycle(conn, sensor: ParticleSensor, cfg: Config, sht) -> None:
    s = cfg.sensor
    consecutive_failures = 0
    while not _stop:
        sensor.wake()
        _sleep(s.warmup_s)
        samples, checksum_errors, timeout_reads, transport_errors = _collect_burst(sensor, s.sample_s)
        sensor.sleep()
        cycle_ts = int(time.time())
        if samples:
            consecutive_failures = 0
            avg = _avg(samples, s.use_atmospheric)
            sht31_ok = _write(conn, cycle_ts, avg, sht)
            db.record_reader_cycle(
                conn,
                cycle_ts,
                success=True,
                valid_frames=len(samples),
                checksum_errors=checksum_errors,
                timeout_reads=timeout_reads,
                transport_errors=transport_errors,
                sht31_ok=sht31_ok,
            )
            log.info("sample pm2.5=%.1f pm10=%.1f (n=%d)", avg["pm2_5"], avg["pm10"], len(samples))
        else:
            consecutive_failures += 1
            log.warning("no valid frames this cycle")
            recovery = _recover_sensor(sensor, cfg, consecutive_failures)
            db.record_reader_cycle(
                conn,
                cycle_ts,
                success=False,
                valid_frames=0,
                checksum_errors=checksum_errors,
                timeout_reads=timeout_reads,
                transport_errors=transport_errors,
                sht31_ok=None,
                recovery=recovery,
            )
        db.commit(conn)
        _sleep(max(1, s.period_s - s.warmup_s - s.sample_s))


def _run_continuous(conn, sensor: ParticleSensor, cfg: Config, sht) -> None:
    s = cfg.sensor
    interval = max(1, s.sample_interval_s)
    commit_every = cfg.storage.commit_interval_s
    sensor.wake()
    buf: list[dict] = []
    consecutive_failures = 0
    checksum_errors = 0
    timeout_reads = 0
    transport_errors = 0
    next_write = (int(time.time()) // interval + 1) * interval
    last_commit = time.monotonic()
    while not _stop:
        try:
            r = sensor.read()
            if r:
                buf.append(r)
        except ChecksumError:
            checksum_errors += 1
        except SensorTransportError:
            transport_errors += 1
            buf = []
            _sleep(max(0, next_write - time.time()))
        else:
            if not r:
                timeout_reads += 1
        if time.time() >= next_write:
            cycle_ts = int(time.time())
            if buf:
                consecutive_failures = 0
                avg = _avg(buf, s.use_atmospheric)
                sht31_ok = _write(conn, next_write - interval, avg, sht)
                db.record_reader_cycle(
                    conn,
                    cycle_ts,
                    success=True,
                    valid_frames=len(buf),
                    checksum_errors=checksum_errors,
                    timeout_reads=timeout_reads,
                    transport_errors=transport_errors,
                    sht31_ok=sht31_ok,
                )
                log.info("sample pm2.5=%.1f pm10=%.1f (n=%d)", avg["pm2_5"], avg["pm10"], len(buf))
                buf = []
            else:
                consecutive_failures += 1
                log.warning("no valid frames this interval")
                recovery = _recover_sensor(sensor, cfg, consecutive_failures)
                db.record_reader_cycle(
                    conn,
                    cycle_ts,
                    success=False,
                    valid_frames=0,
                    checksum_errors=checksum_errors,
                    timeout_reads=timeout_reads,
                    transport_errors=transport_errors,
                    sht31_ok=None,
                    recovery=recovery,
                )
            if commit_every <= 0 or time.monotonic() - last_commit >= commit_every:
                db.commit(conn)
                last_commit = time.monotonic()
            checksum_errors = 0
            timeout_reads = 0
            transport_errors = 0
            next_write += interval


def run(cfg: Config, simulation_profile: str | None = None) -> None:
    conn = db.connect(cfg.storage.db_path)
    db.init_db(conn)
    if simulation_profile:
        from .simulation import SimulatedPMS5003

        sensor: ParticleSensor = SimulatedPMS5003(simulation_profile)
        log.info("using simulated PMS5003 profile=%s", simulation_profile)
    else:
        sensor = PMS5003(cfg.sensor.device, cfg.sensor.baud, cfg.sensor.pin_enable, cfg.sensor.pin_reset)
    sensor.reset()

    sht = None
    if cfg.sensor.sht31.enabled:
        try:
            from .sensor_sht31 import SHT31

            sht = SHT31(address=cfg.sensor.sht31.address)
        except Exception as e:  # keep logging PM even if the humidity sensor is missing
            log.warning("SHT31 init failed, continuing without humidity: %s", e)
            conn.execute(
                "UPDATE reader_status SET sht31_ok = 0, sht31_failures_total = sht31_failures_total + 1 WHERE id = 1"
            )
            conn.commit()

    try:
        if cfg.sensor.mode == "continuous":
            _run_continuous(conn, sensor, cfg, sht)
        else:
            _run_duty_cycle(conn, sensor, cfg, sht)
    finally:
        conn.commit()  # flush any batched-but-uncommitted samples before closing
        sensor.close()
        if sht is not None:
            sht.close()
        conn.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    ap = argparse.ArgumentParser(description="PMS5003 reader daemon")
    ap.add_argument("--config", default="/etc/pm25/config.toml")
    ap.add_argument("--simulate", choices=("normal", "smoke", "faulty"))
    args = ap.parse_args()
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    run(load_config(args.config), simulation_profile=args.simulate)


if __name__ == "__main__":
    main()
