import tempfile
import unittest
from pathlib import Path

from pm25 import db
from pm25.alerts import run_once
from pm25.config import AlertConfig, Config, SensorConfig, StorageConfig, SyncConfig, WebConfig


class AlertTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "pm25.db")
        self.cfg = Config(
            sensor=SensorConfig(),
            storage=StorageConfig(db_path=self.db_path),
            web=WebConfig(),
            sync=SyncConfig(sensor_id="porch"),
            alerts=AlertConfig(
                enabled=True,
                threshold_aqi=101,
                recovery_aqi=80,
                consecutive_runs=2,
                disk_free_mb=0,
            ),
        )
        conn = db.connect(self.db_path)
        db.init_db(conn)
        db.insert_raw(conn, 1000, {"pm2_5": 40, "pm10": 20})
        db.update_rollups(conn, 1000)
        conn.commit()
        conn.close()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_aqi_alert_requires_consecutive_runs(self) -> None:
        events: list[dict] = []

        self.assertTrue(run_once(self.cfg, now=1000, sender=events.append))
        self.assertEqual(events, [])
        self.assertTrue(run_once(self.cfg, now=1120, sender=events.append))

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event"], "aqi_high")
        self.assertEqual(events[0]["sensor_id"], "porch")
        self.assertTrue(events[0]["active"])

    def test_missing_first_reading_triggers_stale_sensor_alert(self) -> None:
        conn = db.connect(self.db_path)
        conn.execute("DELETE FROM readings_raw")
        conn.execute("DELETE FROM alert_state")
        conn.commit()
        conn.close()
        events: list[dict] = []

        self.assertTrue(run_once(self.cfg, now=1000, sender=events.append))

        self.assertEqual([event["event"] for event in events], ["sensor_stale"])
        self.assertTrue(events[0]["active"])


if __name__ == "__main__":
    unittest.main()