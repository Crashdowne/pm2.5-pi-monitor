import tempfile
import os
import time
import unittest
from pathlib import Path
from unittest import mock

from pm25 import db
from pm25.api import create_app
from pm25.config import Config, SensorConfig, SHT31Config, StorageConfig, SyncConfig, UpdateConfig, WebConfig


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
        db.insert_raw(
            conn,
            self.now,
            {"pm2_5": 10, "pm2_5_corr": 8, "pm10": 12, "rh": 48, "temp": 21},
        )
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

    def test_security_headers_present(self) -> None:
        response = self.client.get("/api/health")
        self.assertEqual(response.headers.get("X-Content-Type-Options"), "nosniff")
        self.assertIn("Content-Security-Policy", response.headers)

    def test_current_includes_health_and_supports_etag(self) -> None:
        response = self.client.get("/api/current")

        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(response.headers["Cache-Control"], "no-cache")
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
        self.assertEqual(payload["hourly"][0]["rh"], 48)
        self.assertEqual(payload["hourly"][0]["temp"], 21)
        self.assertEqual(payload["daily"][0]["rh"], 48)
        self.assertEqual(payload["daily"][0]["temp"], 21)
        self.assertEqual(payload["weekly"][0]["rh"], 48)
        self.assertEqual(payload["weekly"][0]["temp"], 21)

    def test_cadence_change_invalidates_current_etag(self) -> None:
        old_response = self.client.get("/api/current")
        updated_cfg = Config(
            sensor=SensorConfig(period_s=180, sht31=SHT31Config(enabled=True)),
            storage=self.cfg.storage,
            web=self.cfg.web,
            sync=self.cfg.sync,
        )
        updated_client = create_app(updated_cfg).test_client()

        response = updated_client.get(
            "/api/current", headers={"If-None-Match": old_response.headers["ETag"]}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["health"]["sample_period_s"], 180)


class UpdateApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.state = Path(self.tempdir.name) / "ota"
        self.state.mkdir()
        self.cfg = Config(
            sensor=SensorConfig(),
            storage=StorageConfig(db_path=str(Path(self.tempdir.name) / "pm25.db")),
            web=WebConfig(),
            sync=SyncConfig(),
            update=UpdateConfig(state_dir=str(self.state), token_env="PM25_TEST_UPDATE_TOKEN"),
        )
        env = mock.patch.dict(os.environ, {"PM25_TEST_UPDATE_TOKEN": "tok"})
        env.start()
        self.addCleanup(env.stop)
        self.client = create_app(self.cfg).test_client()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _post(self, addr: str = "127.0.0.1", token: str | None = "tok", **body):
        headers = {"Authorization": f"Bearer {token}"} if token is not None else {}
        return self.client.post("/api/update", json=body, headers=headers, environ_base={"REMOTE_ADDR": addr})

    def test_status_reports_actions(self) -> None:
        data = self.client.get("/api/update").get_json()
        self.assertEqual(data["actions"], ["pull", "apply_staged"])
        self.assertTrue(data["allow_web_trigger"])
        self.assertIsNone(data["pending_request"])

    def test_trusted_request_is_accepted_then_conflicts(self) -> None:
        resp = self._post(addr="100.100.5.6", action="apply_staged")
        self.assertEqual(resp.status_code, 202)
        self.assertEqual(resp.get_json()["requested"]["action"], "apply_staged")
        self.assertTrue((self.state / "request").exists())
        self.assertEqual(self._post().status_code, 409)

    def test_lan_peer_is_refused(self) -> None:
        self.assertEqual(self._post(addr="192.168.1.50").status_code, 403)
        self.assertFalse((self.state / "request").exists())

    def test_bad_or_missing_token_is_refused(self) -> None:
        self.assertEqual(self._post(token="nope").status_code, 401)
        self.assertEqual(self._post(token=None).status_code, 401)

    def test_bad_action_is_rejected(self) -> None:
        self.assertEqual(self._post(action="shell").status_code, 400)

    def test_disabled_trigger_is_refused(self) -> None:
        cfg = Config(
            sensor=SensorConfig(), storage=self.cfg.storage, web=WebConfig(), sync=SyncConfig(),
            update=UpdateConfig(state_dir=str(self.state), allow_web_trigger=False),
        )
        resp = create_app(cfg).test_client().post("/api/update", json={}, headers={"Authorization": "Bearer tok"})
        self.assertEqual(resp.status_code, 403)

if __name__ == "__main__":
    unittest.main()