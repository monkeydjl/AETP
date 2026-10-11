"""Regression cases for independently reproduced M1 review findings R1/R2."""

import json
import unittest

from aetp.collaboration.messages import Message
from aetp.core.runtime import RuntimeRecovery
from aetp.domain.models import ModelValidationError
from tests.m1.support import CollaborationCase


class MessageWireTests(unittest.TestCase):
    def test_json_roundtrip_preserves_origin_references_and_detaches_collections(self):
        original = Message("reply", "project", "a", ("b",), "challenge", "Check this.",
                           references=("proposal",), target_message="proposal", untrusted_input=True)
        decoded = json.loads(original.to_versioned_json())
        try:
            restored = Message.from_dict(decoded)
        except ModelValidationError as exc:
            self.fail(f"serialized Message cannot be decoded: {exc}")
        self.assertEqual(restored, original)
        self.assertEqual(restored.to_versioned_json(), original.to_versioned_json())
        decoded["recipients"].append("outsider")
        decoded["references"].append("unrelated")
        self.assertEqual(restored.recipients, ("b",))
        self.assertEqual(restored.references, ("proposal",))
        self.assertTrue(restored.untrusted_input)

    def test_wire_decoder_retains_schema_version_and_unknown_field_checks(self):
        raw = json.loads(Message("m", "p", "a", ("b",), "proposal", "text").to_versioned_json())
        for change in ({"schema_version": "99.0"}, {"unexpected": True}):
            with self.subTest(change=change), self.assertRaises(ModelValidationError):
                Message.from_dict({**raw, **change})

    def test_wire_decoder_rejects_malformed_arrays_and_reply_links(self):
        raw = json.loads(Message("m", "p", "a", ("b",), "proposal", "text").to_versioned_json())
        for change in ({"recipients": []}, {"recipients": [False]}, {"recipients": ["b", "b"]},
                       {"recipients": "b"}, {"references": [None]}, {"target_message": "missing"}):
            with self.subTest(change=change), self.assertRaises((ModelValidationError, TypeError)):
                Message.from_dict({**raw, **change})


class InheritedBoundaryTests(CollaborationCase):
    def new_task(self, identifier, *, legacy=False):
        payload = {"title": "Boundary fixture"}
        if not legacy:
            payload["acceptance_criteria"] = ["Overview"]
        command = self.command("task.create", identifier, payload)
        if legacy:
            result = self.fixture.handler.handle(command, authenticated_actor_id="a-1")
            self.assertEqual(result.status, "accepted")
        else:
            self.accept(command)

    def test_ineligible_members_cannot_claim_or_release_through_inherited_paths(self):
        for status in ("disabled", "terminated", "left", "failed"):
            actor = f"member-{status}"
            seed = self.command("agent.register", actor, {"model_id": "fixture", "status": status}, actor="bootstrap")
            self.accept(seed)
            claim_task = f"claim-{status}"
            self.new_task(claim_task)
            with self.subTest(status=status, operation="claim"):
                before = self.state()[f"task:{claim_task}"]
                self.reject(self.command("task.claim", claim_task, {}, actor=actor), "PERMISSION_DENIED")
                self.assertEqual(self.state()[f"task:{claim_task}"], before)
            # Trusted legacy M0 fixture establishes an old ineligible owner.
            # The M1 boundary must reject that owner's next operation as well.
            release_task = f"release-{status}"
            self.new_task(release_task)
            old_claim = self.command("task.claim", release_task, {}, actor=actor)
            self.assertEqual(self.fixture.handler.handle(old_claim, authenticated_actor_id=actor).status, "accepted")
            with self.subTest(status=status, operation="release"):
                before = self.state()[f"task:{release_task}"]
                self.reject(self.command("task.release", release_task, {}, actor=actor, revision=1), "PERMISSION_DENIED")
                self.assertEqual(self.state()[f"task:{release_task}"], before)

    def test_claim_and_release_cannot_bypass_fixed_policy_or_unknown_fields(self):
        cases = [({"approval_required": True}, "APPROVAL_REQUIRED"),
                 ({"risk_level": "critical"}, "APPROVAL_REQUIRED"),
                 ({"policy_version": "unavailable-policy"}, "POLICY_UNAVAILABLE"),
                 ({"approval_required": "false"}, "INVALID_PAYLOAD"),
                 ({"binding_id": "made-up"}, "INVALID_PAYLOAD")]
        for operation in ("claim", "release"):
            for index, (payload, code) in enumerate(cases):
                identifier = f"policy-{operation}-{index}"
                self.new_task(identifier)
                revision = 0
                if operation == "release":
                    self.accept(self.command("task.claim", identifier, {}))
                    revision = 1
                with self.subTest(operation=operation, payload=payload):
                    before = self.state()[f"task:{identifier}"]
                    self.reject(self.command(f"task.{operation}", identifier, payload, revision=revision), code)
                    self.assertEqual(self.state()[f"task:{identifier}"], before)

    def test_legacy_task_has_no_implicit_m1_execution_policy(self):
        self.new_task("legacy-claim", legacy=True)
        with self.subTest(operation="claim"):
            self.reject(self.command("task.claim", "legacy-claim", {}), "POLICY_UNAVAILABLE")
        self.new_task("legacy-release", legacy=True)
        old_claim = self.command("task.claim", "legacy-release", {})
        self.assertEqual(self.fixture.handler.handle(old_claim, authenticated_actor_id="a-1").status, "accepted")
        with self.subTest(operation="release"):
            self.reject(self.command("task.release", "legacy-release", {}, revision=1), "POLICY_UNAVAILABLE")

    def test_eligible_member_with_fixed_policy_can_claim_release_and_recover(self):
        self.new_task("eligible")
        payload = {"policy_version": "m1-document-candidate-v1", "risk_level": "low", "approval_required": False}
        self.accept(self.command("task.claim", "eligible", payload))
        self.accept(self.command("task.release", "eligible", payload, revision=1))
        task = self.state()["task:eligible"]
        self.assertEqual((task["status"], task["revision"], task["owner_id"]), ("pending", 2, None))
        recovery = RuntimeRecovery.open(self.fixture.db_path)
        self.addCleanup(recovery.close)
        self.assertEqual(recovery.rebuild_project("p-1"), self.state())
        self.assertEqual(recovery.reconcile_pending("p-1"), [])
