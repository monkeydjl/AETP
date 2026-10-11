"""Unit tests for the unified conformance runner."""

import os
import tempfile
import unittest

from conformance.definitions import CONFORMANCE_DEFINITIONS
from conformance.registry import FIXTURE_HANDLERS, register_fixture
from conformance.runner import run_conformance


class ConformanceRunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aetp-runner-test-")
        self.db_path = os.path.join(self.tmp, "runner_test.sqlite")

    def tearDown(self):
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            if os.path.exists(self.tmp):
                os.rmdir(self.tmp)
        except OSError:
            pass

    def test_conformance_definitions_count(self):
        """All 28 conformance tests must be defined."""
        self.assertEqual(len(CONFORMANCE_DEFINITIONS), 28)
        self.assertIn("TEST-001", CONFORMANCE_DEFINITIONS)
        self.assertIn("TEST-028", CONFORMANCE_DEFINITIONS)

    def test_run_conformance_rejects_existing_database(self):
        """Clean new database check."""
        with open(self.db_path, "w") as f:
            f.write("existing")
        with self.assertRaises(FileExistsError):
            run_conformance(self.db_path)

    def test_run_conformance_records_unregistered_tests_as_not_run(self):
        """A defined test with no registered fixture is recorded as not_run and pending."""
        from conformance.definitions import ConformanceDefinition
        CONFORMANCE_DEFINITIONS["TEST-999-PENDING"] = ConformanceDefinition(
            id="TEST-999-PENDING", title="Pending scope", section="0.0", invariant="PENDING", domain="test"
        )
        try:
            report = run_conformance(self.db_path, filter_ids=["TEST-999-PENDING"])
            self.assertEqual(report["counts"]["total"], 1)
            self.assertEqual(report["counts"]["not_run"], 1)
            self.assertEqual(report["results"]["TEST-999-PENDING"]["execution_status"], "not_run")
            self.assertEqual(report["results"]["TEST-999-PENDING"]["status"], "pending")
        finally:
            del CONFORMANCE_DEFINITIONS["TEST-999-PENDING"]

    def test_registered_fixture_executes_and_reports_passed(self):
        """A registered fixture with all §18.3 elements executes and reports passed."""
        @register_fixture("TEST-999-DUMMY")
        def dummy_handler(store, project_id):
            return {"status": "passed", "execution_status": "passed", "summary": "Dummy ok", "details": {"ok": True}}

        from conformance.definitions import ConformanceDefinition
        CONFORMANCE_DEFINITIONS["TEST-999-DUMMY"] = ConformanceDefinition(
            id="TEST-999-DUMMY", title="Dummy", section="0.0", invariant="DUMMY", domain="test",
            initial_state="s", input_surface="i", runtime_capability="r",
            fault_injection="f", expected="e", replay_result="p", fixture_kind="real_path",
        )
        try:
            report = run_conformance(self.db_path, filter_ids=["TEST-999-DUMMY"])
            self.assertEqual(report["counts"]["executed_passed"], 1)
            self.assertEqual(report["results"]["TEST-999-DUMMY"]["status"], "passed")
            self.assertEqual(report["results"]["TEST-999-DUMMY"]["execution_status"], "passed")
            self.assertTrue(report["results"]["TEST-999-DUMMY"]["evidence_digest"].startswith("sha256:"))
        finally:
            del CONFORMANCE_DEFINITIONS["TEST-999-DUMMY"]
            del FIXTURE_HANDLERS["TEST-999-DUMMY"]

    def test_missing_frozen_elements_fail_closed(self):
        """A registered fixture without the six §18.3 elements is refused, not passed."""
        @register_fixture("TEST-999-NOELEM")
        def dummy_handler(store, project_id):
            return {"status": "passed", "execution_status": "passed", "summary": "Should not be reached", "details": {}}

        from conformance.definitions import ConformanceDefinition
        CONFORMANCE_DEFINITIONS["TEST-999-NOELEM"] = ConformanceDefinition(
            id="TEST-999-NOELEM", title="No elements", section="0.0", invariant="X", domain="test",
        )
        try:
            report = run_conformance(self.db_path, filter_ids=["TEST-999-NOELEM"])
            entry = report["results"]["TEST-999-NOELEM"]
            self.assertEqual(entry["status"], "failed")
            self.assertEqual(entry["execution_status"], "failed")
            self.assertIn("missing_elements", entry["details"])
            self.assertEqual(len(entry["details"]["missing_elements"]), 6)
        finally:
            del CONFORMANCE_DEFINITIONS["TEST-999-NOELEM"]
            del FIXTURE_HANDLERS["TEST-999-NOELEM"]

    def test_frozen_snapshot_binds_elements_with_digests(self):
        """The frozen snapshot exposes per-test and suite digests over the elements."""
        report = run_conformance(self.db_path, filter_ids=["TEST-001", "TEST-028"])
        frozen = report["frozen_evidence"]
        self.assertEqual(frozen["element_keys"], [
            "initial_state", "input_surface", "runtime_capability",
            "fault_injection", "expected", "replay_result",
        ])
        self.assertTrue(frozen["suite_digest"].startswith("sha256:"))
        self.assertTrue(frozen["snapshot_digest"].startswith("sha256:"))
        for tid in ("TEST-001", "TEST-028"):
            entry = frozen["entries"][tid]
            self.assertTrue(entry["elements_digest"].startswith("sha256:"))
            for key in frozen["element_keys"]:
                self.assertTrue(entry["elements"][key].strip(), f"{tid}.{key} empty")
            self.assertEqual(entry["fixture_kind"], "real_path")

    def test_all_passed_fixtures_expose_nonempty_details(self):
        """Every executed Passed fixture must carry real runtime details (IMP-002)."""
        report = run_conformance(self.db_path)
        self.assertEqual(report["counts"]["total"], 28)
        self.assertEqual(report["counts"]["executed_passed"], 28)
        empty = [
            tid for tid, res in report["results"].items()
            if res["execution_status"] == "passed" and not res["details"]
        ]
        self.assertEqual(empty, [], f"passed fixtures with empty details: {sorted(empty)}")
