"""The fault-injection runner's own report must not read a skip as a pass.

`unittest.TestResult.wasSuccessful()` returns True when the only thing that
happened to a test is that it was skipped. A fault class that never ran would
therefore sit inside an `all_passed=True` report without appearing anywhere in
it - the same "unrun reads as a pass" defect as `unittest discover` skipping a
non-package directory.
"""

from __future__ import annotations

import contextlib
import io
import unittest

from tests.fault_injection.runner import run_fault_injection_suite


class FaultInjectionRunnerReportTests(unittest.TestCase):
    def test_a_skipped_fault_class_is_not_reported_as_passed(self):
        """A skipped test must be counted and must keep all_passed from being true."""
        # Imported inside the method on purpose: at module level this import would
        # put FaultInjectionBatch1Tests into this module's namespace, and discovery
        # collects every TestCase subclass named anywhere in a module - the whole
        # batch would be collected a second time (8 silent duplicate test ids).
        from tests.fault_injection.test_batch1 import FaultInjectionBatch1Tests

        @unittest.skip("injected by this test to model a fault class that never ran")
        def injected_skip(self) -> None:  # pragma: no cover - never executes
            raise AssertionError("a skipped test must not run")

        FaultInjectionBatch1Tests.test_zz_injected_skip = injected_skip
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                report = run_fault_injection_suite()
            self.assertEqual(report["skipped"], 1, f"skipped must be counted, got {report}")
            self.assertFalse(
                report["all_passed"],
                "a fault class that was skipped did not pass; the report must not say it did",
            )
        finally:
            del FaultInjectionBatch1Tests.test_zz_injected_skip

    def test_a_fault_class_that_never_ran_is_not_reported_as_passed(self):
        """tests_run must cover every declared fault class, or the report overclaims."""
        from unittest import mock

        from tests.fault_injection import runner as fi_runner

        # One more declared class than the suite actually exercises.
        extra = fi_runner.FAULT_DEFINITIONS + [
            {"id": "FI-16", "title": "Declared but never wired", "mechanism": "none"}
        ]
        with mock.patch.object(fi_runner, "FAULT_DEFINITIONS", extra):
            with contextlib.redirect_stdout(io.StringIO()):
                report = fi_runner.run_fault_injection_suite()
        self.assertEqual(report["total_fault_classes"], len(extra))
        self.assertLess(report["tests_run"], report["total_fault_classes"])
        self.assertFalse(
            report["all_passed"],
            "a declared fault class that never ran means the suite did not pass",
        )

    def test_a_criterion_whose_evidence_failed_is_not_reported_as_verified(self):
        """§18.2's four criteria are claims about the run, not constants.

        The runner used to write all four as literal True. The report is cited as
        acceptance evidence, so a failed run still read as "all four acceptance
        criteria satisfied" - the same overclaim as an unrun test reading as
        passed, one level up.
        """
        from unittest import mock

        from tests.fault_injection import runner as fi_runner
        from tests.fault_injection.test_batch1 import FaultInjectionBatch1Tests

        def broken(self):  # pragma: no cover - the injected failure is the point
            raise AssertionError("injected: the replay evidence did not hold")

        with mock.patch.object(
            FaultInjectionBatch1Tests,
            "test_fi_05_projection_cache_loss_and_pure_rebuild",
            broken,
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                report = fi_runner.run_fault_injection_suite()

        self.assertFalse(report["all_passed"], "the injected failure must deny all_passed")
        self.assertFalse(
            report["criteria_verification"]["pure_replay_deterministic"],
            "FI-05 is the evidence for pure replay; with it failed the criterion is not verified",
        )

    def test_a_criterion_whose_evidence_was_skipped_is_not_reported_as_verified(self):
        """A criterion is not verified by evidence that never ran either."""
        from unittest import mock

        from tests.fault_injection import runner as fi_runner
        from tests.fault_injection.test_batch1 import FaultInjectionBatch1Tests

        def skipped(self):  # pragma: no cover - never executes
            self.skipTest("injected: the idempotency evidence never ran")

        with mock.patch.object(
            FaultInjectionBatch1Tests,
            "test_fi_02_post_commit_response_loss_idempotent_retry",
            skipped,
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                report = fi_runner.run_fault_injection_suite()

        self.assertEqual(report["skipped"], 1)
        self.assertFalse(
            report["criteria_verification"]["idempotency_zero_side_effects"],
            "unrun idempotency evidence must not leave the criterion verified",
        )

    def test_the_four_criteria_are_verified_when_their_evidence_passes(self):
        """The guard must not be tightened so far that a green run loses its claim."""
        with contextlib.redirect_stdout(io.StringIO()):
            report = run_fault_injection_suite()

        self.assertTrue(report["all_passed"])
        self.assertEqual(
            sorted(report["criteria_verification"]),
            [
                "event_store_fully_auditable",
                "existing_mechanisms_only",
                "idempotency_zero_side_effects",
                "pure_replay_deterministic",
            ],
            "all four §18.2 criteria must still be reported",
        )
        self.assertTrue(
            all(report["criteria_verification"].values()),
            f"a fully green suite verifies all four criteria, got {report['criteria_verification']}",
        )


if __name__ == "__main__":
    unittest.main()
