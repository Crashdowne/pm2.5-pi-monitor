import json
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

from server.ingest import create_app


class ServerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "warehouse.db")
        self.client = create_app(self.db_path, "", {"porch": "secret"}).test_client()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_device_token_is_scoped_to_sensor_id(self) -> None:
        reading_ts = int(time.time())
        payload = json.dumps({"ts": reading_ts, "pm2_5": 12.0, "pm10": 18.0})
        headers = {
            "Authorization": "Bearer secret",
            "X-PM25-Sensor-ID": "porch",
            "X-PM25-Sample-Period": "120",
            "Content-Type": "application/x-ndjson",
        }

        response = self.client.post("/ingest", data=payload, headers=headers)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["received"], 1)
        self.assertEqual(self.client.get("/max_ts", headers=headers).get_json()["max_ts"], reading_ts)
        denied = self.client.post("/ingest", data=payload, headers={**headers, "X-PM25-Sensor-ID": "garage"})
        self.assertEqual(denied.status_code, 401)

    def test_fleet_api_reports_ingested_device(self) -> None:
        reading_ts = int(time.time())
        headers = {"Authorization": "Bearer secret", "X-PM25-Sensor-ID": "porch"}
        self.client.post(
            "/ingest",
            data=json.dumps({"ts": reading_ts, "pm2_5": 10.0, "pm10": 14.0, "rh": 45.0, "temp": 21.0}),
            headers=headers,
        )

        response = self.client.get("/api/fleet")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()[0]["sensor_id"], "porch")
        self.assertIn("ETag", response.headers)
        history = self.client.get("/api/sensors/porch/history?range=24h").get_json()
        self.assertEqual(history[0]["rh"], 45.0)
        self.assertEqual(history[0]["temp"], 21.0)

    def test_existing_single_sensor_database_is_migrated(self) -> None:
        legacy_path = str(Path(self.tempdir.name) / "legacy.db")
        conn = sqlite3.connect(legacy_path)
        conn.execute(
            "CREATE TABLE readings_raw (ts INTEGER PRIMARY KEY, pm1_0 REAL, pm2_5 REAL, pm10 REAL, "
            "pm2_5_corr REAL, n0_3 INTEGER, n0_5 INTEGER, n1_0 INTEGER, n2_5 INTEGER, "
            "n5_0 INTEGER, n10 INTEGER, rh REAL, temp REAL)"
        )
        conn.execute("INSERT INTO readings_raw (ts, pm2_5, pm10) VALUES (100, 8, 12)")
        conn.commit()
        conn.close()

        create_app(legacy_path, "secret")

        conn = sqlite3.connect(legacy_path)
        migrated = conn.execute("SELECT sensor_id, ts FROM readings_raw").fetchone()
        conn.close()
        self.assertEqual(migrated, ("default", 100))

    def test_sparse_legacy_database_is_migrated_without_data_loss(self) -> None:
        legacy_path = str(Path(self.tempdir.name) / "sparse-legacy.db")
        conn = sqlite3.connect(legacy_path)
        conn.execute("CREATE TABLE readings_raw (ts INTEGER PRIMARY KEY, pm2_5 REAL, pm10 REAL)")
        conn.execute("INSERT INTO readings_raw VALUES (100, 8, 12)")
        conn.commit()
        conn.close()

        create_app(legacy_path, "secret")

        conn = sqlite3.connect(legacy_path)
        migrated = conn.execute("SELECT sensor_id, ts, pm2_5, rh FROM readings_raw").fetchone()
        conn.close()
        self.assertEqual(migrated, ("default", 100, 8, None))

    def test_malformed_measurement_rejects_entire_batch(self) -> None:
        now = int(time.time())
        headers = {"Authorization": "Bearer secret", "X-PM25-Sensor-ID": "porch"}
        payload = "\n".join(
            (
                json.dumps({"ts": now, "pm2_5": 10.0, "pm10": 12.0}),
                json.dumps({"ts": now + 1, "pm2_5": "invalid", "pm10": 12.0}),
            )
        )

        response = self.client.post("/ingest", data=payload, headers=headers)

        self.assertEqual(response.status_code, 400)
        conn = sqlite3.connect(self.db_path)
        count = conn.execute("SELECT count(*) FROM readings_raw").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_malformed_gzip_is_rejected(self) -> None:
        headers = {
            "Authorization": "Bearer secret",
            "X-PM25-Sensor-ID": "porch",
            "Content-Encoding": "gzip",
        }

        response = self.client.post("/ingest", data=b"not a gzip stream", headers=headers)

        self.assertEqual(response.status_code, 400)

    def test_unused_global_timestamp_index_is_removed(self) -> None:
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE INDEX idx_readings_raw_ts ON readings_raw(ts)")
        conn.commit()
        conn.close()

        create_app(self.db_path, "", {"porch": "secret"})

        conn = sqlite3.connect(self.db_path)
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(readings_raw)")}
        conn.close()
        self.assertNotIn("idx_readings_raw_ts", indexes)

    def test_read_endpoints_require_basic_auth_when_read_token_set(self) -> None:
        import base64

        client = create_app(self.db_path, "", {"porch": "secret"}, read_token="letmein").test_client()
        denied = client.get("/api/fleet")
        self.assertEqual(denied.status_code, 401)
        self.assertIn("WWW-Authenticate", denied.headers)

        cred = base64.b64encode(b"viewer:letmein").decode()
        allowed = client.get("/api/fleet", headers={"Authorization": f"Basic {cred}"})
        self.assertEqual(allowed.status_code, 200)

        # ingest keeps its own bearer token, independent of the read token
        ping = client.get("/max_ts", headers={"Authorization": "Bearer secret", "X-PM25-Sensor-ID": "porch"})
        self.assertEqual(ping.status_code, 200)

    def test_security_headers_present_on_responses(self) -> None:
        response = self.client.get("/api/fleet")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("Content-Security-Policy", response.headers)


if __name__ == "__main__":
    unittest.main()