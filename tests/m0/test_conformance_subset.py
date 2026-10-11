"""M0-06 RED-first tests: real fixture execution, honest scope and safe evidence."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from aetp.core.commands import CommandHandler

try:
    import conformance.m0.runner as runner
except ModuleNotFoundError as exc:
    if exc.name not in {"conformance", "conformance.m0", "conformance.m0.runner"}:
        raise
    runner = None

ROOT = Path(__file__).resolve().parents[2]
PASSED = {"TEST-001", "TEST-002", "TEST-005", "TEST-017", "TEST-018", "TEST-021"}
PARTIAL = {"TEST-012", "TEST-016", "TEST-019"}
ALL_IDS = {f"TEST-{number:03d}" for number in range(1, 29)}


class ConformanceSubsetTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(runner, "M0 Conformance runner behavior is not implemented")
        self.tempdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tempdir.cleanup)
        self.directory = Path(self.tempdir.name)
        self.db = self.directory / "m0.sqlite"
        self.evidence = self.directory / "evidence"

    def run_subset(self):
        return runner.run_m0_conformance(str(self.db), evidence_dir=self.evidence)

    def observation(self, entry):
        path = Path(entry["evidence"])
        self.assertTrue(path.is_file())
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), entry["evidence_sha256"])
        return json.loads(path.read_text(encoding="utf-8"))

    def test_executes_kernel_requirements_without_promoting_partial_or_future_work(self):
        report = self.run_subset()
        self.assertEqual(set(report), ALL_IDS)
        for test_id, entry in report.items():
            with self.subTest(test_id=test_id):
                expected = "passed" if test_id in PASSED else "pending" if test_id in PARTIAL else "not_applicable"
                self.assertEqual(entry["status"], expected)
                self.assertTrue(entry["requirement"])
                self.assertTrue(entry["scope"])
                if test_id not in PASSED:
                    self.assertTrue(entry["limitations"])
                if test_id in PASSED | PARTIAL:
                    self.assertEqual(entry["execution"]["status"], "passed")
                    self.assertEqual(entry["execution"]["tests_run"], 1)
                else:
                    self.assertEqual(entry["execution"]["status"], "not_run")
                    self.assertEqual(entry["execution"]["tests_run"], 0)
                    self.assertIsNone(entry["raw_output"])

    def test_executed_evidence_has_real_inputs_faults_observations_and_raw_output(self):
        report = self.run_subset()
        for test_id in sorted(PASSED | PARTIAL):
            with self.subTest(test_id=test_id):
                entry = report[test_id]
                evidence = self.observation(entry)
                self.assertEqual(evidence["test_id"], test_id)
                self.assertTrue(evidence["initial_events"])
                self.assertTrue(evidence["commands"])
                self.assertTrue(evidence["fault_injection"])
                self.assertTrue(evidence["checks"])
                self.assertTrue(all(check["passed"] for check in evidence["checks"]))
                self.assertTrue(evidence["replay_state"])
                self.assertEqual(evidence["runtime_capabilities"]["real_adapters"], [])
                raw = Path(entry["raw_output"])
                self.assertEqual(hashlib.sha256(raw.read_bytes()).hexdigest(), entry["raw_output_sha256"])
                self.assertIn("Ran 1 test", raw.read_text(encoding="utf-8"))
                self.assertIn("OK", raw.read_text(encoding="utf-8"))
        # --db is the actual fixture database, not a decorative ignored argument.
        with contextlib.closing(sqlite3.connect(self.db)) as connection:
            projects = {row[0] for row in connection.execute("SELECT DISTINCT project_id FROM events")}
        self.assertEqual(projects, {"m0-" + test_id.lower() for test_id in PASSED | PARTIAL})

    def test_fixture_failure_is_derived_from_a_real_product_regression(self):
        original = CommandHandler.handle
        seen = set()

        def break_retry(handler, command, **kwargs):
            result = original(handler, command, **kwargs)
            key = (command.project_id, command.id)
            repeated = key in seen
            seen.add(key)
            if command.project_id == "m0-test-001" and repeated:
                return replace(result, command_id=result.command_id + "-wrong-result")
            return result

        with patch.object(CommandHandler, "handle", break_retry):
            report = self.run_subset()
        self.assertEqual(report["TEST-001"]["status"], "failed")
        self.assertEqual(report["TEST-001"]["execution"]["failures"], 1)
        self.assertIn("wrong-result", Path(report["TEST-001"]["raw_output"]).read_text(encoding="utf-8"))
        self.assertEqual(report["TEST-005"]["status"], "passed")

    def test_partial_fixture_failure_is_not_hidden_behind_pending(self):
        original = CommandHandler.handle

        def trust_claimed_actor(handler, command, **kwargs):
            if command.project_id == "m0-test-016":
                kwargs["authenticated_actor_id"] = command.actor_id
            return original(handler, command, **kwargs)

        with patch.object(CommandHandler, "handle", trust_claimed_actor):
            report = self.run_subset()
        self.assertEqual(report["TEST-016"]["status"], "failed")
        self.assertEqual(report["TEST-016"]["execution"]["failures"], 1)
        self.assertTrue(report["TEST-016"]["limitations"])

    def test_skip_cannot_be_reported_as_passed(self):
        def skip(case):
            case.skipTest("injected missing capability")
        with patch.object(runner._CoreFixtures, "test_001", skip):
            report = self.run_subset()
        self.assertEqual(report["TEST-001"]["status"], "failed")
        self.assertEqual(report["TEST-001"]["execution"]["skipped"], 1)

    def test_expected_failure_cannot_be_reported_as_passed(self):
        @unittest.expectedFailure
        def expected_failure(case):
            case.fail("injected known failure")
        with patch.object(runner._CoreFixtures, "test_001", expected_failure):
            report = self.run_subset()
        self.assertEqual(report["TEST-001"]["status"], "failed")
        self.assertEqual(report["TEST-001"]["execution"]["expected_failures"], 1)

    def test_unexpected_success_cannot_be_reported_as_passed(self):
        @unittest.expectedFailure
        def unexpected_success(case):
            pass
        with patch.object(runner._CoreFixtures, "test_001", unexpected_success):
            report = self.run_subset()
        self.assertEqual(report["TEST-001"]["status"], "failed")
        self.assertEqual(report["TEST-001"]["execution"]["unexpected_successes"], 1)

    def test_noop_fixture_cannot_turn_test_presence_into_evidence(self):
        with patch.object(runner._CoreFixtures, "test_001", lambda case: None):
            report = self.run_subset()
        entry = report["TEST-001"]
        self.assertEqual(entry["status"], "failed")
        self.assertFalse(entry["execution"]["fixture_complete"])
        self.assertIn("incomplete", Path(entry["raw_output"]).read_text(encoding="utf-8").lower())

    def test_fixture_error_is_recorded_and_other_cases_still_run(self):
        def broken(case):
            raise RuntimeError("injected fixture error")
        with patch.object(runner._CoreFixtures, "test_001", broken):
            report = self.run_subset()
        self.assertEqual(report["TEST-001"]["execution"]["errors"], 1)
        self.assertEqual(report["TEST-001"]["status"], "failed")
        self.assertEqual(report["TEST-021"]["status"], "passed")

    def test_zero_test_execution_cannot_be_reported_as_passed(self):
        original = unittest.TextTestRunner.run

        def empty_first(text_runner, suite):
            if any(getattr(case, "_testMethodName", None) == "test_001" for case in suite):
                return original(text_runner, unittest.TestSuite())
            return original(text_runner, suite)

        with patch.object(unittest.TextTestRunner, "run", empty_first):
            report = self.run_subset()
        self.assertEqual(report["TEST-001"]["status"], "failed")
        self.assertEqual(report["TEST-001"]["execution"]["tests_run"], 0)

    def test_existing_database_is_never_opened_or_overwritten(self):
        self.db.write_bytes(b"existing database owner data")
        with self.assertRaises(FileExistsError):
            self.run_subset()
        self.assertEqual(self.db.read_bytes(), b"existing database owner data")
        self.assertFalse(self.evidence.exists())

    def test_existing_evidence_is_never_overwritten_or_reused_as_a_result(self):
        self.evidence.mkdir()
        prior = self.evidence / "TEST-001.json"
        prior.write_text('{"status":"passed"}', encoding="utf-8")
        with self.assertRaises(FileExistsError):
            self.run_subset()
        self.assertEqual(prior.read_text(encoding="utf-8"), '{"status":"passed"}')
        self.assertFalse(self.db.exists())

    def test_invalid_or_memory_database_is_rejected_before_writes(self):
        for value in (None, "", " ", ":memory:", b"m0.sqlite"):
            with self.subTest(value=value), self.assertRaises((TypeError, ValueError)):
                runner.run_m0_conformance(value, evidence_dir=self.evidence)
        self.assertFalse(self.evidence.exists())

    def test_nested_database_evidence_paths_are_refused_before_writes(self):
        cases = (
            (self.directory / "same", self.directory / "same"),
            (self.directory / "outer" / "database", self.directory / "outer"),
            (self.directory / "reverse", self.directory / "reverse" / "evidence"),
        )
        for database, evidence in cases:
            with self.subTest(database=database, evidence=evidence):
                with self.assertRaises((OSError, ValueError)) as rejected:
                    runner.run_m0_conformance(str(database), evidence_dir=evidence)
                self.assertFalse(database.exists(), "path validation must not create a database or directory")
                self.assertFalse(evidence.exists(), "path validation must not create evidence")
                self.assertIsInstance(rejected.exception, ValueError)

    def test_api_refuses_existing_sqlite_sidecar_files_and_directories(self):
        for suffix in ("-journal", "-wal", "-shm"):
            for kind in ("file", "directory"):
                with self.subTest(suffix=suffix, kind=kind):
                    base = self.directory / (suffix[1:] + "-" + kind)
                    base.mkdir()
                    database = base / "fresh.sqlite"
                    sidecar = Path(str(database) + suffix)
                    evidence = base / "evidence"
                    if kind == "directory":
                        sidecar.mkdir()
                    owned = sidecar / "owner.data" if kind == "directory" else sidecar
                    owned.write_bytes(b"pre-existing owner evidence")
                    with self.assertRaises(FileExistsError):
                        runner.run_m0_conformance(str(database), evidence_dir=evidence)
                    self.assertEqual(owned.read_bytes(), b"pre-existing owner evidence")
                    self.assertFalse(database.exists())
                    self.assertFalse(evidence.exists())

    def test_cli_refuses_existing_sqlite_sidecars_without_touching_owner_data(self):
        for suffix in ("-journal", "-wal", "-shm"):
            for kind in ("file", "directory"):
                with self.subTest(suffix=suffix, kind=kind):
                    base = self.directory / (suffix[1:] + "-" + kind)
                    base.mkdir()
                    database = base / "fresh.sqlite"
                    sidecar = Path(str(database) + suffix)
                    report = base / "report.json"
                    if kind == "directory":
                        sidecar.mkdir()
                    owned = sidecar / "owner.data" if kind == "directory" else sidecar
                    owned.write_bytes(b"pre-existing owner evidence")
                    result = self.cli(report, database=database)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertEqual(owned.read_bytes(), b"pre-existing owner evidence")
                    self.assertFalse(database.exists())
                    self.assertFalse(report.exists())
                    self.assertFalse(report.with_suffix(".evidence").exists())

    def test_api_refuses_evidence_equal_to_or_inside_sqlite_sidecar_paths(self):
        for suffix in ("-journal", "-wal", "-shm"):
            for nested in (False, True):
                with self.subTest(suffix=suffix, nested=nested):
                    base = self.directory / (suffix[1:] + "-" + str(nested))
                    database = base / "fresh.sqlite"
                    sidecar = Path(str(database) + suffix)
                    evidence = sidecar / "evidence" if nested else sidecar
                    with self.assertRaises(ValueError):
                        runner.run_m0_conformance(str(database), evidence_dir=evidence)
                    self.assertFalse(base.exists(), "overlap must be refused before any output")

    def test_cli_refuses_report_equal_to_or_inside_sqlite_sidecar_paths(self):
        for suffix in ("-journal", "-wal", "-shm"):
            for nested in (False, True):
                with self.subTest(suffix=suffix, nested=nested):
                    base = self.directory / (suffix[1:] + "-" + str(nested))
                    database = base / "fresh.sqlite"
                    sidecar = Path(str(database) + suffix)
                    report = sidecar / "report.json" if nested else sidecar
                    result = self.cli(report, database=database)
                    self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
                    self.assertFalse(base.exists(), "report/sidecar overlap must create no output")

    def test_sidecar_dangling_link_predicate_is_checked_by_api_and_cli(self):
        # Exercise the symlink predicate without requiring Windows link privileges.
        # This is a unit boundary check, not a claim of host filesystem isolation.
        original = Path.is_symlink
        for suffix in ("-journal", "-wal", "-shm"):
            for api in (True, False):
                with self.subTest(suffix=suffix, api=api):
                    base = self.directory / (suffix[1:] + "-" + str(api))
                    database = base / "fresh.sqlite"
                    sidecar = Path(str(database) + suffix)
                    report = base / "report.json"
                    with patch.object(Path, "is_symlink", lambda path: path == sidecar or original(path)):
                        if api:
                            with self.assertRaises(FileExistsError):
                                runner.run_m0_conformance(str(database), evidence_dir=base / "evidence")
                        else:
                            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                                result = runner.main(["--db", str(database), "--json", str(report)])
                            self.assertEqual(result, 2)
                    self.assertFalse(base.exists())

    def test_default_evidence_directory_preserves_repeat_run_without_reusing_results(self):
        report = runner.run_m0_conformance(str(self.db))
        entry = report["TEST-001"]
        before = Path(entry["evidence"]).read_bytes()
        with self.assertRaises(FileExistsError):
            runner.run_m0_conformance(str(self.db))
        self.assertEqual(Path(entry["evidence"]).read_bytes(), before)
        self.assertEqual(entry["status"], "passed")

    def cli(self, output, *, optimized=False, database=None):
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT / "src")
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        command = [sys.executable]
        if optimized:
            command.append("-O")
        command += ["-m", "conformance.m0.runner", "--db", str(self.db if database is None else database), "--json", str(output)]
        return subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=90)

    def test_cli_runs_real_fixtures_and_never_claims_independent_or_full_acceptance(self):
        output = self.directory / "report.json"
        process = self.cli(output, optimized=True)
        self.assertEqual(process.returncode, 0, process.stdout + process.stderr)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["counts"], {"passed": 6, "failed": 0, "pending": 3, "not_applicable": 19})
        self.assertEqual(report["execution_counts"], {"passed": 9, "failed": 0, "not_run": 19})
        self.assertEqual(report["scope"], "m0-core-only")
        self.assertEqual(report["bootstrap_status"], "not_started")
        self.assertFalse(report["claims"]["full_aetp_compatible"])
        self.assertFalse(report["claims"]["work_item_accepted"])
        self.assertFalse(report["claims"]["task_completed"])
        self.assertEqual(report["review"]["status"], "pending")
        self.assertIsNone(report["review"]["reviewer"])
        self.assertIn("conformance/m0/runner.py", report["source_sha256"])
        self.assertEqual(len(report["source_sha256"]["conformance/m0/runner.py"]), 64)
        self.assertEqual(set(report["tests"]), ALL_IDS)

    def test_cli_refuses_existing_report_before_creating_database(self):
        output = self.directory / "report.json"
        output.write_text("previous evidence", encoding="utf-8")
        process = self.cli(output)
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertEqual(output.read_text(encoding="utf-8"), "previous evidence")
        self.assertFalse(self.db.exists())

    def test_cli_failure_keeps_evidence_and_exits_nonzero(self):
        output = self.directory / "failed-report.json"
        def fail(case):
            case.fail("injected acceptance assertion")
        with patch.object(runner._CoreFixtures, "test_001", fail), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            exit_code = runner.main(["--db", str(self.db), "--json", str(output)])
        self.assertEqual(exit_code, 1)
        report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(report["counts"]["failed"], 1)
        entry = report["tests"]["TEST-001"]
        self.assertEqual(entry["status"], "failed")
        self.assertIn("injected acceptance assertion", Path(entry["raw_output"]).read_text(encoding="utf-8"))

    def test_cli_rejects_report_evidence_alias_without_writing(self):
        output = self.directory / "report.evidence"
        process = self.cli(output)
        self.assertEqual(process.returncode, 2, process.stdout + process.stderr)
        self.assertFalse(self.db.exists(), "report/evidence alias must be refused before running fixtures")
        self.assertFalse(output.exists(), "report/evidence alias must not create either output")

    def test_cli_rejects_database_report_alias_without_writing(self):
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = runner.main(["--db", str(self.db), "--json", str(self.db)])
        self.assertEqual(result, 2)
        self.assertFalse(self.db.exists())


if __name__ == "__main__":
    unittest.main()
