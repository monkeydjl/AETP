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

    def test_every_defined_test_has_a_registered_fixture(self):
        """No definition may sit in the suite without something to execute it.

        Without this guard a definition can be added and never wired, and the
        runner reports it as pending while the suite still calls itself green.
        """
        import conformance.fixtures  # noqa: F401  registers the fixtures

        unwired = sorted(tid for tid in CONFORMANCE_DEFINITIONS if tid not in FIXTURE_HANDLERS)
        self.assertEqual(unwired, [], f"defined but no fixture handler: {unwired}")

    def test_a_test_that_never_ran_is_not_reported_as_all_passed(self):
        """A defined test with no fixture executed nothing, so the suite did not pass.

        Same defect class as `unittest discover` skipping a directory: an
        unexecuted test must not read as a pass.
        """
        from conformance.definitions import ConformanceDefinition
        CONFORMANCE_DEFINITIONS["TEST-999-NORUN"] = ConformanceDefinition(
            id="TEST-999-NORUN", title="Never wired", section="0.0", invariant="NORUN", domain="test"
        )
        try:
            report = run_conformance(self.db_path, filter_ids=["TEST-999-NORUN"])
            self.assertEqual(report["counts"]["not_run"], 1)
            self.assertFalse(
                report["all_passed"],
                "a test that executed nothing must not count as passed",
            )
        finally:
            del CONFORMANCE_DEFINITIONS["TEST-999-NORUN"]

    def test_cli_exits_nonzero_when_a_test_never_ran(self):
        """The exit code must agree with all_passed: an unrun test is not success.

        Without this, a suite that skipped a test still exits 0 and any CI or
        script wrapping the command reads an empty run as a green one.
        """
        from conformance.definitions import ConformanceDefinition
        from conformance.runner import main

        db = os.path.join(self.tmp, "cli_norun.sqlite")
        CONFORMANCE_DEFINITIONS["TEST-999-NORUN-CLI"] = ConformanceDefinition(
            id="TEST-999-NORUN-CLI", title="Never wired", section="0.0", invariant="NORUN", domain="test"
        )
        try:
            code = main(["--db", db, "--filter", "TEST-999-NORUN-CLI"])
            self.assertNotEqual(code, 0, "a suite with an unrun test must not exit 0")
        finally:
            del CONFORMANCE_DEFINITIONS["TEST-999-NORUN-CLI"]
            if os.path.exists(db):
                os.remove(db)

    def test_filter_matching_nothing_fails_closed(self):
        """A filter that names no defined test executed nothing, so it is not a pass.

        A typo in a CI filter would otherwise leave the whole suite green while
        running zero tests - the same "unrun reads as passed" defect.
        """
        db = os.path.join(self.tmp, "filter_matches_nothing.sqlite")
        try:
            report = run_conformance(db, filter_ids=["TEST-999-NOT-DEFINED-ANYWHERE"])
            self.assertEqual(report["counts"]["total"], 0)
            self.assertFalse(
                report["all_passed"],
                "a run that executed no test at all must not report all-passed",
            )
        finally:
            if os.path.exists(db):
                os.remove(db)

    def test_an_unaccounted_execution_status_is_not_a_pass(self):
        """Every result must land in exactly one count, or it silently disappears.

        The counts are derived from exact string matches on execution_status. A
        fixture reporting any other value makes its result invisible: total says
        one test ran, the three counters say none did, and the suite reads green.
        """
        @register_fixture("TEST-999-SKIPPED")
        def skipped_handler(store, project_id):
            return {"status": "pending", "execution_status": "skipped", "summary": "Skipped", "details": {}}

        from conformance.definitions import ConformanceDefinition
        CONFORMANCE_DEFINITIONS["TEST-999-SKIPPED"] = ConformanceDefinition(
            id="TEST-999-SKIPPED", title="Skipped", section="0.0", invariant="SKIPPED", domain="test",
            initial_state="s", input_surface="i", runtime_capability="r",
            fault_injection="f", expected="e", replay_result="p", fixture_kind="real_path",
        )
        db = os.path.join(self.tmp, "unaccounted_status.sqlite")
        try:
            report = run_conformance(db, filter_ids=["TEST-999-SKIPPED"])
            counts = report["counts"]
            self.assertEqual(counts["total"], 1)
            self.assertEqual(
                counts["executed_passed"] + counts["executed_failed"] + counts["not_run"],
                counts["total"],
                f"every result must be counted exactly once, got {counts}",
            )
            self.assertFalse(
                report["all_passed"],
                "a result that fell outside every counter must not count as passed",
            )
        finally:
            del CONFORMANCE_DEFINITIONS["TEST-999-SKIPPED"]
            del FIXTURE_HANDLERS["TEST-999-SKIPPED"]
            if os.path.exists(db):
                os.remove(db)

    def test_a_fixture_reporting_failed_status_is_not_all_passed(self):
        """execution_status is not the whole story.

        A fixture can report status='failed' while claiming execution_status='passed'.
        Both axes must be clean, or the suite calls a self-reported failure a pass.
        """
        @register_fixture("TEST-999-CONTRADICT")
        def contradict_handler(store, project_id):
            return {
                "status": "failed",
                "execution_status": "passed",
                "summary": "Reports a failed status while claiming it executed fine",
                "details": {},
            }

        from conformance.definitions import ConformanceDefinition
        CONFORMANCE_DEFINITIONS["TEST-999-CONTRADICT"] = ConformanceDefinition(
            id="TEST-999-CONTRADICT", title="Contradiction", section="0.0", invariant="X", domain="test",
            initial_state="s", input_surface="i", runtime_capability="r",
            fault_injection="f", expected="e", replay_result="p", fixture_kind="real_path",
        )
        db = os.path.join(self.tmp, "contradict.sqlite")
        try:
            report = run_conformance(db, filter_ids=["TEST-999-CONTRADICT"])
            self.assertEqual(report["counts"]["status_failed"], 1)
            self.assertFalse(
                report["all_passed"],
                "a fixture that reports status='failed' must not be counted as all passed",
            )
        finally:
            del CONFORMANCE_DEFINITIONS["TEST-999-CONTRADICT"]
            del FIXTURE_HANDLERS["TEST-999-CONTRADICT"]
            if os.path.exists(db):
                os.remove(db)

    def test_cli_refuses_a_filter_naming_an_undefined_test(self):
        """A partially-matching filter must not silently run only the ids it recognised.

        `--filter TEST-001,TEST-999-BOGUS` dropped the unknown id and exited 0, which
        is the same "quietly ran less than asked" shape as discovery skipping a directory.
        """
        from conformance.runner import main

        db = os.path.join(self.tmp, "filter_mix.sqlite")
        try:
            code = main(["--db", db, "--filter", "TEST-001,TEST-999-BOGUS"])
            self.assertNotEqual(code, 0, "a filter naming an undefined test must not exit 0")
        finally:
            if os.path.exists(db):
                os.remove(db)

    def test_cli_exit_code_follows_all_passed(self):
        """The exit code must be driven by all_passed, not by a second copy of its logic.

        They were two separate expressions; extending the status enumeration made
        them disagree (all_passed False, exit 0). One source, one answer.
        """
        from unittest import mock

        import conformance.runner as cr

        healthy_counts = {
            "total": 1, "executed_passed": 1, "executed_failed": 0, "not_run": 0,
            "status_passed": 1, "status_pending": 0, "status_failed": 0,
        }
        fake = {"counts": healthy_counts, "all_passed": False}
        db = os.path.join(self.tmp, "follows_all_passed.sqlite")
        try:
            with mock.patch.object(cr, "run_conformance", return_value=fake):
                code = cr.main(["--db", db, "--summary"])
            self.assertNotEqual(code, 0, "exit code must follow all_passed, even when counts look clean")
        finally:
            if os.path.exists(db):
                os.remove(db)

    def test_a_status_outside_the_enum_is_not_a_pass(self):
        """`status` is matched by exact string, so an unlisted value vanishes from the counters."""
        @register_fixture("TEST-999-ODDSTATUS")
        def odd_status_handler(store, project_id):
            return {
                "status": "not_a_status_anyone_defined",
                "execution_status": "passed",
                "summary": "Odd status",
                "details": {},
            }

        from conformance.definitions import ConformanceDefinition
        CONFORMANCE_DEFINITIONS["TEST-999-ODDSTATUS"] = ConformanceDefinition(
            id="TEST-999-ODDSTATUS", title="Odd status", section="0.0", invariant="ODD", domain="test",
            initial_state="s", input_surface="i", runtime_capability="r",
            fault_injection="f", expected="e", replay_result="p", fixture_kind="real_path",
        )
        db = os.path.join(self.tmp, "odd_status.sqlite")
        try:
            report = run_conformance(db, filter_ids=["TEST-999-ODDSTATUS"])
            self.assertFalse(report["all_passed"], "an unlisted status must not read as passed")
        finally:
            del CONFORMANCE_DEFINITIONS["TEST-999-ODDSTATUS"]
            del FIXTURE_HANDLERS["TEST-999-ODDSTATUS"]
            if os.path.exists(db):
                os.remove(db)

    def test_a_missing_execution_status_is_not_a_pass(self):
        """Omitting the key must not default to success - absence is not evidence of passing."""
        @register_fixture("TEST-999-NOKEY")
        def no_key_handler(store, project_id):
            return {"status": "failed", "summary": "Reported failed but forgot execution_status", "details": {}}

        from conformance.definitions import ConformanceDefinition
        CONFORMANCE_DEFINITIONS["TEST-999-NOKEY"] = ConformanceDefinition(
            id="TEST-999-NOKEY", title="No key", section="0.0", invariant="NOKEY", domain="test",
            initial_state="s", input_surface="i", runtime_capability="r",
            fault_injection="f", expected="e", replay_result="p", fixture_kind="real_path",
        )
        db = os.path.join(self.tmp, "missing_key.sqlite")
        try:
            report = run_conformance(db, filter_ids=["TEST-999-NOKEY"])
            self.assertNotEqual(
                report["results"]["TEST-999-NOKEY"]["execution_status"], "passed",
                "a fixture that omits execution_status must not be recorded as passed",
            )
            self.assertFalse(report["all_passed"], "a result missing its execution_status must not pass")
        finally:
            del CONFORMANCE_DEFINITIONS["TEST-999-NOKEY"]
            del FIXTURE_HANDLERS["TEST-999-NOKEY"]
            if os.path.exists(db):
                os.remove(db)

    def test_a_fixture_kind_outside_the_documented_enum_is_not_a_pass(self):
        """`fixture_kind` is declared, never validated, and then republished.

        The field carries exactly two documented values, and the frozen snapshot
        republishes whatever the definition says. For a reader of that snapshot it
        is the only signal of how strong the evidence behind a result is, so a
        definition carrying a blank or invented kind advertises evidence strength
        that was never established - the same shape as a status outside its enum.
        """
        # A rejected fixture_kind must fail closed: the fixture must not run, so
        # the result carries no effect a reader could mistake for evidence.
        ran = []

        @register_fixture("TEST-999-ODDKIND")
        def odd_kind_handler(store, project_id):
            ran.append(True)
            return {"status": "passed", "execution_status": "passed", "summary": "Passed", "details": {"k": 1}}

        from conformance.definitions import ConformanceDefinition
        CONFORMANCE_DEFINITIONS["TEST-999-ODDKIND"] = ConformanceDefinition(
            id="TEST-999-ODDKIND", title="Odd kind", section="0.0", invariant="ODDKIND", domain="test",
            initial_state="s", input_surface="i", runtime_capability="r",
            fault_injection="f", expected="e", replay_result="p",
            fixture_kind="totally_made_up_kind",
        )
        db = os.path.join(self.tmp, "odd_kind.sqlite")
        try:
            report = run_conformance(db, filter_ids=["TEST-999-ODDKIND"])
            self.assertEqual(report["results"]["TEST-999-ODDKIND"]["status"], "failed")
            self.assertEqual(ran, [], "the fixture ran despite an unusable fixture_kind")
            self.assertFalse(report["all_passed"], "a fixture_kind outside the enum must not read as passed")
        finally:
            del CONFORMANCE_DEFINITIONS["TEST-999-ODDKIND"]
            del FIXTURE_HANDLERS["TEST-999-ODDKIND"]
            if os.path.exists(db):
                os.remove(db)

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
