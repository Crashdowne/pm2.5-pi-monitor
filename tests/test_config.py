import tempfile
import unittest
from pathlib import Path

from pm25.config import load_config, parse_pin


class ConfigTests(unittest.TestCase):
    def _load(self, text: str):
        with tempfile.TemporaryDirectory() as tempdir:
            path = Path(tempdir) / "config.toml"
            path.write_text(text, encoding="utf-8")
            return load_config(path)

    def test_valid_minimal_config_loads(self) -> None:
        cfg = self._load("[sensor]\nmode = 'continuous'\n")

        self.assertEqual(cfg.sensor.mode, "continuous")
        self.assertEqual(cfg.sensor.period_s, 180)

    def test_negative_retention_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "raw_retention_days"):
            self._load("[storage]\nraw_retention_days = -1\n")

    def test_zero_sync_batch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "batch_size"):
            self._load("[sync]\nbatch_size = 0\n")

    def test_duty_cycle_period_must_include_sleep_time(self) -> None:
        with self.assertRaisesRegex(ValueError, "period_s"):
            self._load("[sensor]\nperiod_s = 30\nwarmup_s = 25\nsample_s = 5\n")

    def test_i2c_bus_defaults_to_one_and_loads(self) -> None:
        self.assertEqual(self._load("[sensor]\n").sensor.i2c_bus, 1)
        self.assertEqual(self._load("[sensor]\ni2c_bus = 3\n").sensor.i2c_bus, 3)

    def test_update_defaults_and_overrides(self) -> None:
        cfg = self._load("[sensor]\n")
        self.assertTrue(cfg.update.allow_web_trigger)
        self.assertEqual(cfg.update.remote, "")
        self.assertEqual(cfg.update.branch, "main")
        self.assertFalse(cfg.update.auto_pull)
        cfg = self._load(
            "[update]\nremote = 'ssh://git@devbox.tail1234.ts.net/pm25.git'\nbranch = 'release/1'\n"
            "auto_pull = true\nallow_web_trigger = false\n"
        )
        self.assertEqual(cfg.update.remote, "ssh://git@devbox.tail1234.ts.net/pm25.git")
        self.assertEqual(cfg.update.branch, "release/1")
        self.assertTrue(cfg.update.auto_pull)
        self.assertFalse(cfg.update.allow_web_trigger)

    def test_update_rejects_unsafe_values(self) -> None:
        for text, field in (
            ("[update]\nbranch = '-x; rm'\n", "update.branch"),
            ("[update]\nremote = 'origin; reboot'\n", "update.remote"),
            ("[update]\nstate_dir = 'relative/dir'\n", "update.state_dir"),
            ("[update]\ntoken_env = 'BAD-NAME'\n", "update.token_env"),
        ):
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, field):
                self._load(text)

    def test_negative_i2c_bus_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "i2c_bus"):
            self._load("[sensor]\ni2c_bus = -1\n")

    def test_gpiochip_pins_load_as_strings(self) -> None:
        cfg = self._load("[sensor]\npin_enable = \"gpiochip3:8\"\npin_reset = -1\n")
        self.assertEqual(cfg.sensor.pin_enable, "gpiochip3:8")
        self.assertIsNone(cfg.sensor.pin_reset)


class ParsePinTests(unittest.TestCase):
    def test_valid_values(self) -> None:
        self.assertEqual(parse_pin(22), 22)
        self.assertEqual(parse_pin("27"), 27)
        self.assertIsNone(parse_pin(-1))
        self.assertIsNone(parse_pin(""))
        self.assertIsNone(parse_pin(None))
        self.assertEqual(parse_pin("gpiochip3:8"), "gpiochip3:8")
        self.assertEqual(parse_pin(" /dev/gpiochip0:12 "), "/dev/gpiochip0:12")

    def test_invalid_values(self) -> None:
        for bad in ("gpiochip3", "chip3:8", "gpiochip3:x", "abc"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                parse_pin(bad)


if __name__ == "__main__":
    unittest.main()