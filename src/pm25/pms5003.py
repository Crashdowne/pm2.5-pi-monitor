"""Minimal PMS5003 UART driver (pyserial) with optional GPIO sleep/wake.

Frame: 0x42 0x4D, 2-byte length, then 13 uint16 data words + 1 uint16 checksum
(big-endian). Data words 0-2 are 'standard' PM1.0/2.5/10, words 3-5 are the
'atmospheric/environmental' values, words 6-11 are particle counts per 0.1 L.
"""
from __future__ import annotations

import struct
import time

try:  # available only on the Pi (the 'pi' extra)
    import serial
except Exception:  # pragma: no cover - dev machines without pyserial
    serial = None

try:
    from gpiozero import OutputDevice
except Exception:  # pragma: no cover
    OutputDevice = None

_SOF = (0x42, 0x4D)
_SLEEP_CMD = bytes([0x42, 0x4D, 0xE4, 0x00, 0x00, 0x01, 0x73])
_WAKE_CMD = bytes([0x42, 0x4D, 0xE4, 0x00, 0x01, 0x01, 0x74])


class ChecksumError(RuntimeError):
    pass


class PMS5003:
    def __init__(
        self,
        device: str,
        baud: int = 9600,
        pin_enable: int | None = None,
        pin_reset: int | None = None,
        read_timeout: float = 5.0,
    ) -> None:
        if serial is None:
            raise RuntimeError("pyserial not installed - run `uv sync --extra pi` on the Pi")
        self._device = device
        self._baud = baud
        self._serial = serial.Serial(self._device, baudrate=self._baud, timeout=1.0)
        self.read_timeout = read_timeout
        self._enable = None
        self._reset = None
        if pin_enable is not None and OutputDevice is not None:
            self._enable = OutputDevice(pin_enable, initial_value=True)
        if pin_reset is not None and OutputDevice is not None:
            self._reset = OutputDevice(pin_reset, initial_value=True)

    def reset(self) -> None:
        if self._reset is not None:
            self._reset.off()
            time.sleep(0.1)
            self._serial.reset_input_buffer()
            self._reset.on()
            time.sleep(0.1)

    def reopen(self) -> None:
        """Reopen the UART after repeated read timeouts without recreating GPIO devices."""
        try:
            self._serial.close()
        finally:
            self._serial = serial.Serial(self._device, baudrate=self._baud, timeout=1.0)

    def wake(self) -> None:
        if self._enable is not None:
            self._enable.on()
        else:  # no SET pin wired - fall back to the passive-mode UART command
            try:
                self._serial.write(_WAKE_CMD)
            except Exception:
                pass

    def sleep(self) -> None:
        if self._enable is not None:
            self._enable.off()
        else:
            try:
                self._serial.write(_SLEEP_CMD)
            except Exception:
                pass

    def read(self) -> dict | None:
        """Return one decoded frame, or None on timeout. Raises ChecksumError on a bad frame."""
        ser = self._serial
        deadline = time.monotonic() + self.read_timeout
        while True:  # scan for start-of-frame
            if time.monotonic() > deadline:
                return None
            b = ser.read(1)
            if not b or b[0] != _SOF[0]:
                continue
            b2 = ser.read(1)
            if b2 and b2[0] == _SOF[1]:
                break

        header = ser.read(2)
        if len(header) != 2:
            return None
        frame_len = (header[0] << 8) | header[1]
        if not 4 <= frame_len <= 64:
            return None
        body = ser.read(frame_len)
        if len(body) != frame_len:
            return None

        checksum = _SOF[0] + _SOF[1] + header[0] + header[1] + sum(body[:-2])
        expected = (body[-2] << 8) | body[-1]
        if checksum != expected:
            raise ChecksumError(f"{checksum} != {expected}")

        data = struct.unpack(f">{frame_len // 2}H", body)
        return {
            "pm1_0_std": data[0], "pm2_5_std": data[1], "pm10_std": data[2],
            "pm1_0_atm": data[3], "pm2_5_atm": data[4], "pm10_atm": data[5],
            "n0_3": data[6], "n0_5": data[7], "n1_0": data[8],
            "n2_5": data[9], "n5_0": data[10], "n10": data[11],
        }

    def close(self) -> None:
        try:
            self._serial.close()
        except Exception:
            pass
        for d in (self._enable, self._reset):
            if d is not None:
                try:
                    d.close()
                except Exception:
                    pass
