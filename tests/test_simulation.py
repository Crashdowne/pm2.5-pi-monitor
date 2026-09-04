import unittest

from pm25.pms5003 import ChecksumError
from pm25.simulation import SimulatedPMS5003


class SimulationTests(unittest.TestCase):
    def test_normal_profile_emits_complete_frames(self) -> None:
        sensor = SimulatedPMS5003(frame_interval_s=0)

        frame = sensor.read()

        self.assertIsNotNone(frame)
        self.assertEqual(
            set(frame or {}),
            {
                "pm1_0_std", "pm2_5_std", "pm10_std",
                "pm1_0_atm", "pm2_5_atm", "pm10_atm",
                "n0_3", "n0_5", "n1_0", "n2_5", "n5_0", "n10",
            },
        )

    def test_faulty_profile_injects_timeouts_and_checksum_errors(self) -> None:
        sensor = SimulatedPMS5003(profile="faulty", frame_interval_s=0)
        timeouts = 0
        checksum_errors = 0

        for _ in range(20):
            try:
                if sensor.read() is None:
                    timeouts += 1
            except ChecksumError:
                checksum_errors += 1

        self.assertGreaterEqual(timeouts, 2)
        self.assertEqual(checksum_errors, 1)


if __name__ == "__main__":
    unittest.main()