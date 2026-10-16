import json
import tempfile
import unittest
from pathlib import Path

from pm25 import ota


class TrustedAddressTests(unittest.TestCase):
    def test_loopback_and_tailnet_are_trusted(self) -> None:
        for addr in ("127.0.0.1", "::1", "100.64.0.1", "100.101.102.103", "100.127.255.254",
                     "fd7a:115c:a1e0::1", "::ffff:100.100.1.1"):
            with self.subTest(addr=addr):
                self.assertTrue(ota.is_trusted_address(addr))

    def test_lan_public_and_garbage_are_refused(self) -> None:
        for addr in ("192.168.1.20", "10.0.0.5", "100.128.0.1", "8.8.8.8", "fe80::1", "", None, "not-an-ip"):
            with self.subTest(addr=addr):
                self.assertFalse(ota.is_trusted_address(addr))


class TokenTests(unittest.TestCase):
    def test_bearer_token_must_match(self) -> None:
        self.assertTrue(ota.token_matches("s3cret", "Bearer s3cret"))
        self.assertTrue(ota.token_matches("s3cret", "bearer s3cret "))
        self.assertFalse(ota.token_matches("s3cret", "Bearer wrong"))
        self.assertFalse(ota.token_matches("s3cret", "Basic s3cret"))
        self.assertFalse(ota.token_matches("s3cret", None))

    def test_empty_expected_token_never_matches(self) -> None:
        self.assertFalse(ota.token_matches("", "Bearer "))
        self.assertFalse(ota.token_matches("", "Bearer anything"))


class RequestTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_request_writes_file_and_blocks_duplicates(self) -> None:
        req = ota.request_update(self.dir, "apply_staged", now=1000)
        self.assertEqual(req, {"action": "apply_staged", "ts": 1000})
        self.assertEqual(json.loads((self.dir / ota.REQUEST_FILE).read_text()), req)
        self.assertEqual(list(self.dir.glob(".*.tmp")), [])
        with self.assertRaisesRegex(RuntimeError, "pending"):
            ota.request_update(self.dir, "pull")

    def test_unknown_action_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ota.request_update(self.dir, "rm -rf /")
        self.assertFalse((self.dir / ota.REQUEST_FILE).exists())

    def test_running_update_blocks_new_request(self) -> None:
        (self.dir / ota.STATUS_FILE).write_text(json.dumps({"state": "running"}))
        with self.assertRaisesRegex(RuntimeError, "running"):
            ota.request_update(self.dir, "pull")

    def test_read_status_merges_files_and_tolerates_garbage(self) -> None:
        (self.dir / ota.VERSION_FILE).write_text(json.dumps({"short": "abc1234"}))
        (self.dir / ota.STATUS_FILE).write_text("{not json")
        status = ota.read_status(self.dir)
        self.assertEqual(status["installed"], {"short": "abc1234"})
        self.assertEqual(status["last_run"], {})
        self.assertIsNone(status["pending_request"])
        self.assertTrue(status["package_version"])

        ota.request_update(self.dir, "pull", now=5)
        self.assertEqual(ota.read_status(self.dir)["pending_request"], {"action": "pull", "ts": 5})

    def test_read_status_on_missing_dir(self) -> None:
        status = ota.read_status(self.dir / "absent")
        self.assertEqual(status["installed"], {})
        self.assertIsNone(status["pending_request"])


if __name__ == "__main__":
    unittest.main()
