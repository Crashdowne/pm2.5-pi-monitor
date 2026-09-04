import os
import tempfile
import unittest

from aqi_site import alerts
from aqi_site.config import AlertsConfig, Config
from tests.seed import make_warehouse


class DecisionTests(unittest.TestCase):
    def setUp(self):
        self.cfg = AlertsConfig(notify_from="recommended", min_interval_s=3600)

    def test_below_threshold(self):
        fire, reason = alerts.should_fire("none", "carry", self.cfg, 0, 10_000)
        self.assertFalse(fire)
        self.assertEqual(reason, "below-threshold")

    def test_escalation(self):
        fire, reason = alerts.should_fire("none", "strong", self.cfg, 0, 10_000)
        self.assertTrue(fire)
        self.assertEqual(reason, "escalated")

    def test_reminder_after_interval(self):
        fire, reason = alerts.should_fire("strong", "strong", self.cfg, 0, 10_000)
        self.assertTrue(fire)
        self.assertEqual(reason, "reminder")

    def test_debounced(self):
        fire, reason = alerts.should_fire("strong", "strong", self.cfg, 9_000, 10_000)
        self.assertFalse(fire)
        self.assertEqual(reason, "debounced")

    def test_quiet_hours(self):
        wrap = AlertsConfig(quiet_start_hour=22, quiet_end_hour=7)
        self.assertTrue(alerts.in_quiet_hours(23 * 3600, wrap))
        self.assertTrue(alerts.in_quiet_hours(3 * 3600, wrap))
        self.assertFalse(alerts.in_quiet_hours(12 * 3600, wrap))
        self.assertFalse(alerts.in_quiet_hours(12 * 3600, AlertsConfig()))


class StateAndPollTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = os.path.join(self.tmp.name, "pm25.db")
        self.state_path = os.path.join(self.tmp.name, "state.db")
        make_warehouse(self.db_path)
        self.config = Config(
            db_path=self.db_path,
            state_db_path=self.state_path,
            alerts=AlertsConfig(enabled=True, notify_from="recommended", min_interval_s=3600),
        )

    def test_overrides_roundtrip(self):
        state = alerts.open_state(self.state_path)
        self.addCleanup(state.close)
        alerts.save_overrides(state, {"enabled": True, "notify_from": "strong", "bogus": 1})
        loaded = alerts.load_overrides(state)
        self.assertEqual(loaded, {"enabled": True, "notify_from": "strong"})

    def test_poll_fires_then_debounces(self):
        sent_calls = []
        original = alerts.notify
        alerts.notify = lambda cfg, sid, snap: sent_calls.append(sid) or True
        try:
            state = alerts.open_state(self.state_path)
            self.addCleanup(state.close)
            first = alerts.poll_once(self.config, state)
            second = alerts.poll_once(self.config, state)
        finally:
            alerts.notify = original
        self.assertIn("smoky", sent_calls)
        fired_first = {e["sensor_id"] for e in first if e["sent"]}
        self.assertIn("smoky", fired_first)
        self.assertFalse(any(e["sent"] for e in second))

    def test_poll_disabled_noop(self):
        config = Config(db_path=self.db_path, state_db_path=self.state_path)
        state = alerts.open_state(self.state_path)
        self.addCleanup(state.close)
        self.assertEqual(alerts.poll_once(config, state), [])


if __name__ == "__main__":
    unittest.main()
