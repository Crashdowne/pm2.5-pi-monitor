"""Deterministic PMS5003 simulator for local development and fault testing."""
from __future__ import annotations

import math
import random
import time

from .pms5003 import ChecksumError


class SimulatedPMS5003:
    def __init__(self, profile: str = "normal", frame_interval_s: float = 0.2, seed: int = 25) -> None:
        if profile not in {"normal", "smoke", "faulty"}:
            raise ValueError(f"unknown simulation profile: {profile}")
        self.profile = profile
        self.frame_interval_s = frame_interval_s
        self._random = random.Random(seed)
        self._started = time.monotonic()
        self._reads = 0
        self._awake = True

    def reset(self) -> None:
        self._reads = 0

    def reopen(self) -> None:
        self._reads = 0

    def wake(self) -> None:
        self._awake = True

    def sleep(self) -> None:
        self._awake = False

    def read(self) -> dict | None:
        if self.frame_interval_s:
            time.sleep(self.frame_interval_s)
        if not self._awake:
            return None

        self._reads += 1
        if self.profile == "faulty":
            if self._reads % 19 == 0:
                raise ChecksumError("simulated checksum mismatch")
            if self._reads % 7 == 0:
                return None

        elapsed = time.monotonic() - self._started
        pm25 = 7.0 + 2.5 * math.sin(elapsed / 90) + self._random.uniform(-0.8, 0.8)
        if self.profile == "smoke":
            phase = elapsed % 600
            if 180 <= phase <= 420:
                pm25 += 72 * math.sin(math.pi * (phase - 180) / 240)
        pm25 = max(0.0, pm25)
        pm10 = max(pm25 * 1.35, pm25 + 2.0)
        pm1 = pm25 * 0.72

        return {
            "pm1_0_std": round(pm1 * 1.04),
            "pm2_5_std": round(pm25 * 1.04),
            "pm10_std": round(pm10 * 1.04),
            "pm1_0_atm": round(pm1),
            "pm2_5_atm": round(pm25),
            "pm10_atm": round(pm10),
            "n0_3": round(pm25 * 104),
            "n0_5": round(pm25 * 62),
            "n1_0": round(pm25 * 24),
            "n2_5": round(pm25 * 5),
            "n5_0": round(pm25),
            "n10": round(pm25 / 4),
        }

    def close(self) -> None:
        pass