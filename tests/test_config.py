import tempfile
import unittest
from pathlib import Path

from pm25.config import load_config


class ConfigTests(unittest.TestCase):
    def _load(self, text: str):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "config.toml"
            path.write_text(text, encoding="utf-8")
            return load_config(path)

    def test_valid_minimal_config_loads(self) -> None:
        cfg = self._load("[sensor]\nmode = 'continuous'\n")

        self.assertEqual(cfg.sensor.mode, "continuous")

    def test_negative_retention_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "raw_retention_days"):
            self._load("[storage]\nraw_retention_days = -1\n")

    def test_zero_sync_batch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "batch_size"):
            self._load("[sync]\nbatch_size = 0\n")

    def test_duty_cycle_period_must_include_sleep_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "period_s"):
            self._load("[sensor]\nperiod_s = 30\nwarmup_s = 25\nsample_s = 5\n")


if __name__ == "__main__":
    unittest.main()