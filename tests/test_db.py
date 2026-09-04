import sqlite3
import unittest

from pm25 import db


class DatabaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        db.init_db(self.conn)

    def tearDown(self) -> None:
        self.conn.close()

    def test_rollups_prefer_corrected_average_without_losing_sample_count(self) -> None:
        db.insert_raw(self.conn, 3601, {"pm2_5": 20, "pm2_5_corr": 10, "pm10": 30})
        db.insert_raw(self.conn, 3661, {"pm2_5": 30, "pm2_5_corr": 20, "pm10": 40})
        db.update_rollups(self.conn, 3661)

        hourly = self.conn.execute("SELECT * FROM readings_hourly WHERE ts_hour = 3600").fetchone()
        daily = self.conn.execute("SELECT * FROM readings_daily WHERE ts_day = 0").fetchone()
        self.assertEqual(hourly["pm2_5_corr"], 15)
        self.assertEqual(hourly["samples"], 2)
        self.assertEqual(daily["samples"], 2)

    def test_init_migrates_pre_correction_tables(self) -> None:
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE readings_raw (ts INTEGER PRIMARY KEY, pm2_5 REAL)")

        db.init_db(conn)

        columns = {row[1] for row in conn.execute("PRAGMA table_info(readings_raw)")}
        self.assertIn("pm2_5_corr", columns)
        conn.close()

    def test_upsert_only_requeues_changed_measurements(self) -> None:
        db.insert_raw(self.conn, 100, {"pm2_5": 8.0, "pm10": 12.0})
        self.conn.execute("UPDATE readings_raw SET synced = 1 WHERE ts = 100")

        db.insert_raw(self.conn, 100, {"pm2_5": 8.0, "pm10": 12.0})
        self.assertEqual(self.conn.execute("SELECT synced FROM readings_raw").fetchone()[0], 1)

        db.insert_raw(self.conn, 100, {"pm2_5": 9.0, "pm10": 12.0})
        row = self.conn.execute("SELECT pm2_5, synced FROM readings_raw").fetchone()
        self.assertEqual((row["pm2_5"], row["synced"]), (9.0, 0))


if __name__ == "__main__":
    unittest.main()