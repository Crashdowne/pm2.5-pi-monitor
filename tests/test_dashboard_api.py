import json
import tempfile
import time
import unittest
from pathlib import Path

from pm25 import db
from pm25.api import create_app, sse_current_stream
from pm25.config import Config, DashboardConfig, SensorConfig, SHT31Config, StorageConfig, SyncConfig, WebConfig


class DashboardApiTests(unittest.TestCase):
    """Covers the ported aqi-worker read-endpoints the React dashboard consumes."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "pm25.db")
        self.cfg = Config(
            sensor=SensorConfig(period_s=120, sht31=SHT31Config(enabled=True)),
            storage=StorageConfig(db_path=self.db_path),
            web=WebConfig(),
            sync=SyncConfig(enabled=True, server_url="http://server", sensor_id="porch"),
            dashboard=DashboardConfig(site_title="Porch Air", mask_sensitivity="asthma"),
        )
        self.now = int(time.time())
        conn = db.connect(self.db_path)
        db.init_db(conn)
        for dt, pm25, corr, pm10, rh, temp in [
            (0, 10, 8, 12, 48, 21),
            (3600, 20, 18, 25, 50, 20),
            (7200, 30, 28, 35, 52, 19),
            (10800, 15, 13, 18, 47, 22),
            (86400, 40, 38, 45, 55, 18),
        ]:
            ts = self.now - dt
            db.insert_raw(conn, ts, {"pm2_5": pm25, "pm2_5_corr": corr, "pm10": pm10, "rh": rh, "temp": temp})
            db.update_rollups(conn, ts)
        conn.execute("UPDATE sync_state SET last_success_ts = ? WHERE id = 1", (self.now - 60,))
        db.record_reader_cycle(
            conn, self.now, success=True, valid_frames=8, checksum_errors=0, timeout_reads=0, sht31_ok=True
        )
        conn.commit()
        conn.close()
        self.client = create_app(self.cfg).test_client()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_config_shape(self) -> None:
        payload = self.client.get("/api/config").get_json()
        self.assertEqual(payload["site_title"], "Porch Air")
        self.assertIn("24h", payload["ranges"])
        self.assertEqual(len(payload["bands"]), 6)
        self.assertEqual(set(payload["mask"]["thresholds"]), {"carry", "recommended", "strong", "indoors"})
        self.assertEqual(payload["mask"]["thresholds"]["carry"], 51)  # asthma preset
        self.assertIn("asthma", payload["mask"]["presets"])
        self.assertEqual(len(payload["mask"]["levels"]), 5)

    def test_mask_threshold_override(self) -> None:
        cfg = Config(
            sensor=self.cfg.sensor,
            storage=self.cfg.storage,
            web=self.cfg.web,
            sync=self.cfg.sync,
            dashboard=DashboardConfig(mask_sensitivity="asthma", mask_carry_aqi=40),
        )
        payload = create_app(cfg).test_client().get("/api/config").get_json()
        self.assertEqual(payload["mask"]["thresholds"]["carry"], 40)
        self.assertEqual(payload["mask"]["thresholds"]["recommended"], 76)  # preset kept

    def test_sensors_overview_single_entry(self) -> None:
        data = self.client.get("/api/sensors").get_json()
        self.assertEqual(len(data), 1)
        entry = data[0]
        self.assertEqual(entry["sensor_id"], "porch")
        self.assertIsInstance(entry["aqi"], int)
        self.assertIn("mask_level", entry)
        self.assertTrue(entry["online"])
        self.assertTrue(entry["sht31_ok"])

    def test_sensors_etag_304(self) -> None:
        first = self.client.get("/api/sensors")
        cached = self.client.get("/api/sensors", headers={"If-None-Match": first.headers["ETag"]})
        self.assertEqual(cached.status_code, 304)

    def test_current_shape(self) -> None:
        payload = self.client.get("/api/sensors/porch/current").get_json()
        self.assertEqual(payload["sensor_id"], "porch")
        self.assertIsInstance(payload["nowcast_aqi"], int)
        self.assertIn(payload["dominant"], ("pm2_5", "pm10"))
        self.assertEqual(payload["pm2_5"], 8)  # corrected value preferred
        self.assertEqual(payload["pm2_5_raw"], 10)
        self.assertIn("disclaimer", payload["mask"])
        self.assertIn("good_window", payload)
        self.assertEqual(payload["last_ingest_age_s"], self.now - (self.now - 60))

    def test_history_recent_and_long_range(self) -> None:
        recent = self.client.get("/api/sensors/porch/history?range=24h").get_json()
        self.assertTrue(recent)
        for point in recent:
            self.assertEqual(set(point), {"t", "pm2_5", "pm10", "temp", "rh", "aqi"})
        long_range = self.client.get("/api/sensors/porch/history?range=7d").get_json()
        self.assertIsInstance(long_range, list)

    def test_calendar(self) -> None:
        year = time.gmtime(self.now).tm_year
        data = self.client.get(f"/api/sensors/porch/calendar?year={year}").get_json()
        self.assertIsInstance(data, list)
        self.assertTrue(all(d["date"].startswith(str(year)) for d in data))

    def test_heatmap_cells(self) -> None:
        data = self.client.get("/api/sensors/porch/heatmap?range=7d").get_json()
        self.assertTrue(data)
        for cell in data:
            self.assertEqual(len(cell), 3)  # [hour, dow, aqi]

    def test_distribution_bands(self) -> None:
        data = self.client.get("/api/sensors/porch/distribution?range=7d").get_json()
        self.assertEqual(len(data), 6)
        self.assertGreaterEqual(sum(b["hours"] for b in data), 1)
        self.assertAlmostEqual(sum(b["pct"] for b in data), 100.0, delta=0.5)

    def test_diurnal_24_hours(self) -> None:
        data = self.client.get("/api/sensors/porch/diurnal?range=24h").get_json()
        self.assertEqual(len(data), 24)
        self.assertEqual([d["hour"] for d in data], list(range(24)))

    def test_summary_periods(self) -> None:
        data = self.client.get("/api/sensors/porch/summary").get_json()
        self.assertEqual(len(data["by_period"]), 3)
        for key in ("pm25_24h", "aqi_7d", "cigarettes_30d", "peak_aqi_7d", "exceedance_hours_30d"):
            self.assertIn(key, data)

    def test_status(self) -> None:
        data = self.client.get("/api/sensors/porch/status").get_json()
        self.assertEqual(data["sensor_id"], "porch")
        self.assertTrue(data["online"])
        self.assertEqual(set(data["coverage_24h"]), {"expected", "actual", "pct"})
        self.assertTrue(data["sht31"]["ok"])
        self.assertIsInstance(data["gaps_7d"]["count"], int)

    def test_mask_endpoint(self) -> None:
        data = self.client.get("/api/sensors/porch/mask").get_json()
        self.assertIn("aqi", data)
        self.assertIn("level", data["mask"])
        self.assertIn("good_window", data)

    def test_export_csv_and_json(self) -> None:
        csv = self.client.get("/api/sensors/porch/export?range=24h&format=csv")
        self.assertTrue(csv.headers["Content-Type"].startswith("text/csv"))
        self.assertTrue(csv.get_data(as_text=True).startswith("ts,iso_utc,pm2_5,pm10,temp,rh,aqi"))
        js = self.client.get("/api/sensors/porch/export?range=24h&format=json").get_json()
        self.assertIsInstance(js, list)

    def test_unknown_sensor_404(self) -> None:
        self.assertEqual(self.client.get("/api/sensors/other/current").status_code, 404)

    def test_bad_range_400(self) -> None:
        self.assertEqual(self.client.get("/api/sensors/porch/history?range=zzz").status_code, 400)

    def test_alerts_view_and_readonly_post(self) -> None:
        view = self.client.get("/api/alerts").get_json()
        self.assertFalse(view["enabled"])
        self.assertFalse(view["webhook_configured"])
        self.assertEqual(len(view["levels"]), 5)
        self.assertEqual(view["sensors"][0]["sensor_id"], "porch")
        self.assertEqual(self.client.post("/api/alerts", json={}).status_code, 403)

    def test_sse_stream_helper_emits_events(self) -> None:
        events = list(sse_current_stream(lambda: db.connect(self.db_path), self.cfg, 0, max_events=2))
        self.assertEqual(len(events), 2)
        self.assertTrue(events[0].startswith("data: "))
        self.assertTrue(events[0].endswith("\n\n"))
        payload = json.loads(events[0][len("data: "):].strip())
        self.assertEqual(payload["sensor_id"], "porch")

    def test_sse_endpoint_once(self) -> None:
        resp = self.client.get("/api/sensors/porch/stream?once=1")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.headers["Content-Type"].startswith("text/event-stream"))
        self.assertEqual(resp.headers["Cache-Control"], "no-cache")
        body = resp.get_data(as_text=True)
        self.assertTrue(body.startswith("data: "))
        payload = json.loads(body[len("data: "):].strip())
        self.assertEqual(payload["sensor_id"], "porch")

    def test_sse_unknown_sensor_404(self) -> None:
        self.assertEqual(self.client.get("/api/sensors/other/stream?once=1").status_code, 404)

    def test_continuous_mode_reports_sample_interval(self) -> None:
        cfg = Config(
            sensor=SensorConfig(mode="continuous", sample_interval_s=10, sht31=SHT31Config(enabled=True)),
            storage=self.cfg.storage,
            web=self.cfg.web,
            sync=self.cfg.sync,
            dashboard=self.cfg.dashboard,
        )
        payload = create_app(cfg).test_client().get("/api/sensors/porch/current").get_json()
        self.assertEqual(payload["sample_period_s"], 10)


if __name__ == "__main__":
    unittest.main()
