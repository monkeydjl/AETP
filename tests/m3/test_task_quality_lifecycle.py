"""Explicit rework and Task-scoped completion cannot revive execution rights."""

from aetp.core.projection import Projection
from aetp.domain.models import COMMAND_TYPES, Event, ModelValidationError
from aetp.quality.service import TaskQualityService
from aetp.runtime.document import DocumentRuntime
from aetp.runtime.service import ExecutionService
from tests.m3.quality_support import QualityCase, quality_governance


class QualityLifecycleTests(QualityCase):
    def setUp(self):
        super().setUp()
        self.assertIn("task.quality.complete", COMMAND_TYPES, "Explicit Task quality completion is not implemented")

    def block(self, reason="Reopen the implementation after a context change"):
        return self.qaccept("task.quality.block", payload={"reason": reason, **self.fence()})

    def rework(self):
        return self.qaccept("task.quality.rework", payload={"reason": "Accept a new explicit work round", **self.fence()})

    def test_completed_requires_exemption_fact_then_terminal_and_retires_execution(self):
        self.verified_quality()
        revision = self.task()["revision"]
        result = self.quality_complete()
        events = self.store.read_events("p-1")
        self.assertEqual([event.type for event in events[-3:]],
                         ["command.received", "task.integration_exempted", "task.completed"])
        intermediate = Projection.rebuild(events[:-1])["task:t-1"]
        self.assertEqual(intermediate["status"], "verified")
        self.assertEqual(intermediate["revision"], revision + 1)
        self.assertIn("completion_pending", intermediate)
        self.assertFalse(intermediate["lease"]["revoked"])
        self.assertIn(result.command_id, Projection.pending_command_ids(events[:-1], self.commands()))
        task = self.task()
        self.assertEqual((task["status"], task["revision"]), ("completed", revision + 2))
        self.assertTrue(task["lease"]["revoked"])
        self.assertEqual(task["bindings"][task["current_binding_id"]]["status"], "completed")
        self.assertNotIn("completion_pending", task)
        self.assertEqual(task["integration_exemption"]["basis"], "explicit_human_owner_task_scope")
        self.assertEqual(Projection.pending_command_ids(events, self.commands()), [])

    def test_no_task_specific_exemption_leaves_task_verified(self):
        self.configure_task_quality(version="no-exemption", exempt=False)
        self.verified_quality()
        result = self.qcall("task.quality.complete", actor="a-2")
        self.assertEqual(result.error_code, "INTEGRATION_EXEMPTION_REQUIRED")
        self.assertEqual(self.task()["status"], "verified")
        self.assertNotIn("task.integration_exempted", self.event_types())

    def test_another_tasks_human_declaration_cannot_exempt_this_task(self):
        self.accept(self.command("project.task_quality.configure", "p-1", {
            "version": "qa-only", "max_evidence_age_ms": 60000, "integration_exemptions": [
                {"task_id": "qa-task", "scope": "standalone_fixed_json_document", "reason": "Only this Task"}]},
            actor="human-owner"))
        self.verified_quality()
        result = self.qcall("task.quality.complete", actor="a-2")
        self.assertEqual(result.error_code, "INTEGRATION_EXEMPTION_REQUIRED")

    def test_quality_completion_cannot_skip_verified(self):
        self.reviewed_quality()
        result = self.qcall("task.quality.complete", actor="a-2")
        self.assertEqual(result.error_code, "INVALID_TRANSITION")

    def test_explicit_governance_rule_is_still_required_for_exemption(self):
        value = quality_governance("no-completion-rule")
        value["rules"] = [row for row in value["rules"] if row["action"] != "task.integration.exempt"]
        self.configure(value)
        self.verified_quality()
        result = self.qcall("task.quality.complete", actor="a-2")
        self.assertEqual(result.error_code, "POLICY_DENIED")

    def test_expired_evidence_cannot_complete_an_already_verified_task(self):
        self.configure_task_quality(version="short-final-use", age=500)
        self.verified_quality()
        self.clock_value += 501
        result = self.qcall("task.quality.complete", actor="a-2")
        self.assertEqual(result.error_code, "EVIDENCE_EXPIRED")
        self.assertEqual(self.task()["status"], "verified")
        self.assertEqual(self.verification()["result"], "PASSED")

    def test_pause_requires_a_new_completion_command_after_resume(self):
        self.verified_quality()
        self.accept(self.control("pause"))
        result = self.qcall("task.quality.complete", actor="a-2")
        self.assertEqual(result.error_code, "PROJECT_PAUSED")
        self.accept(self.control("resume"))
        self.assertEqual(self.execution.recover("p-1")["barrier"], "open")
        self.assertEqual(self.task()["status"], "verified")
        self.quality_complete()
        self.assertEqual(self.task()["status"], "completed")

    def test_lost_author_session_is_not_recreated_from_persisted_descriptor(self):
        self.verified_quality()
        runtime = DocumentRuntime(self.workspace)
        execution = ExecutionService(self.store, runtime, clock=lambda: self.clock_value)
        service = TaskQualityService(self.store, owner_id="human-owner", execution=execution,
            input_authority=self.input_authority, meter=self.meter, clock=lambda: self.clock_value)
        command = self.command("task.quality.complete", "t-1", actor="a-2")
        result = service.handle(command, authenticated_actor_id="a-2",
            input_receipt=self.input_authority.issue(command, exposure="internal"))
        self.assertEqual(result.error_code, "SESSION_INVALID")
        self.assertEqual(runtime.sessions(), {})
        self.assertEqual(self.task()["status"], "verified")

    def test_rejected_task_rework_retains_old_cycle_but_requires_new_outputs(self):
        self.reviewed_quality(status="changes_requested")
        self.quality_evaluate()
        old = self.task()["quality_cycle"]
        self.rework()
        self.assertEqual(self.task()["status"], "in_progress")
        self.assertIsNone(self.task()["quality_cycle"])
        self.assertEqual(self.task()["quality_history"][-1]["cycle"], old)
        result = self.qcall("task.quality.submit", payload={"artifact_ids": ["doc-1"], "summary": "Old output", **self.fence()})
        self.assertEqual(result.error_code, "EVIDENCE_STALE")
        self.capture(identifier="reworked-doc")
        self.quality_submit(["reworked-doc"])
        self.assertNotEqual(self.task()["quality_cycle"]["id"], old["id"])
        self.quality_review()
        self.approve_quality_review(artifact_id="reworked-doc")
        self.request_verification("new-v", artifact_id="reworked-doc")
        self.service.dispatch("p-1", "new-v", session=self.qa_session)
        self.quality_evaluate()
        self.quality_complete()
        self.assertEqual(self.task()["status"], "completed")

    def test_unknown_revision_growth_requires_block_and_explicit_rework(self):
        self.enroll_quality()
        self.capture()
        self.eaccept(self.command("execution.report", "t-1", {"summary": "Changed work revision", **self.fence()}),
                     session=self.session)
        self.block()
        self.assertEqual(self.task()["blocked_from"], "in_progress")
        self.rework()
        self.assertEqual(self.task()["quality_contract"]["work_revision"], self.task()["revision"])
        self.capture(identifier="next-doc")
        self.quality_submit(["next-doc"])
        self.assertEqual(self.task()["status"], "ready_for_review")

    def test_ready_round_cannot_rework_without_explicit_block(self):
        self.ready_quality()
        result = self.qcall("task.quality.rework", payload={"reason": "Skip block", **self.fence()})
        self.assertEqual(result.error_code, "INVALID_TRANSITION")
        self.block()
        self.assertEqual(self.task()["blocked_from"], "ready_for_review")
        self.rework()
        self.assertEqual(self.task()["status"], "in_progress")

    def test_peer_with_author_fence_cannot_block_execution(self):
        self.ready_quality()
        result = self.qcall("task.quality.block", payload={"reason": "Borrowed authority", **self.fence()}, actor="a-2")
        self.assertEqual(result.error_code, "PERMISSION_DENIED")

    def test_block_and_rework_require_the_callers_actual_session(self):
        self.ready_quality()
        for kind in ("task.quality.block", "task.quality.rework"):
            command = self.command(kind, "t-1", {"reason": "No capability", **self.fence()})
            result = self.service.handle(command, authenticated_actor_id="a-1", session=None,
                input_receipt=self.input_authority.issue(command, exposure="internal"))
            self.assertEqual(result.error_code, "SESSION_INVALID")
            if kind.endswith("block"):
                self.block()

    def test_new_epoch_cannot_inherit_an_old_task_exemption(self):
        self.eaccept(self.command("lease.revoke", "t-1", {"reason": "handoff", **self.fence()}))
        self.eaccept(self.command("task.requeue", "t-1"))
        self.eaccept(self.command("task.claim", "t-1"))
        start = self.command("execution.start", "t-1", {
            "binding_id": self.task()["current_binding_id"], "lease_epoch": self.task()["lease_epoch"]})
        result, self.session = self.execution.start_session(start, authenticated_actor_id="a-1")
        self.assertEqual(result.status, "accepted", result.to_dict())
        self.verified_quality()
        result = self.qcall("task.quality.complete", actor="a-2")
        self.assertEqual(result.error_code, "INTEGRATION_EXEMPTION_STALE")
        self.assertEqual(self.task()["status"], "verified")

    def test_legacy_commands_cannot_revive_or_mutate_completed_task(self):
        self.verified_quality()
        self.quality_complete()
        final = self.task()
        for kind, payload in (("task.requeue", {}), ("lease.revoke", {"reason": "handoff", **self.fence()}),
                              ("lease.renew", self.fence()),
                              ("execution.report", {"summary": "Late observation", **self.fence()})):
            result = self.execution.handle(self.command(kind, "t-1", payload),
                authenticated_actor_id="a-1", session=self.session)
            self.assertEqual(result.status, "rejected", (kind, result.to_dict()))
            self.assertEqual(self.task(), final)

    def test_retired_sessions_do_not_block_recovery_of_other_work(self):
        self.verified_quality()
        self.eaccept(self.command("lease.revoke", "qa-task", {"reason": "handoff", **self.qa_fence()}, actor="a-2"))
        self.quality_complete()
        self.clock_value = max(self.session.expires_at_wall_ms, self.qa_session.expires_at_wall_ms) + 1
        recovered = self.execution.recover("p-1")
        self.assertEqual(recovered["barrier"], "open", recovered)
        self.assertEqual(recovered["missing_sessions"], [])

    def test_new_quality_commands_cannot_reopen_completed_task(self):
        self.verified_quality()
        self.quality_complete()
        for kind in ("task.quality.block", "task.quality.rework"):
            result = self.qcall(kind, payload={"reason": "Reopen terminal", **self.fence()})
            self.assertEqual(result.error_code, "INVALID_TRANSITION")
        self.assertEqual(self.task()["status"], "completed")

    def test_cancelled_task_cannot_be_requeued_by_legacy_entry(self):
        self.accept(self.command("intervention.apply", "human-stop", {"action": "stop",
            "target": {"type": "task", "id": "t-1", "revision": self.task()["revision"]},
            "reason": "Stop this execution", "impact": "task"}, actor="human-owner"))
        self.assertEqual(self.task()["status"], "cancelled")
        result = self.execution.handle(self.command("task.requeue", "t-1"), authenticated_actor_id="a-1")
        self.assertEqual(result.status, "rejected", result.to_dict())
        self.assertEqual(self.task()["status"], "cancelled")

    def test_pure_reducer_rejects_a_legacy_requeue_fact_after_completion(self):
        self.verified_quality()
        self.quality_complete()
        events = self.store.read_events("p-1")
        forged = Event("forged-requeue-effect", "p-1", events[-1].sequence + 1, "task.requeued", "task", "t-1",
            self.task()["revision"] + 1, "forged-requeue", "quality-test", {
                "actor_id": "a-1", "observed_at_ms": self.clock_value, "reason": "execution_requeue"})
        with self.assertRaises(ModelValidationError):
            Projection.rebuild([*events, forged])
