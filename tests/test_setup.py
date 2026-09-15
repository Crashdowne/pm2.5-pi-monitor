import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from pm25 import setup
from pm25.config import (
    Config,
    SensorConfig,
    SHT31Config,
    StorageConfig,
    SyncConfig,
    WebConfig,
    load_config,
)


def _quiet() -> contextlib.AbstractContextManager:
    return contextlib.redirect_stdout(io.StringIO())


class RenderConfigTests(unittest.TestCase):
    def test_round_trips_through_load_config(self) -> None:
        cfg = Config(
            sensor=SensorConfig(
                device="/dev/ttyUSB0",
                mode="continuous",
                pin_enable=None,
                pin_reset=17,
                use_atmospheric=False,
                sht31=SHT31Config(enabled=True, address=0x45),
            ),
            storage=StorageConfig(db_path="/tmp/x.db", raw_retention_days=14),
            web=WebConfig(host="127.0.0.1", port=9090),
            sync=SyncConfig(enabled=True, server_url="http://srv:9000", sensor_id="porch", batch_size=150),
        )
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "config.toml"
            path.write_text(setup.render_config(cfg))
            loaded = load_config(path)

        self.assertEqual(loaded.sensor.device, "/dev/ttyUSB0")
        self.assertEqual(loaded.sensor.mode, "continuous")
        self.assertIsNone(loaded.sensor.pin_enable)
        self.assertEqual(loaded.sensor.pin_reset, 17)
        self.assertFalse(loaded.sensor.use_atmospheric)
        self.assertTrue(loaded.sensor.sht31.enabled)
        self.assertEqual(loaded.sensor.sht31.address, 0x45)
        self.assertEqual(loaded.storage.raw_retention_days, 14)
        self.assertEqual(loaded.web.port, 9090)
        self.assertTrue(loaded.sync.enabled)
        self.assertEqual(loaded.sync.server_url, "http://srv:9000")
        self.assertEqual(loaded.sync.sensor_id, "porch")
        self.assertEqual(loaded.sync.batch_size, 150)


class PromptTests(unittest.TestCase):
    def test_prompt_sensor_collects_values(self) -> None:
        answers = iter(["/dev/ttyAMA0", "duty_cycle", "120", "20", "6", "22", "none", "y"])
        with mock.patch("builtins.input", lambda _prompt: next(answers)), _quiet():
            sensor = setup.prompt_sensor(SensorConfig())
        self.assertEqual(sensor.device, "/dev/ttyAMA0")
        self.assertEqual((sensor.period_s, sensor.warmup_s, sensor.sample_s), (120, 20, 6))
        self.assertEqual(sensor.pin_enable, 22)
        self.assertIsNone(sensor.pin_reset)
        self.assertTrue(sensor.use_atmospheric)

    def test_prompt_sensor_reprompts_on_bad_timing(self) -> None:
        # period must exceed warmup + burst: first (50/40/20) is rejected, second (200/40/20) accepted.
        answers = iter(["/dev/ttyAMA0", "duty_cycle", "50", "40", "20", "200", "40", "20", "27", "27", "y"])
        with mock.patch("builtins.input", lambda _prompt: next(answers)), _quiet():
            sensor = setup.prompt_sensor(SensorConfig())
        self.assertEqual((sensor.period_s, sensor.warmup_s, sensor.sample_s), (200, 40, 20))

    def test_prompt_sht31_disabled_skips_address(self) -> None:
        with mock.patch("builtins.input", lambda _prompt: "n"), _quiet():
            sht = setup.prompt_sht31(SHT31Config(enabled=True, address=0x44))
        self.assertFalse(sht.enabled)


class ProbeTests(unittest.TestCase):
    def test_probe_pms_reports_missing_hardware(self) -> None:
        result = setup.probe_pms(SensorConfig(), settle_s=0.0, timeout_s=0.0)
        self.assertFalse(result.ok)

    def test_probe_sht31_reports_missing_hardware(self) -> None:
        self.assertFalse(setup.probe_sht31(0x44).ok)


class WizardFlowTests(unittest.TestCase):
    def test_main_writes_config_without_restart(self) -> None:
        answers = iter(
            ["/dev/ttyAMA0", "duty_cycle", "180", "30", "8", "22", "27", "y", "y", "0x44", "y"]
        )
        with tempfile.TemporaryDirectory() as d:
            path = str(Path(d) / "config.toml")
            with mock.patch("builtins.input", lambda _prompt: next(answers)), mock.patch.object(
                setup, "probe_pms", return_value=setup.ProbeResult(True, "PM2.5 5 ug/m3")
            ), mock.patch.object(
                setup, "probe_sht31", return_value=setup.ProbeResult(True, "21.0 C, 50% RH")
            ), _quiet():
                setup.main(["--config", path, "--no-restart"])
            self.assertTrue(Path(path).exists())
            loaded = load_config(path)
            self.assertEqual(loaded.sensor.pin_enable, 22)
            self.assertEqual(loaded.sensor.pin_reset, 27)
            self.assertTrue(loaded.sensor.sht31.enabled)


if __name__ == "__main__":
    unittest.main()
