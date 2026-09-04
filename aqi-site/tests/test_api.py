import os
import tempfile
import unittest

from aqi_site.api import create_app
from aqi_site.config import Config
from tests.seed import make_warehouse


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.db_path = os.path.join(cls.tmp.name, "pm25.db")
        cls.state_path = os.path.join(cls.tmp.name, "state.db")
        make_warehouse(cls.db_path)
        cls.config = Config(db_path=cls.db_path, state_db_path=cls.state_path)
        cls.app = create_app(cls.config)
        cls.client = cls.app.test_client()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_healthz(self):
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_config(self):
        body = self.client.get("/api/config").get_json()
        self.assertEqual(body["mask"]["sensitivity"], "asthma")
        self.assertIn("asthma", body["mask"]["presets"])
        self.assertIn("24h", body["ranges"])

    def test_sensors(self):
        body = self.client.get("/api/sensors").get_json()
        self.assertEqual({s["sensor_id"] for s in body}, {"backyard", "rooftop", "smoky"})

    def test_current_default_sensor(self):
        resp = self.client.get("/api/sensors/backyard/current")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json()["sensor_id"], "backyard")

    def test_history_and_bucket(self):
        body = self.client.get("/api/sensors/backyard/history?range=24h&bucket=1800").get_json()
        self.assertGreater(len(body), 0)

    def test_invalid_range(self):
        self.assertEqual(self.client.get("/api/sensors/backyard/history?range=nope").status_code, 400)

    def test_unknown_sensor(self):
        self.assertEqual(self.client.get("/api/sensors/ghost/current").status_code, 404)

    def test_invalid_sensor_id(self):
        self.assertEqual(self.client.get("/api/sensors/bad id!/current").status_code, 400)

    def test_calendar_heatmap_distribution_diurnal_summary(self):
        for path in (
            "/api/sensors/backyard/calendar",
            "/api/sensors/backyard/heatmap?range=7d",
            "/api/sensors/backyard/distribution?range=7d",
            "/api/sensors/backyard/diurnal?range=7d",
            "/api/sensors/backyard/summary",
            "/api/sensors/backyard/mask",
        ):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_export_csv(self):
        resp = self.client.get("/api/sensors/backyard/export?range=24h&format=csv")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/csv", resp.headers["Content-Type"])
        self.assertIn("iso_utc", resp.get_data(as_text=True).splitlines()[0])

    def test_export_json(self):
        resp = self.client.get("/api/sensors/backyard/export?range=24h&format=json")
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.get_json(), list)

    def test_alerts_get_post(self):
        self.assertEqual(self.client.get("/api/alerts").get_json()["enabled"], False)
        resp = self.client.post("/api/alerts", json={"enabled": True, "notify_from": "strong"})
        body = resp.get_json()
        self.assertTrue(body["enabled"])
        self.assertEqual(body["notify_from"], "strong")

    def test_alerts_post_rejects_bad_level(self):
        self.assertEqual(
            self.client.post("/api/alerts", json={"notify_from": "bogus"}).status_code, 400
        )

    def test_db_unavailable_503(self):
        app = create_app(Config(db_path="/nonexistent/pm25.db"))
        self.assertEqual(app.test_client().get("/healthz").status_code, 503)
        self.assertEqual(app.test_client().get("/api/sensors").status_code, 503)


if __name__ == "__main__":
    unittest.main()
