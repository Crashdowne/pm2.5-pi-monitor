import unittest
import sqlite3

from pm25 import db
from pm25.config import Config, SensorConfig, StorageConfig, SyncConfig, WebConfig
from pm25.reader import _recover_sensor


class FakeSensor:
    def __init__(self) -> None:
        self.resets = 0
        self.reopens = 0

    def reset(self) -> None:
        self.resets += 1

    def reopen(self) -> None:
        self.reopens += 1


class ReaderRecoveryTests(unittest.TestCase):
    def test_stalled_sensor_is_reset_then_reopened(self) -> None:
        cfg = Config(
            sensor=SensorConfig(reset_after_failures=2, reopen_after_failures=4),
            storage=StorageConfig(),
            web=WebConfig(),
            sync=SyncConfig(),
        )
        sensor = FakeSensor()

        self.assertIsNone(_recover_sensor(sensor, cfg, 1))
        self.assertEqual(_recover_sensor(sensor, cfg, 2), "reset")
        self.assertEqual(_recover_sensor(sensor, cfg, 4), "reopen")
        self.assertEqual((sensor.resets, sensor.reopens), (2, 1))

    def test_reader_status_accumulates_cycle_diagnostics(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        db.init_db(conn)

        db.record_reader_cycle(
            conn,
            100,
            success=False,
            valid_frames=0,
            checksum_errors=2,
            timeout_reads=1,
            sht31_ok=None,
            recovery="reset",
        )
        db.record_reader_cycle(
            conn,
            200,
            success=True,
            valid_frames=5,
            checksum_errors=1,
            timeout_reads=0,
            sht31_ok=False,
        )

        status = conn.execute("SELECT * FROM reader_status WHERE id = 1").fetchone()
        self.assertEqual(status["last_success_ts"], 200)
        self.assertEqual(status["consecutive_failures"], 0)
        self.assertEqual(status["valid_frames_total"], 5)
        self.assertEqual(status["checksum_errors_total"], 3)
        self.assertEqual(status["sensor_resets_total"], 1)
        self.assertEqual(status["sht31_failures_total"], 1)
        conn.close()


if __name__ == "__main__":
    unittest.main()