import json
import time
import unittest
from pathlib import Path

from werkzeug.exceptions import HTTPException

from server import ingest

CONTRACT = json.loads(
    (Path(__file__).resolve().parents[1] / "contracts" / "ingest_ranges.json").read_text()
)


class IngestContractTests(unittest.TestCase):
    """Guard parity between the warehouse validator and the shared ingest contract."""

    def test_value_ranges_match_shared_contract(self) -> None:
        expected = {key: tuple(value) for key, value in CONTRACT["value_ranges"].items()}
        self.assertEqual(ingest.VALUE_RANGES, expected)

    def test_raw_columns_match_contract_keys(self) -> None:
        self.assertEqual(set(ingest.RAW_COLS), set(CONTRACT["value_ranges"]))

    def test_body_limit_matches_shared_contract(self) -> None:
        self.assertEqual(ingest.MAX_BODY, CONTRACT["max_body_bytes"])

    def test_validated_record_enforces_contract_bounds(self) -> None:
        now = int(time.time())
        clean = ingest._validated_record({"ts": now, "pm2_5": 12.3, "pm10": 20.0}, now)
        self.assertEqual(clean["ts"], now)
        self.assertEqual(clean["pm2_5"], 12.3)

        floor = ingest._validated_record({"ts": CONTRACT["ts_min"], "pm2_5": 5.0}, now)
        self.assertEqual(floor["ts"], CONTRACT["ts_min"])

        with self.assertRaises(HTTPException):
            ingest._validated_record({"ts": now, "pm2_5": 99999.0}, now)
        with self.assertRaises(HTTPException):
            ingest._validated_record({"ts": CONTRACT["ts_min"] - 1, "pm2_5": 5.0}, now)


if __name__ == "__main__":
    unittest.main()
