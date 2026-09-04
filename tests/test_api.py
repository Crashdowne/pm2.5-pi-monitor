import tempfile
import time
import unittest
from pathlib import Path

from pm25 import db
from pm25.api import create_app
from pm25.config import Config, SensorConfig, SHT31Config, StorageConfig, SyncConfig, WebConfig


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "pm25.db")
        self.cfg = Config(
            sensor=SensorConfig(period_s=120, sht31=SHT31Config(enabled=True)),
            storage=StorageConfig(db_path=self.db_path),
            web=WebConfig(),
            sync=SyncConfig(enabled=True, server_url="http://server"),
        )
        self.now = int(time.time())
        conn = db.connect(self.db_path)
        db.init_db(conn)
        db.insert_raw(conn, self.now, {"pm2_5": 10, "pm2_5_corr": 8, "pm10": 12, "rh": 48})
        db.update_rollups(conn, self.now)
        db.record_reader_cycle(
            conn,
            self.now,
            success=True,
            valid_frames=8,
            checksum_errors=1,
            timeout_reads=0,
            sht31_ok=True,
        )
        conn.commit()
        conn.close()
        self.client = create_app(self.cfg).test_client()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_current_includes_health_and_supports_etag(self) -> None:
        response = self.client.get("/api/current")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["health"]["sample_period_s"], 120)
        self.assertEqual(payload["health"]["sensors"]["pm"], "ok")
        self.assertEqual(payload["health"]["sensors"]["humidity"], "ok")
        self.assertEqual(payload["health"]["reader"]["checksum_errors_total"], 1)

        cached = self.client.get("/api/current", headers={"If-None-Match": response.headers["ETag"]})
        self.assertEqual(cached.status_code, 304)

    def test_averages_include_sample_coverage(self) -> None:
        payload = self.client.get("/api/averages").get_json()

        self.assertEqual(payload["hourly"][0]["samples"], 1)
        self.assertGreater(payload["hourly"][0]["coverage"], 0)


if __name__ == "__main__":
    unittest.main()