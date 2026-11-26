"""Unit test for TEST-028 Conformance Suite."""

import os
import tempfile
import unittest

from aetp.core.projection import Projection
from aetp.storage.sqlite_store import SQLiteStore
from conformance.m3.test_028 import run_test_028_scenario


class ConformanceTest028Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aetp-test-028-")
        self.db_path = os.path.join(self.tmp, "test_028.sqlite")

    def tearDown(self):
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            if os.path.exists(self.tmp):
                os.rmdir(self.tmp)
        except OSError:
            pass

    def test_run_test_028_full_scenario_success(self):
        """Execute TEST-028 equal agents negotiation and delivery scenario."""
        report = run_test_028_scenario(self.db_path)
        self.assertEqual(report["verdict"], "PASSED")
        self.assertEqual(report["conformance_test"], "TEST-028")
        self.assertTrue(report["events_count"] > 0)
        for step in report["steps_verified"]:
            self.assertEqual(step["status"], "passed", f"Step failed: {step}")

    def test_test_028_deterministic_event_replay_matches(self):
        """Events produced by TEST-028 can be deterministically replayed."""
        run_test_028_scenario(self.db_path)
        store = SQLiteStore.open(self.db_path)
        events = store.read_events("p-test-028")
        state = Projection.rebuild(events)
        store.close()
        self.assertEqual(state["mission:mission-ping"]["status"], "completed")
        self.assertEqual(state["team:team-ping"]["status"], "forming")
        self.assertEqual(state["blueprint:bp-ping"]["status"], "proposed")
        self.assertEqual(state["project:p-test-028"]["planning"]["mode"], "candidate_only")
