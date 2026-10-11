"""Independent reviews bind to a complete, explicit submission round."""

from aetp.core.projection import Projection
from aetp.domain.models import COMMAND_TYPES
from tests.m3.quality_support import QualityCase, quality_governance


class QualityReviewTests(QualityCase):
    def setUp(self):
        super().setUp()
        self.assertIn("task.quality.request_review", COMMAND_TYPES, "Official independent reviews are not implemented")

    def test_request_creates_all_reviews_and_in_review_atomically(self):
        self.enroll_quality()
        self.capture(identifier="doc-1")
        self.capture(identifier="doc-2")
        self.quality_submit(["doc-2", "doc-1"])
        revision = self.task()["revision"]
        result = self.quality_review()
        self.assertEqual(self.task()["status"], "in_review")
        self.assertEqual(self.task()["revision"], revision + 1)
        self.assertEqual(len(result.event_ids), 4)
        for artifact, identifier in self.task()["quality_cycle"]["reviews"].items():
            review = self.state()[f"review:{identifier}"]
            self.assertEqual((review["artifact_id"], review["reviewer_id"], review["status"]),
                             (artifact, "a-2", "pending"))
            self.assertEqual(review["quality_cycle_id"], self.task()["quality_cycle"]["id"])
        self.assertEqual(Projection.pending_command_ids(self.store.read_events("p-1"), self.commands()), [])

    def test_review_does_not_borrow_author_session_or_lease(self):
        self.ready_quality()
        lease = self.task()["lease"]
        command = self.command("task.quality.request_review", "t-1", {"reviewers": {"doc-1": "a-2"}}, actor="a-2")
        result = self.service.handle(command, authenticated_actor_id="a-2", session=None,
            input_receipt=self.input_authority.issue(command, exposure="internal"))
        self.assertEqual(result.status, "accepted", result.to_dict())
        self.approve_quality_review()
        self.assertEqual(self.task()["lease"], lease)
        self.assertEqual(self.task()["owner_id"], "a-1")

    def test_author_cannot_be_selected_as_independent_reviewer(self):
        self.ready_quality()
        result = self.qcall("task.quality.request_review", payload={"reviewers": {"doc-1": "a-1"}})
        self.assertEqual(result.error_code, "INDEPENDENCE_REQUIRED")
        self.assertEqual(self.task()["status"], "ready_for_review")

    def test_review_selection_covers_every_submitted_artifact(self):
        self.enroll_quality()
        self.capture(identifier="doc-1")
        self.capture(identifier="doc-2")
        self.quality_submit(["doc-1", "doc-2"])
        result = self.qcall("task.quality.request_review", payload={"reviewers": {"doc-1": "a-2"}}, actor="a-2")
        self.assertEqual(result.error_code, "REVIEW_SET_INCOMPLETE")
        self.assertFalse(any(key.startswith("review:") for key in self.state()))

    def test_review_request_requires_formal_ready_stage(self):
        self.enroll_quality()
        self.capture()
        result = self.qcall("task.quality.request_review", payload={"reviewers": {"doc-1": "a-2"}}, actor="a-2")
        self.assertEqual(result.error_code, "INVALID_TRANSITION")

    def test_only_selected_peer_can_submit_once(self):
        self.ready_quality()
        self.quality_review()
        identifier = self.task()["quality_cycle"]["reviews"]["doc-1"]
        result = self.qcall("review.quality.submit", identifier,
                           {"status": "approved", "feedback": "Author attempts their own review"})
        self.assertEqual(result.error_code, "PERMISSION_DENIED")
        self.approve_quality_review()
        result = self.qcall("review.quality.submit", identifier,
                           {"status": "rejected", "feedback": "Replace an immutable opinion"}, actor="a-2")
        self.assertEqual(result.error_code, "REVIEW_FINAL")
        self.assertEqual(self.task()["status"], "in_review")

    def test_unproven_review_input_cannot_obtain_auto_permission(self):
        self.ready_quality()
        self.quality_review()
        identifier = self.task()["quality_cycle"]["reviews"]["doc-1"]
        result = self.qcall("review.quality.submit", identifier,
                           {"status": "approved", "feedback": "Unknown ingress"}, actor="a-2", trusted=False)
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")

    def test_review_approval_alone_does_not_verify_task(self):
        self.reviewed_quality()
        self.assertEqual(self.task()["status"], "in_review")
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "in_review")
        self.assertEqual(self.task()["quality_cycle"]["uses"][-1]["result"], "INCONCLUSIVE")

    def test_verification_requires_in_review_and_preserves_original_revision(self):
        self.ready_quality()
        command = self.verification_command()
        result = self.service.handle(command, authenticated_actor_id="a-2", session=self.qa_session,
            input_receipt=self.input_authority.issue(command, exposure="internal"))
        self.assertEqual(result.error_code, "INVALID_TRANSITION")
        self.quality_review()
        record = self.request_verification()
        self.assertEqual(record["input"]["quality_cycle_id"], self.task()["quality_cycle"]["id"])
        self.assertEqual(record["input"]["task_revision"], self.state()["artifact:doc-1"]["task_revision"])
        self.assertLess(record["input"]["task_revision"], self.task()["revision"])

    def test_missing_explicit_governance_rule_denies_review(self):
        value = quality_governance("no-review-rule")
        value["rules"] = [row for row in value["rules"] if row["action"] != "task.quality.review"]
        self.configure(value)
        self.ready_quality()
        result = self.qcall("task.quality.request_review", payload={"reviewers": {"doc-1": "a-2"}}, actor="a-2")
        self.assertEqual(result.error_code, "POLICY_DENIED")

    def test_only_designated_reviewer_can_request_cycle_verification(self):
        self.accept(self.command("agent.register", "a-3", {"model_id": "fixture-peer"}, actor="bootstrap"))
        value = quality_governance("three-peers")
        value["subjects"]["a-3"] = {"type": "agent", "roles": ["independent_reviewer", "agent_reviewer"]}
        self.configure(value)
        self.ready_quality()
        self.quality_review(reviewer="a-3")
        command = self.verification_command()
        result = self.service.handle(command, authenticated_actor_id="a-2", session=self.qa_session,
            input_receipt=self.input_authority.issue(command, exposure="internal"))
        self.assertEqual(result.error_code, "REVIEWER_MISMATCH")
