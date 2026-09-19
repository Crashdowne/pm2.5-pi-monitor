import tempfile
import time
import unittest
from pathlib import Path

from pm25 import db, events, forecast
from pm25.api import create_app
from pm25.config import Config, DashboardConfig, SensorConfig, StorageConfig, SyncConfig, WebConfig


class IntelligenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "pm25.db")
        self.cfg = Config(
            sensor=SensorConfig(mode="continuous", sample_interval_s=60),
            storage=StorageConfig(db_path=self.db_path),
            web=WebConfig(),
            sync=SyncConfig(sensor_id="porch"),
            dashboard=DashboardConfig(),
        )
        self.now = int(time.time())
        self.conn = db.connect(self.db_path)
        db.init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tempdir.cleanup()

    def _seed_hourly_history(self, days: int = 14) -> None:
        start = self.now - days * 86400
        h = start - start % 3600
        while h <= self.now:
            hod = int(time.strftime("%H", time.gmtime(h)))
            pm = 25.0 if (hod < 6 or hod >= 20) else 10.0  # higher overnight
            self.conn.execute(
                "INSERT OR REPLACE INTO readings_hourly (ts_hour, pm2_5, pm10, pm2_5_corr, rh, temp, samples) "
                "VALUES (?,?,?,?,?,?,?)",
                (h, pm, pm * 1.3, pm, 50, 20, 6),
            )
            h += 3600
        db.insert_raw(self.conn, self.now, {"pm2_5": 12, "pm2_5_corr": 12, "pm10": 16, "rh": 50, "temp": 20})
        self.conn.commit()

    def test_forecast_blends_persistence_and_diurnal(self) -> None:
        self._seed_hourly_history()
        fc = forecast.forecast(self.conn, self.cfg, hours=6)
        self.assertEqual(len(fc), 6)
        for point in fc:
            self.assertTrue({"t", "pm2_5", "pm2_5_lo", "pm2_5_hi", "aqi"} <= set(point))
            self.assertLessEqual(point["pm2_5_lo"], point["pm2_5"])
            self.assertLessEqual(point["pm2_5"], point["pm2_5_hi"])
        self.assertLess(abs(fc[0]["pm2_5"] - 12), 6)  # first hour dominated by persistence

    def test_forecast_empty_without_data(self) -> None:
        self.assertEqual(forecast.forecast(self.conn, self.cfg), [])

    def test_events_detects_smoke_signature(self) -> None:
        start = self.now - 300 * 60
        for i in range(200):  # long low baseline so the median stays low
            db.insert_raw(self.conn, start + i * 60, {"pm2_5": 8, "pm2_5_corr": 8, "pm10": 12, "rh": 40, "temp": 20})
        plume_start = start + 200 * 60
        for i in range(80):  # 80 min of dense fine PM => wildfire signature
            db.insert_raw(
                self.conn, plume_start + i * 60, {"pm2_5": 160, "pm2_5_corr": 160, "pm10": 180, "rh": 40, "temp": 20}
            )
        self.conn.commit()
        evs = events.classify_events(self.conn, self.cfg, hours=12)
        self.assertTrue(evs)
        top = evs[0]
        self.assertEqual(top["source"], "wildfire_smoke")
        self.assertGreaterEqual(top["peak_pm2_5"], 150)
        self.assertGreater(top["duration_s"], 3600)
        self.assertGreater(top["peak_aqi"], 150)

    def test_events_empty_when_flat(self) -> None:
        base = self.now - 3 * 3600
        for i in range(30):
            db.insert_raw(self.conn, base + i * 60, {"pm2_5": 10, "pm2_5_corr": 10, "pm10": 14, "rh": 40, "temp": 20})
        self.conn.commit()
        self.assertEqual(events.classify_events(self.conn, self.cfg, hours=6), [])

    def test_endpoints(self) -> None:
        self._seed_hourly_history()
        client = create_app(self.cfg).test_client()
        fc = client.get("/api/sensors/porch/forecast?hours=4").get_json()
        self.assertEqual(len(fc), 4)
        evs = client.get("/api/sensors/porch/events?range=24h")
        self.assertEqual(evs.status_code, 200)
        self.assertIsInstance(evs.get_json(), list)


if __name__ == "__main__":
    unittest.main()
