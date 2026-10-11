"""Integration Gate, state machine transitions, TEST-009, and TEST-024 checks."""
from unittest.mock import patch
from aetp.core.projection import Projection
from aetp.domain.models import Command
from tests.m3.integration_live_support import IntegrationCase
from tests.m3.test_integration_contract_inputs import target_fixture


class IntegrationGateTests(IntegrationCase):
    def test_unexempted_task_cannot_complete_without_gate_test_009(self):
        """TEST-009: Unexempted task cannot complete without passing Integration Gate."""
        # Configured without exemption
        self.declare()
        self.verified_quality()
        self.assertEqual(self.task()["status"], "verified")

        # Attempt to complete directly from verified -> must reject
        result = self.qcall("task.quality.complete", actor="a-2")
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "INTEGRATION_REQUIRED")
        self.assertEqual(self.task()["status"], "verified")

    def test_exempted_task_with_audit_trail_can_complete(self):
        """TEST-009: Exempted task with explicit audit trail can complete without gate."""
        self.configure_task_quality(version="task-quality-exempt", exempt=True)
        self.verified_quality()
        self.assertEqual(self.task()["status"], "verified")

        # When explicitly exempted in policy, quality complete succeeds
        result = self.quality_complete()
        self.assertEqual(result.status, "accepted")
        self.assertEqual(self.task()["status"], "completed")

    def test_verified_transitions_to_ready_for_integration(self):
        """Task in verified state transitions to ready_for_integration when integration declared."""
        self.declare()
        self.verified_quality()
        self.assertEqual(self.task()["status"], "verified")

        # Advance to ready_for_integration
        cmd = self.command("task.integration_ready", "t-1",
                           {"expected_task_revision": self.task()["revision"]},
                           revision=self.task()["revision"], actor="human-owner")
        result = self.submit(cmd)
        self.assertEqual(result.status, "accepted", result.to_dict())
        self.assertEqual(self.task()["status"], "ready_for_integration")

    def test_missing_declaration_cannot_enter_integration_ready(self):
        """Task without integration declaration cannot enter ready_for_integration."""
        self.verified_quality()
        cmd = self.command("task.integration_ready", "t-1",
                           {"expected_task_revision": self.task()["revision"]},
                           revision=self.task()["revision"], actor="human-owner")
        result = self.submit(cmd)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "INTEGRATION_NOT_DECLARED")
        self.assertEqual(self.task()["status"], "verified")

    def test_merge_baseline_advanced_rejected_test_024(self):
        """TEST-024: Target branch baseline advancement rejects merge."""
        self.declare()
        self.verified_quality()
        ready_cmd = self.command("task.integration_ready", "t-1",
                                 {"expected_task_revision": self.task()["revision"]},
                                 revision=self.task()["revision"], actor="human-owner")
        self.submit(ready_cmd)
        self.assertEqual(self.task()["status"], "ready_for_integration")

        # Submit git.merge with an expected commit that does not match current target baseline
        merge_cmd = self.command("git.merge", "t-1", {
            "source_ref": "refs/heads/agent/task_042",
            "source_commit": "1111111111111111111111111111111111111111",
            "target_ref": "refs/heads/main",
            "expected_target_commit": "0000000000000000000000000000000000000000",  # Stale baseline
            "current_target_commit": "2222222222222222222222222222222222222222",   # Target has moved
            "expected_task_revision": self.task()["revision"]
        }, revision=self.task()["revision"], actor="human-owner")
        result = self.submit(merge_cmd)
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "BASELINE_ADVANCED")
        self.assertEqual(self.task()["status"], "ready_for_integration")

    def test_merge_success_transitions_to_integrated(self):
        """Matching baseline git.merge succeeds and transitions task to integrated."""
        self.declare()
        self.verified_quality()
        ready_cmd = self.command("task.integration_ready", "t-1",
                                 {"expected_task_revision": self.task()["revision"]},
                                 revision=self.task()["revision"], actor="human-owner")
        self.submit(ready_cmd)
        self.assertEqual(self.task()["status"], "ready_for_integration")

        commit = "2222222222222222222222222222222222222222"
        merge_cmd = self.command("git.merge", "t-1", {
            "source_ref": "refs/heads/agent/task_042",
            "source_commit": "1111111111111111111111111111111111111111",
            "target_ref": "refs/heads/main",
            "expected_target_commit": commit,
            "current_target_commit": commit,
            "result_commit": "3333333333333333333333333333333333333333",
            "expected_task_revision": self.task()["revision"]
        }, revision=self.task()["revision"], actor="human-owner")
        result = self.submit(merge_cmd)
        self.assertEqual(result.status, "accepted", result.to_dict())
        self.assertEqual(self.task()["status"], "integrated")

    def test_merge_conflict_records_event_and_does_not_advance_to_integrated(self):
        """Merge conflict records integration.conflict and keeps task in ready_for_integration."""
        self.declare()
        self.verified_quality()
        ready_cmd = self.command("task.integration_ready", "t-1",
                                 {"expected_task_revision": self.task()["revision"]},
                                 revision=self.task()["revision"], actor="human-owner")
        self.submit(ready_cmd)

        commit = "2222222222222222222222222222222222222222"
        merge_cmd = self.command("git.merge", "t-1", {
            "source_ref": "refs/heads/agent/task_042",
            "source_commit": "1111111111111111111111111111111111111111",
            "target_ref": "refs/heads/main",
            "expected_target_commit": commit,
            "current_target_commit": commit,
            "has_conflict": True,
            "conflict_paths": ["src/main.py"],
            "expected_task_revision": self.task()["revision"]
        }, revision=self.task()["revision"], actor="human-owner")
        result = self.submit(merge_cmd)
        self.assertEqual(result.status, "accepted", result.to_dict())
        self.assertEqual(self.task()["status"], "ready_for_integration")
        self.assertTrue(self.task().get("integration_conflict"))

    def test_system_verification_required_before_completed(self):
        """Task in integrated state must pass system verification before completed."""
        self.declare()
        self.verified_quality()
        ready_cmd = self.command("task.integration_ready", "t-1",
                                 {"expected_task_revision": self.task()["revision"]},
                                 revision=self.task()["revision"], actor="human-owner")
        self.submit(ready_cmd)

        commit = "2222222222222222222222222222222222222222"
        merge_cmd = self.command("git.merge", "t-1", {
            "source_ref": "refs/heads/agent/task_042",
            "source_commit": "1111111111111111111111111111111111111111",
            "target_ref": "refs/heads/main",
            "expected_target_commit": commit,
            "current_target_commit": commit,
            "result_commit": "3333333333333333333333333333333333333333",
            "expected_task_revision": self.task()["revision"]
        }, revision=self.task()["revision"], actor="human-owner")
        self.submit(merge_cmd)
        self.assertEqual(self.task()["status"], "integrated")

        # Cannot complete directly from integrated without system verification
        fail_complete = self.qcall("task.quality.complete", actor="a-2", revision=self.task()["revision"])
        self.assertEqual(fail_complete.status, "rejected")
        self.assertEqual(fail_complete.error_code, "INTEGRATION_REQUIRED")

        # Record system verification PASSED
        sys_cmd = self.command("task.system_verify", "t-1", {
            "result_commit": "3333333333333333333333333333333333333333",
            "outcome": "passed",
            "expected_task_revision": self.task()["revision"]
        }, revision=self.task()["revision"], actor="human-owner")
        sys_res = self.submit(sys_cmd)
        self.assertEqual(sys_res.status, "accepted", sys_res.to_dict())
        self.assertEqual(self.task()["status"], "system_verified")

        # Now can complete
        complete_res = self.qcall("task.quality.complete", actor="a-2", revision=self.task()["revision"])
        self.assertEqual(complete_res.status, "accepted", complete_res.to_dict())
        self.assertEqual(self.task()["status"], "completed")

    def test_full_gate_deterministic_replay(self):
        """Full gate lifecycle events replay deterministically without side effects."""
        self.declare()
        self.verified_quality()
        ready_cmd = self.command("task.integration_ready", "t-1",
                                 {"expected_task_revision": self.task()["revision"]},
                                 revision=self.task()["revision"], actor="human-owner")
        self.submit(ready_cmd)

        commit = "2222222222222222222222222222222222222222"
        merge_cmd = self.command("git.merge", "t-1", {
            "source_ref": "refs/heads/agent/task_042",
            "source_commit": "1111111111111111111111111111111111111111",
            "target_ref": "refs/heads/main",
            "expected_target_commit": commit,
            "current_target_commit": commit,
            "result_commit": "3333333333333333333333333333333333333333",
            "expected_task_revision": self.task()["revision"]
        }, revision=self.task()["revision"], actor="human-owner")
        self.submit(merge_cmd)

        sys_cmd = self.command("task.system_verify", "t-1", {
            "result_commit": "3333333333333333333333333333333333333333",
            "outcome": "passed",
            "expected_task_revision": self.task()["revision"]
        }, revision=self.task()["revision"], actor="human-owner")
        self.submit(sys_cmd)
        self.qcall("task.quality.complete", actor="a-2", revision=self.task()["revision"])

        live_state = self.state()
        self.assertEqual(live_state["task:t-1"]["status"], "completed")

        # Pure replay from SQLite event store
        events = self.store.read_events("p-1")
        replayed_state = Projection.rebuild(events)
        self.assertEqual(replayed_state["task:t-1"]["status"], "completed")
        self.assertEqual(replayed_state["task:t-1"]["revision"], live_state["task:t-1"]["revision"])
