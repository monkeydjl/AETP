"""Unresolved execution and source boundaries around the quality lifecycle."""

from unittest.mock import patch

from tests.m3.quality_support import QualityCase, quality_governance


class QualityBoundaryTests(QualityCase):
    def test_in_flight_and_unknown_document_actions_prevent_submission(self):
        self.enroll_quality()
        self.capture()
        self.request_approval("lost-write", trusted=True, arguments=self.document_arguments())
        action = self.request_document("lost-write")
        with patch.object(self.workspace, "write", side_effect=SystemExit("fixture effect interruption")):
            with self.assertRaises(SystemExit):
                self.execution.dispatch("p-1", action["id"], session=self.session)
        self.assertEqual(self.state()[f"action:{action['id']}"]["status"], "in_flight")
        payload = {"artifact_ids": ["doc-1"], "summary": "Unsettled effect", **self.fence()}
        self.assertEqual(self.qcall("task.quality.submit", payload=payload).error_code, "RECONCILIATION_REQUIRED")
        self.assertEqual(self.execution.recover("p-1")["barrier"], "closed")
        self.assertEqual(self.state()[f"action:{action['id']}"]["status"], "unknown")
        self.assertEqual(self.qcall("task.quality.submit", payload=payload).error_code, "RECOVERY_REQUIRED")
        self.assertEqual(self.task()["status"], "in_progress")

    def test_task_running_verification_for_another_target_has_not_finished_execution(self):
        self.enroll_quality()
        self.capture()
        content, fence = '{"qa":true}', self.qa_fence()
        self.qaccept("approval.request", "peer-write", {"target": self.service.snapshot("p-1", "task", "qa-task"),
            "action": "document.write", "arguments": {**fence, "document": {"content": content}}, "ttl_ms": 1000}, actor="a-2")
        result = self.eaccept(self.command("tool.request", "qa-task", {**fence, "operation": "document.write",
            "arguments": {"content": content}, "approval_id": "peer-write"}, actor="a-2"), session=self.qa_session)
        event = next(event for event in self.store.read_events("p-1") if event.id == result.event_ids[-1])
        self.execution.dispatch("p-1", event.aggregate_id, session=self.qa_session)
        self.qaccept("artifact.capture", "peer-doc", {**fence, "source_action_id": event.aggregate_id}, actor="a-2")
        artifact = self.state()["artifact:peer-doc"]
        self.qaccept("verification.request", "author-qa", {"artifact_id": "peer-doc", "artifact_digest": artifact["content_digest"],
            "exec_task_id": "t-1", **self.fence(),
            "cases": [{"criterion": "Execute Cases", "path": ["qa"], "equals": True}]})
        result = self.qcall("task.quality.submit", payload={"artifact_ids": ["doc-1"], "summary": "Still running QA", **self.fence()})
        self.assertEqual(result.error_code, "RECONCILIATION_REQUIRED")

    def test_inherited_untrusted_source_is_not_cleansed_by_a_new_submission_receipt(self):
        self.enroll_quality()
        self.capture(trusted=False)
        result = self.qcall("task.quality.submit", payload={"artifact_ids": ["doc-1"], "summary": "Marked output", **self.fence()})
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        self.assertEqual(self.task()["status"], "in_progress")

    def test_pending_verification_must_finish_before_rework(self):
        self.reviewed_quality()
        self.request_verification()
        self.qaccept("task.quality.block", payload={"reason": "Revise work", **self.fence()})
        result = self.qcall("task.quality.rework", payload={"reason": "New work", **self.fence()})
        self.assertEqual(result.error_code, "RECONCILIATION_REQUIRED")
        final = self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.assertEqual((final["result"], final["action"]["dispatch_count"]), ("INCONCLUSIVE", 0))
        self.qaccept("task.quality.rework", payload={"reason": "Now settled", **self.fence()})
        self.assertEqual(self.task()["status"], "in_progress")

    def test_passed_verification_cannot_replace_a_pending_independent_review(self):
        self.ready_quality()
        self.quality_review()
        self.request_verification()
        self.assertEqual(self.service.dispatch("p-1", "v-1", session=self.qa_session)["result"], "PASSED")
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "in_review")
        self.approve_quality_review()
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "verified")

    def test_manual_policy_cannot_implicitly_approve_a_quality_transition(self):
        self.configure(quality_governance("manual-quality", mode="manual"))
        result = self.qcall("task.quality.enroll", payload={"policy_version": "task-quality-1", **self.fence()})
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        self.assertNotIn("quality_contract", self.task())
