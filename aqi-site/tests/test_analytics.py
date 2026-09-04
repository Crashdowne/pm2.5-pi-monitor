import os
import tempfile
import time
import unittest

from aqi_site import analytics, db
from aqi_site.config import MaskConfig
from tests.seed import make_warehouse


class AnalyticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.path = os.path.join(cls.tmp.name, "pm25.db")
        cls.now = make_warehouse(cls.path)
        cls.mask_cfg = MaskConfig()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.conn = db.connect(self.path)

    def tearDown(self):
        self.conn.close()

    def test_read_only(self):
        with self.assertRaises(Exception):
            self.conn.execute("INSERT INTO readings_raw (sensor_id, ts) VALUES ('x', 1)")

    def test_distinct_sensors(self):
        self.assertEqual(db.distinct_sensors(self.conn), ["backyard", "rooftop", "smoky"])

    def test_current(self):
        data = analytics.current(self.conn, "backyard", self.mask_cfg)
        self.assertIsInstance(data["nowcast_aqi"], int)
        self.assertIn(data["mask"]["level"], {"none", "carry", "recommended", "strong", "indoors"})
        self.assertIn(data["trend"], {"improving", "worsening", "steady"})
        self.assertIsNotNone(data["temp"])

    def test_current_optional_env_falls_back(self):
        # rooftop has no pm2_5_corr / rh / temp -> COALESCE uses raw pm2_5.
        data = analytics.current(self.conn, "rooftop", self.mask_cfg)
        self.assertIsNone(data["rh"])
        self.assertIsNone(data["temp"])
        self.assertIsNotNone(data["pm2_5"])

    def test_smoky_hits_top_bands(self):
        data = analytics.current(self.conn, "smoky", self.mask_cfg)
        self.assertGreater(data["nowcast_aqi"], 200)
        self.assertEqual(data["mask"]["level"], "indoors")

    def test_history_shape(self):
        rows = analytics.history(self.conn, "backyard", "24h")
        self.assertGreater(len(rows), 0)
        self.assertEqual(set(rows[0]), {"t", "pm2_5", "pm10", "temp", "rh", "aqi"})
        self.assertTrue(all(rows[i]["t"] <= rows[i + 1]["t"] for i in range(len(rows) - 1)))

    def test_calendar(self):
        year = time.gmtime(self.now).tm_year
        rows = analytics.calendar(self.conn, "rooftop", year)
        self.assertGreater(len(rows), 0)
        self.assertRegex(rows[0]["date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_heatmap(self):
        cells = analytics.heatmap(self.conn, "backyard", "7d")
        self.assertTrue(cells)
        for hour, dow, value in cells:
            self.assertTrue(0 <= hour <= 23 and 0 <= dow <= 6)
            self.assertIsInstance(value, int)

    def test_distribution_sums_100(self):
        dist = analytics.distribution(self.conn, "backyard", "7d")
        self.assertEqual(len(dist), 6)
        self.assertAlmostEqual(sum(b["pct"] for b in dist), 100.0, delta=0.5)

    def test_diurnal_24(self):
        rows = analytics.diurnal(self.conn, "backyard", "7d")
        self.assertEqual([r["hour"] for r in rows], list(range(24)))

    def test_summary(self):
        s = analytics.summary(self.conn, "backyard")
        for key in ("pm25_24h", "aqi_7d", "cigarettes_30d", "peak_aqi_7d", "exceedance_hours_30d"):
            self.assertIn(key, s)
        self.assertGreaterEqual(s["cigarettes_30d"], 0)

    def test_sensors_overview(self):
        overview = analytics.sensors_overview(self.conn, self.mask_cfg)
        ids = {row["sensor_id"] for row in overview}
        self.assertEqual(ids, {"backyard", "rooftop", "smoky"})
        for row in overview:
            self.assertLessEqual(row["coverage_24h"], 100)
            self.assertIn("online", row)

    def test_current_online(self):
        data = analytics.current(self.conn, "backyard", self.mask_cfg)
        self.assertTrue(data["online"])
        self.assertFalse(data["stale"])
        self.assertEqual(data["sample_period_s"], 900)

    def test_diurnal_aqi_minmax(self):
        rows = [r for r in analytics.diurnal(self.conn, "backyard", "7d") if r["avg"] is not None]
        self.assertTrue(rows)
        self.assertIn("aqi_min", rows[0])
        self.assertIn("aqi_max", rows[0])
        self.assertLessEqual(rows[0]["aqi_min"], rows[0]["aqi_max"])

    def test_summary_by_period(self):
        s = analytics.summary(self.conn, "backyard")
        self.assertEqual([p["period"] for p in s["by_period"]], ["24h", "7d", "30d"])
        for p in s["by_period"]:
            self.assertIn("peak_aqi", p)
            self.assertIn("unhealthy_hours", p)
            self.assertIn("cigarettes", p)

    def test_status(self):
        st = analytics.status(self.conn, "backyard")
        self.assertTrue(st["online"])
        self.assertEqual(st["coverage_24h"]["pct"], 100)
        self.assertTrue(st["sht31"]["ok"])  # backyard reports temp + rh
        self.assertIn("gaps_7d", st)

    def test_status_sht31_absent(self):
        st = analytics.status(self.conn, "rooftop")
        self.assertFalse(st["sht31"]["ok"])  # rooftop has no temp/rh (SHT31 disabled)


if __name__ == "__main__":
    unittest.main()
