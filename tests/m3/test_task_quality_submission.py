"""Submission must prove a real current execution, not a claimed completion."""

from dataclasses import replace

from aetp.runtime.document import Session
from tests.m3.quality_support import QualityCase


class QualitySubmissionTests(QualityCase):
    def test_explicit_enrollment_and_submission_only_reaches_ready_for_review(self):
        self.enroll_quality()
        self.capture()
        previous = self.task()["revision"]
        self.quality_submit()
        task = self.task()
        self.assertEqual(task["status"], "ready_for_review")
        self.assertEqual(task["revision"], previous + 1)
        self.assertEqual(task["quality_cycle"]["artifact_ids"], ["doc-1"])
        self.assertEqual(task["quality_cycle"]["anchor_task_revision"], previous)
        self.assertNotIn("integration_exemption", task)

    def test_human_owner_alone_configures_task_quality(self):
        command = self.command("project.task_quality.configure", "p-1", {
            "version": "unauthorized", "max_evidence_age_ms": 60000, "integration_exemptions": []}, actor="a-2")
        result = self.service.handle(command, authenticated_actor_id="a-2")
        self.assertEqual(result.error_code, "PERMISSION_DENIED")
        self.assertEqual(self.state()["project:p-1"]["task_quality_policy"]["current_version"], "task-quality-1")

    def test_legacy_artifact_cannot_be_promoted_by_enrollment(self):
        self.capture()
        self.enroll_quality()
        result = self.qcall("task.quality.submit", payload={"artifact_ids": ["doc-1"],
            "summary": "Old output", **self.fence()})
        self.assertEqual(result.error_code, "EVIDENCE_STALE")
        self.assertEqual(self.task()["status"], "in_progress")

    def test_submission_without_explicit_enrollment_is_rejected(self):
        self.capture()
        result = self.qcall("task.quality.submit", payload={"artifact_ids": ["doc-1"],
            "summary": "Finished", **self.fence()})
        self.assertEqual(result.error_code, "QUALITY_CONTRACT_REQUIRED")

    def test_peer_cannot_use_public_author_fence_as_execution_authority(self):
        self.enroll_quality()
        self.capture()
        result = self.qcall("task.quality.submit", payload={"artifact_ids": ["doc-1"],
            "summary": "I claim their execution ended", **self.fence()}, actor="a-2")
        self.assertEqual(result.error_code, "PERMISSION_DENIED")

    def test_copied_session_cannot_finish_execution(self):
        self.enroll_quality()
        self.capture()
        forged = Session(**{name: getattr(self.session, name) for name in Session.__slots__})
        result = self.qcall("task.quality.submit", payload={"artifact_ids": ["doc-1"],
            "summary": "Finished", **self.fence()}, session=forged)
        self.assertEqual(result.error_code, "SESSION_INVALID")

    def test_registered_author_session_is_not_substituted_when_caller_omits_it(self):
        self.enroll_quality()
        self.capture()
        command = self.command("task.quality.submit", "t-1", {"artifact_ids": ["doc-1"],
            "summary": "No actual caller capability supplied", **self.fence()})
        result = self.service.handle(command, authenticated_actor_id="a-1", session=None,
            input_receipt=self.input_authority.issue(command, exposure="internal"))
        self.assertEqual(result.error_code, "SESSION_INVALID")

    def test_pending_document_action_prevents_execution_end(self):
        self.enroll_quality()
        self.capture()
        self.request_approval("not-dispatched", trusted=True, arguments=self.document_arguments())
        self.request_document("not-dispatched", "Scope and Recovery")
        result = self.qcall("task.quality.submit", payload={"artifact_ids": ["doc-1"],
            "summary": "Finished", **self.fence()})
        self.assertEqual(result.error_code, "RECONCILIATION_REQUIRED")
        self.assertEqual(self.task()["status"], "in_progress")

    def test_every_completed_document_in_round_must_be_declared(self):
        self.enroll_quality()
        self.capture(identifier="doc-1")
        self.capture(identifier="doc-2")
        result = self.qcall("task.quality.submit", payload={"artifact_ids": ["doc-1"],
            "summary": "Omitted a second output", **self.fence()})
        self.assertEqual(result.error_code, "OUTPUT_SET_INCOMPLETE")
        self.quality_submit(["doc-1", "doc-2"])
        self.assertEqual(self.task()["quality_cycle"]["artifact_ids"], ["doc-1", "doc-2"])

    def test_unknown_revision_growth_before_first_submission_cannot_hide_older_output(self):
        self.enroll_quality()
        self.capture(identifier="doc-1")
        self.eaccept(self.command("execution.report", "t-1", {"summary": "Still working", **self.fence()}),
                     session=self.session)
        self.capture(identifier="doc-2")
        result = self.qcall("task.quality.submit", payload={"artifact_ids": ["doc-2"],
            "summary": "Omitted the earlier revision output", **self.fence()})
        self.assertEqual(result.error_code, "QUALITY_CONTEXT_STALE")

    def test_untrusted_submission_does_not_gain_auto_authority(self):
        self.enroll_quality()
        self.capture()
        result = self.qcall("task.quality.submit", payload={"artifact_ids": ["doc-1"],
            "summary": "Unproven ingress", **self.fence()}, trusted=False)
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")

    def test_paused_project_does_not_advance_to_review(self):
        self.enroll_quality()
        self.capture()
        self.accept(self.control("pause"))
        result = self.qcall("task.quality.submit", payload={"artifact_ids": ["doc-1"],
            "summary": "Finished during pause", **self.fence()})
        self.assertEqual(result.error_code, "PROJECT_PAUSED")
        self.assertEqual(self.task()["status"], "in_progress")

    def test_finished_round_rejects_new_runtime_work(self):
        self.ready_quality()
        command = self.command("tool.request", "t-1", {"operation": "document.write",
            "arguments": {"content": "late output"}, **self.fence()})
        result = self.execution.handle(command, authenticated_actor_id="a-1", session=self.session)
        self.assertEqual(result.error_code, "TASK_NOT_EXECUTING")

    def test_author_mismatch_cannot_reserve_quality_command(self):
        command = self.command("task.quality.enroll", "t-1", {"policy_version": "task-quality-1", **self.fence()})
        before = len(self.store.read_events("p-1"))
        result = self.service.handle(command, authenticated_actor_id="a-2", session=self.session)
        self.assertEqual(result.error_code, "ACTOR_MISMATCH")
        self.assertEqual(len(self.store.read_events("p-1")), before)
        accepted = self.service.handle(command, authenticated_actor_id="a-1", session=self.session,
            input_receipt=self.input_authority.issue(command, exposure="internal"))
        self.assertEqual(accepted.status, "accepted", accepted.to_dict())
