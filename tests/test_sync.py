import os
import json
import tempfile
import time
import unittest
from pathlib import Path

from pm25 import db
from pm25.config import Config, SensorConfig, StorageConfig, SyncConfig, WebConfig
from pm25.sync import _prune, _push, run_once


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict:
        return self.payload


class FakeSession:
    def __init__(self) -> None:
        self.headers: dict = {}

    def post(self, _url: str, *, data: bytes, headers: dict, timeout: int) -> FakeResponse:
        self.headers = headers
        rows = [line for line in data.decode("utf-8").splitlines() if line]
        max_ts = max(json.loads(line)["ts"] for line in rows)
        return FakeResponse({"received": len(rows), "max_ts": max_ts})


class SyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "pm25.db")
        self.cfg = Config(
            sensor=SensorConfig(),
            storage=StorageConfig(db_path=self.db_path, raw_retention_days=30),
            web=WebConfig(),
            sync=SyncConfig(enabled=True, server_url="http://server", sensor_id="porch"),
        )
        self.conn = db.connect(self.db_path)
        db.init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()
        self.tempdir.cleanup()

    def test_push_verifies_ack_and_sends_sensor_identity(self) -> None:
        db.insert_raw(self.conn, 20, {"pm2_5": 8.1, "pm10": 11.2})
        self.conn.commit()
        session = FakeSession()
        os.environ["PM25_SYNC_TOKEN"] = "secret"
        self.addCleanup(os.environ.pop, "PM25_SYNC_TOKEN", None)

        _push(self.cfg, self.conn, session)  # type: ignore[arg-type]

        state = self.conn.execute("SELECT last_pushed_ts FROM sync_state WHERE id = 1").fetchone()
        self.assertEqual(state["last_pushed_ts"], 20)
        self.assertEqual(self.conn.execute("SELECT synced FROM readings_raw WHERE ts = 20").fetchone()[0], 1)
        self.assertEqual(session.headers["X-PM25-Sensor-ID"], "porch")

    def test_normal_pruning_uses_storage_retention(self) -> None:
        old_ts = int(time.time()) - 20 * 86400
        db.insert_raw(self.conn, old_ts, {"pm2_5": 8.1})
        self.conn.commit()
        cfg = Config(
            sensor=self.cfg.sensor,
            storage=StorageConfig(db_path=self.db_path, raw_retention_days=30),
            web=self.cfg.web,
            sync=SyncConfig(enabled=False, pressure_keep_days=1, trigger_db_size_mb=9999),
        )

        _prune(cfg, self.conn, 0)

        self.assertEqual(self.conn.execute("SELECT count(*) FROM readings_raw").fetchone()[0], 1)

    def test_enabled_sync_without_url_fails_closed(self) -> None:
        old_ts = int(time.time()) - 40 * 86400
        db.insert_raw(self.conn, old_ts, {"pm2_5": 8.1})
        self.conn.commit()
        cfg = Config(
            sensor=self.cfg.sensor,
            storage=StorageConfig(db_path=self.db_path, raw_retention_days=30),
            web=self.cfg.web,
            sync=SyncConfig(enabled=True, server_url=""),
        )

        self.assertFalse(run_once(cfg))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM readings_raw").fetchone()[0], 1)

    def test_clock_rollback_row_is_pushed_and_only_acknowledged_rows_prune(self) -> None:
        old_ts = int(time.time()) - 40 * 86400
        db.insert_raw(self.conn, old_ts + 100, {"pm2_5": 8.1})
        self.conn.execute("UPDATE readings_raw SET synced = 1 WHERE ts = ?", (old_ts + 100,))
        db.insert_raw(self.conn, old_ts, {"pm2_5": 9.1})
        self.conn.commit()
        os.environ["PM25_SYNC_TOKEN"] = "secret"
        self.addCleanup(os.environ.pop, "PM25_SYNC_TOKEN", None)

        _push(self.cfg, self.conn, FakeSession())  # type: ignore[arg-type]
        _prune(self.cfg, self.conn, int(time.time()))

        self.assertEqual(self.conn.execute("SELECT count(*) FROM readings_raw").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()