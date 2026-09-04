"""SHT31-D temperature + humidity reader (I2C via smbus2).

Present but disabled by default (`[sensor.sht31] enabled = false`). Wire the sensor and
flip the flag when the hardware arrives; the reader will then stamp rh/temp onto each row.
Uses a high-repeatability single-shot measurement with CRC-checked results.
"""
from __future__ import annotations

import time

try:
    from smbus2 import SMBus, i2c_msg
except Exception:  # pragma: no cover - only needed when enabled
    SMBus = None
    i2c_msg = None


class SHT31:
    _MEASURE = (0x24, 0x00)  # high repeatability, clock stretching disabled
    _SOFT_RESET = (0x30, 0xA2)

    def __init__(self, bus: int = 1, address: int = 0x44) -> None:
        if SMBus is None:
            raise RuntimeError("smbus2 not installed - run `uv sync --extra pi` on the Pi")
        self._bus = SMBus(bus)
        self._addr = address
        self._command(*self._SOFT_RESET)
        time.sleep(0.05)

    def _command(self, msb: int, lsb: int) -> None:
        self._bus.write_i2c_block_data(self._addr, msb, [lsb])

    def read(self) -> tuple[float, float]:
        """Return (relative_humidity_percent, temperature_celsius)."""
        self._command(*self._MEASURE)
        time.sleep(0.02)  # ~15 ms conversion for high repeatability
        msg = i2c_msg.read(self._addr, 6)
        self._bus.i2c_rdwr(msg)
        raw = list(msg)
        if self._crc(raw[0:2]) != raw[2] or self._crc(raw[3:5]) != raw[5]:
            raise RuntimeError("SHT31 CRC mismatch")
        t_raw = (raw[0] << 8) | raw[1]
        h_raw = (raw[3] << 8) | raw[4]
        temp = -45.0 + 175.0 * t_raw / 65535.0
        rh = 100.0 * h_raw / 65535.0
        return max(0.0, min(100.0, rh)), temp

    @staticmethod
    def _crc(data: list[int]) -> int:
        crc = 0xFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                crc = ((crc << 1) ^ 0x31) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
        return crc

    def close(self) -> None:
        try:
            self._bus.close()
        except Exception:
            pass
