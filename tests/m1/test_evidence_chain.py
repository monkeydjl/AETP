"""Immutable candidates and independent review, without Task ownership transfer."""

import hashlib
from dataclasses import replace

from aetp.collaboration.messages import Message
from aetp.core.projection import Projection
from tests.m1.support import CollaborationCase


class EvidenceChainTests(CollaborationCase):
    def test_fixed_policy_criteria_and_readable_artifact_are_bound_to_task_snapshot(self):
        task = self.state()["task:t-1"]
        self.assertEqual(task["policy_version"], "m1-document-candidate-v1")
        self.assertEqual(task["acceptance_criteria"], ["Overview", "Failure case"])
        artifact, result = self.artifact(content="Overview\nFailure case\n证据")
        self.assertEqual(artifact["content_digest"], "sha256:" + hashlib.sha256("Overview\nFailure case\n证据".encode()).hexdigest())
        self.assertEqual(artifact["content"], "Overview\nFailure case\n证据")
        self.assertEqual(artifact["task_revision"], 1)
        self.assertEqual(artifact["criteria_digest"], task["criteria_digest"])
        self.assertEqual(artifact["source"]["kind"], "inline_candidate")
        self.assertEqual(artifact["source"]["command_id"], result.command_id)
        self.assertEqual(self.state()["task:t-1"], task)

    def test_artifact_identity_is_immutable_and_replacement_preserves_provenance(self):
        original, _ = self.artifact()
        self.reject(self.command("artifact.submit", "art-1", {
            "task_id": "t-1", "type": "document", "content": "Replacement"}), "REVISION_CONFLICT")
        replacement, _ = self.artifact("art-2", content="Overview\nFailure case\nRevision 2",
                                        derived_from=["art-1"], supersedes="art-1")
        self.assertEqual(replacement["derived_from"], ["art-1"])
        self.assertEqual(replacement["supersedes"], "art-1")
        self.assertEqual(self.state()["artifact:art-1"], original)
        replacement["content"] = "caller mutation"
        self.assertIn("Revision 2", self.state()["artifact:art-2"]["content"])

    def test_nonowner_candidate_does_not_acquire_task_or_advance_status(self):
        task = self.state()["task:t-1"]
        artifact, _ = self.artifact(actor="a-2")
        self.assertEqual(artifact["created_by"], "a-2")
        self.assertEqual(self.state()["task:t-1"], task)
        self.assertEqual(task["owner_id"], "a-1")
        self.assertEqual(task["status"], "assigned")

    def test_pinned_conversation_remains_readable_after_message_bus_is_replaced(self):
        bus = self.service.messages
        bus.send(Message("m-1", "p-1", "a-1", ("a-2",), "proposal", "Write Overview.",
                         untrusted_input=True), authenticated_actor_id="a-1")
        bus.send(Message("m-2", "p-1", "a-2", ("a-1",), "challenge", "Add Failure case.",
                         references=("m-1",), target_message="m-1", untrusted_input=False),
                 authenticated_actor_id="a-2")
        artifact, _ = self.artifact(message_ids=["m-1", "m-2"])
        self.assertEqual([s["message"]["id"] for s in artifact["source"]["messages"]], ["m-1", "m-2"])
        self.assertTrue(artifact["source"]["untrusted_input"])
        from aetp.collaboration.service import CollaborationService
        fresh = CollaborationService(self.store)
        self.assertEqual(fresh.messages.inbox("p-1", authenticated_actor_id="a-2"), ())
        replay = Projection.rebuild(self.store.read_events("p-1"))
        self.assertEqual(replay["artifact:art-1"]["source"], artifact["source"])

    def test_independent_peer_reviews_without_claiming_author_task(self):
        self.artifact()
        task = self.state()["task:t-1"]
        self.request_review()
        self.accept(self.submit_review_command())
        review = self.state()["review:rev-1"]
        self.assertEqual(review["reviewer_id"], "a-2")
        self.assertEqual(review["status"], "approved")
        self.assertEqual(review["revision"], 1)
        self.assertEqual(self.state()["task:t-1"], task)
        self.assertEqual(Projection.rebuild(self.store.read_events("p-1")), self.state())

    def test_self_review_forged_reviewer_and_nonmembers_cannot_approve(self):
        artifact, _ = self.artifact()
        self.reject(self.command("review.request", "self-review", {
            "artifact_id": "art-1", "artifact_digest": artifact["content_digest"],
            "reviewer_id": "a-1"}), "SELF_REVIEW")
        self.request_review()
        self.reject(self.submit_review_command(actor="a-1"), "PERMISSION_DENIED")
        self.reject(self.submit_review_command(actor="outsider"), "PERMISSION_DENIED")
        self.assertEqual(self.state()["review:rev-1"]["status"], "pending")

    def test_review_binds_expected_digest_and_rejects_stale_task_revision(self):
        self.artifact()
        self.reject(self.command("review.request", "bad-digest", {
            "artifact_id": "art-1", "artifact_digest": "sha256:" + "0" * 64,
            "reviewer_id": "a-2"}, actor="a-2"), "EVIDENCE_STALE")
        self.request_review()
        self.accept(self.command("task.release", "t-1", {}, revision=1))
        self.reject(self.submit_review_command(), "EVIDENCE_STALE")
        self.assertEqual(self.state()["review:rev-1"]["status"], "pending")

    def test_review_can_request_changes_but_terminal_result_cannot_be_rewritten(self):
        self.artifact()
        self.request_review()
        self.accept(self.submit_review_command(status="changes_requested"))
        self.reject(self.submit_review_command(status="approved"), "REVISION_CONFLICT")
        retry = replace(self.submit_review_command(status="approved"), expected_revision=1)
        self.reject(retry, "REVIEW_FINAL")
        self.assertEqual(self.state()["review:rev-1"]["status"], "changes_requested")
        self.assertEqual(self.state()["task:t-1"]["status"], "assigned")

    def test_spoofed_actor_cannot_reserve_candidate_command_identity(self):
        command = self.command("artifact.submit", "art-1", {
            "task_id": "t-1", "type": "document", "content": "Overview\nFailure case"})
        before = self.store.read_events("p-1")
        self.reject(command, "ACTOR_MISMATCH", actor="a-2")
        self.assertEqual(self.store.read_events("p-1"), before)
        self.accept(command)
        self.assertIn("artifact:art-1", self.state())

    def test_policy_does_not_accept_client_approval_claims_or_unsupported_content(self):
        cases = [({"risk_level": "high"}, "APPROVAL_REQUIRED"),
                 ({"approval_required": True}, "APPROVAL_REQUIRED"),
                 ({"approval_required": False, "type": "code"}, "POLICY_DENIED"),
                 ({"policy_version": "future-policy"}, "POLICY_UNAVAILABLE"),
                 ({"source": {"path": "C:/private"}}, "INVALID_PAYLOAD"),
                 ({"content_digest": "sha256:" + "0" * 64}, "INVALID_PAYLOAD"),
                 ({"data_classification": "restricted"}, "POLICY_DENIED"),
                 ({"content": ""}, "INVALID_PAYLOAD"),
                 ({"content": "x" * 65537}, "INVALID_PAYLOAD"),
                 ({"message_ids": ["missing"]}, "INVALID_REFERENCE"),
                 ({"derived_from": ["missing"]}, "INVALID_REFERENCE")]
        for index, (change, code) in enumerate(cases):
            with self.subTest(change=list(change)):
                payload = {"task_id": "t-1", "type": "document", "content": "Overview\nFailure case"}
                payload.update(change)
                self.reject(self.command("artifact.submit", f"bad-{index}", payload), code)
        self.assertFalse(any(key.startswith("artifact:") for key in self.state()))

    def test_task_criteria_are_required_and_legacy_task_has_no_implicit_policy(self):
        for index, criteria in enumerate([[], [""], "Overview", ["Overview", "Overview"]]):
            with self.subTest(criteria=criteria):
                self.reject(self.command("task.create", f"invalid-{index}", {
                    "title": "Invalid", "acceptance_criteria": criteria}), "INVALID_PAYLOAD")
        legacy = self.command("task.create", "legacy", {"title": "Old M0 task"})
        self.assertEqual(self.fixture.handler.handle(legacy, authenticated_actor_id="a-1").status, "accepted")
        self.reject(self.command("artifact.submit", "legacy-art", {
            "task_id": "legacy", "type": "document", "content": "Text"}), "POLICY_UNAVAILABLE")

    def test_same_command_retry_has_no_second_artifact_or_review(self):
        artifact, first = self.artifact()
        events = self.store.read_events("p-1")
        command = self.command("artifact.submit", "art-1", {
            "task_id": "t-1", "type": "document", "content": artifact["content"]}, key=first.command_id)
        self.assertEqual(self.accept(command), first)
        self.assertEqual(self.store.read_events("p-1"), events)
        self.reject(replace(command, payload={**command.to_dict()["payload"], "content": "Changed"}), "IDEMPOTENCY_CONFLICT")
