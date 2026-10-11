"""Crash, revocation and live-time checks over the real durable grant boundary."""

import json
import sqlite3
from unittest.mock import patch

from aetp.acceptance.runner import FixedJsonRunner
from aetp.core.projection import Projection
from tests.m3.verification_support import VerificationCase, verification_policy


class VerificationRecoveryTests(VerificationCase):
    def setUp(self):
        super().setUp()
        self.capture()
        self.request_verification()

    def lose_result(self):
        connection = self.store._ensure_open()
        connection.execute("""CREATE TRIGGER lose_verification_result BEFORE INSERT ON events
            WHEN NEW.type = 'verification.finished' BEGIN SELECT RAISE(ABORT, 'lost result transaction'); END""")
        try:
            with self.assertRaises(ValueError) as failure:
                self.service.dispatch("p-1", "v-1", session=self.qa_session)
            self.assertIsInstance(failure.exception.__cause__, sqlite3.IntegrityError)
        finally:
            connection.execute("DROP TRIGGER lose_verification_result")
        self.assertEqual(self.verification()["action"]["status"], "in_flight")
        self.assertNotIn("artifact.verification_reported", self.event_types())
        self.assertNotIn("verification.finished", self.event_types())
        self.assertEqual(Projection.pending_command_ids(self.store.read_events("p-1"), self.commands()), [])

    def test_lost_result_blocks_global_recovery_assessment(self):
        self.lose_result()
        status = self.execution.recovery_status("p-1")
        self.assertFalse(status["checks"]["ready"])
        self.assertEqual(status["checks"]["unknown_actions"], [self.verification()["action"]["id"]])

    def test_document_recovery_cannot_hide_nested_unknown_action(self):
        self.lose_result()
        result = self.execution.recover("p-1")
        self.assertEqual(result["barrier"], "closed")
        self.assertEqual(result["unknown_actions"], [self.verification()["action"]["id"]])

    def test_recovery_closes_fixed_call_with_termination_evidence_and_never_reruns(self):
        count = []
        original = FixedJsonRunner.run

        def observed(runner, content, cases):
            count.append(1)
            return original(runner, content, cases)

        with patch.object(FixedJsonRunner, "run", observed):
            self.lose_result()
        with patch.object(FixedJsonRunner, "run", side_effect=AssertionError("recovery reran historical work")):
            retry = self.service.dispatch("p-1", "v-1", session=self.qa_session)
            self.assertEqual(retry["action"]["status"], "in_flight")
            recovered = self.service.recover_verifications("p-1")
            self.assertEqual(self.service.recover_verifications("p-1"), [])
        self.assertEqual(len(count), 1)
        self.assertEqual(len(recovered), 1)
        final = self.verification()
        self.assertEqual((final["result"], final["action"]["status"]), ("INCONCLUSIVE", "abandoned"))
        report = json.loads(self.state()[f"artifact:{final['evidence_id']}"]["content"])
        self.assertEqual(report["termination"], "exclusive_gate_fixed_memory_runner_exited")
        self.assertIsNone(report["observation"])
        self.assertEqual(report["execution_outcome"], "recovered")
        self.assertEqual(self.execution.recover("p-1")["barrier"], "open")

    def test_governance_resume_remains_closed_until_verification_is_recovered(self):
        self.lose_result()
        self.accept(self.control("pause"))
        self.reject(self.control("resume"), "RECOVERY_REQUIRED")
        self.service.recover_verifications("p-1")
        self.accept(self.control("resume"))
        self.assertEqual(self.state()["project:p-1"]["status"], "planning")

    def test_wall_clock_expiry_prevents_first_invocation(self):
        self.clock_value = 2000
        with patch.object(FixedJsonRunner, "run", side_effect=AssertionError("expired grant ran")):
            result = self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.assertEqual((result["result"], result["reason"]), ("INCONCLUSIVE", "GRANT_EXPIRED"))
        self.assertEqual(result["action"]["dispatch_count"], 0)

    def test_quality_change_after_grant_invalidates_before_invocation(self):
        self.accept(self.command("project.quality.configure", "p-1", {"grant_ttl_ms": 1000}, actor="human-owner"))
        with patch.object(FixedJsonRunner, "run", side_effect=AssertionError("obsolete quality policy ran")):
            result = self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.assertEqual(result["reason"], "QUALITY_POLICY_CHANGED")
        self.assertEqual(result["action"]["dispatch_count"], 0)

    def test_governance_change_after_grant_invalidates_before_invocation(self):
        self.configure(verification_policy("gov-changed"))
        with patch.object(FixedJsonRunner, "run", side_effect=AssertionError("obsolete governance ran")):
            result = self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.assertEqual(result["reason"], "GOVERNANCE_CHANGED")

    def test_author_task_revision_change_makes_target_stale(self):
        self.eaccept(self.command("lease.renew", "t-1", self.fence()), session=self.session)
        with patch.object(FixedJsonRunner, "run", side_effect=AssertionError("stale artifact ran")):
            result = self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.assertEqual(result["reason"], "EVIDENCE_STALE")

    def test_new_epoch_does_not_inherit_old_grant(self):
        self.eaccept(self.command("lease.revoke", "qa-task", {**self.qa_fence(), "reason": "handoff"}, actor="a-2"))
        self.eaccept(self.command("task.requeue", "qa-task", actor="a-2"))
        self.eaccept(self.command("task.claim", "qa-task", actor="a-2"))
        task = self.state()["task:qa-task"]
        result, new_session = self.execution.start_session(self.command("execution.start", "qa-task",
            {"binding_id": task["current_binding_id"], "lease_epoch": task["lease_epoch"]}, actor="a-2"), authenticated_actor_id="a-2")
        self.assertEqual(result.status, "accepted")
        self.assertEqual(task["lease_epoch"], 2)
        with patch.object(FixedJsonRunner, "run", side_effect=AssertionError("old epoch ran")):
            final = self.service.dispatch("p-1", "v-1", session=new_session)
        self.assertEqual(final["reason"], "STALE_EXECUTION")

    def test_revocation_after_observation_preserves_observation_but_invalidates_pass(self):
        original = FixedJsonRunner.run

        def revoked(runner, content, cases):
            observation = original(runner, content, cases)
            self.accept(self.command("verification.revoke", "v-1", {"reason": "Human withdrew this grant"}, actor="human-owner"))
            return observation

        with patch.object(FixedJsonRunner, "run", revoked):
            result = self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.assertEqual((result["result"], result["reason"]), ("INCONCLUSIVE", "GRANT_REVOKED"))
        report = json.loads(self.state()[f"artifact:{result['evidence_id']}"]["content"])
        self.assertEqual(report["observation"]["observed_result"], "PASSED")

    def test_pause_after_observation_cannot_commit_usable_pass(self):
        original = FixedJsonRunner.run

        def paused(runner, content, cases):
            observation = original(runner, content, cases)
            self.accept(self.control("pause"))
            return observation

        with patch.object(FixedJsonRunner, "run", paused):
            result = self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.assertEqual((result["result"], result["reason"]), ("INCONCLUSIVE", "PROJECT_PAUSED"))
        self.assertEqual(result["action"]["status"], "completed")

    def test_lost_registered_session_invalidates_before_call(self):
        self.runtime._sessions.pop(self.qa_session.id)
        with patch.object(FixedJsonRunner, "run", side_effect=AssertionError("lost Session ran")):
            result = self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.assertEqual(result["reason"], "SESSION_INVALID")

    def test_runner_exception_has_no_fabricated_checks(self):
        with patch.object(FixedJsonRunner, "run", side_effect=RuntimeError("simulated interrupted checker")):
            result = self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.assertEqual((result["result"], result["reason"]), ("INCONCLUSIVE", "RUNNER_ERROR"))
        report = json.loads(self.state()[f"artifact:{result['evidence_id']}"]["content"])
        self.assertIsNone(report["observation"])
        self.assertEqual(result["action"]["status"], "abandoned")

    def test_finished_truth_is_immutable_after_later_policy_change(self):
        first = self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.assertEqual(first["result"], "PASSED")
        self.configure(verification_policy("gov-later"))
        self.assertEqual(self.verification(), first)
        self.reject(self.command("verification.revoke", "v-1", {"reason": "too late"}, actor="human-owner"), "VERIFICATION_FINAL")
