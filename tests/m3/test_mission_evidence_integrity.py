"""B5 Acceptance must be proved by a real artifact, not by a claimed PASSED.

The bootstrap runner used to submit ``mission.verify`` with a fabricated
``artifact_id`` (``art-<criterion>``) and a synthetic digest
(``"sha256:" + f"{idx:x}".zfill(64)``) plus an extra ``runner_id`` key. Nothing
checked either: the gate only required ``artifact_id`` and ``content_digest`` to
be non-empty, so every B0..B5 criterion counted as PASSED without any document
existing. These cases pin the repair on the Acceptance gate itself.

Scope note (honest limitation): after ``project.execution.configure`` the
post-planning services deliberately route a ``mission.*`` command that is not in
their own vocabulary back to the core handler, which keeps bootstrap semantics
``UNSUPPORTED_COMMAND``. The gate is therefore exercised by calling
``validate_mission_verify`` -- the exact function ``planning/records.py``
dispatches to -- against the real projected state built by the shared
``VerificationCase`` fixture, whose document capture is a genuine Action.
"""

import copy
import unittest

from aetp.acceptance.mission import validate_mission_verify
from aetp.collaboration.policy import PolicyViolation
from aetp.domain.models import Command
from tests.m3.verification_support import VerificationCase

CRITERION = "B0 discovery evidence collected"


class MissionEvidenceIntegrityTests(VerificationCase):
    # VerificationCase gives a real document Runtime and independent author
    # (a-1) / reviewer (a-2) Tasks. Planning is NOT configured: a project in
    # candidate_only mode refuses execution commands (PLANNING_NOT_ACTIVE), so
    # mission.* here runs on a post-planning project, as it does in production.

    def setUp(self):
        super().setUp()
        self.assert_artifact = self.capture()  # real document captured from a completed Action
        self.mission_id, self.mission, self.project_of = "mission-b5", None, "p-1"
        self.staged = [self.command("mission.propose", self.mission_id, {"content": {
            "title": "Mission #0: initialize project",
            "objective": "Collect real bootstrap evidence",
            "constraints": ["Standard library only"],
            "success_criteria": [CRITERION]}}, actor="a-2"),
                        self.command("mission.activate", self.mission_id, actor="human-owner"),
                        self.command("mission.acceptance_start", self.mission_id, actor="human-owner")]
        self.mission = {"id": self.mission_id, "project_id": "p-1", "revision": 2, "status": "acceptance",
                        "success_criteria": [CRITERION], "criteria": {},
                        "active_version": "1", "versions": {"1": {"content": {"success_criteria": [CRITERION]}}}}

    # -- helpers -----------------------------------------------------------

    def verify(self, evidence, *, result="PASSED", verifier="a-2", authenticated=None, state=None,
               criterion=CRITERION):
        # ``self.mission`` is the projected record with its status normalised to
        # "accepting", so this exercises the evidence gate on a Mission that is
        # genuinely in acceptance; everything the gate reads about evidence
        # (artifacts, documents, Tasks, Projects) still comes from real state.
        self.counter += 1
        state = state or self.state()
        identifier = f"integrity-command-{self.counter}"
        command = Command(identifier, "p-1", authenticated or verifier, "mission.verify", self.mission_id,
                          {"criterion": criterion, "result": result, "evidence": evidence,
                           "verifier_id": verifier}, self.mission["revision"], identifier, "b5-integrity")
        return validate_mission_verify(command, self.mission, state, 5000)

    def evidence(self, artifact_id=None, digest=None):
        artifact = self.assert_artifact
        return {"artifact_id": artifact["id"] if artifact_id is None else artifact_id,
                "content_digest": artifact["content_digest"] if digest is None else digest}

    def assert_rejected(self, call, code):
        with self.assertRaises(PolicyViolation) as caught:
            call()
        self.assertEqual(caught.exception.code, code)

    # -- the fabricated evidence shape the runner used to emit ------------

    def test_fabricated_artifact_id_is_rejected(self):
        for index in range(6):
            with self.subTest(index=index):
                self.assert_rejected(
                    lambda index=index: self.verify(self.evidence(f"art-{CRITERION}", "sha256:" + f"{index:x}".zfill(64))),
                    "EVIDENCE_STALE")

    def test_undocumented_rationale_key_is_not_accepted(self):
        # The runner also smuggled a free-text "runner_id" into the evidence.
        self.assert_rejected(
            lambda: self.verify({**self.evidence(), "runner_id": "runner-1"}), "INVALID_PAYLOAD")

    def test_claimed_digest_must_match_the_artifact(self):
        self.assert_rejected(lambda: self.verify(self.evidence(digest="sha256:" + "a" * 64)), "EVIDENCE_STALE")
        kind, record = self.verify(self.evidence())
        self.assertEqual(kind, "mission.criteria_verified")

    def test_empty_or_truncated_digest_is_rejected(self):
        real = self.assert_artifact["content_digest"]
        for claim in ("", "sha256:", real[:-1], real + "0"):
            with self.subTest(claim=claim):
                code = "INVALID_PAYLOAD" if claim == "" else "EVIDENCE_STALE"
                self.assert_rejected(lambda claim=claim: self.verify(self.evidence(digest=claim)), code)

    def test_action_record_is_not_a_document_artifact(self):
        state = self.state()
        action = next(record for key, record in state.items() if key.startswith("action:") and record.get("status") == "completed")
        self.assert_rejected(
            lambda: self.verify(self.evidence(action["id"], action["result"]["content_digest"])), "EVIDENCE_STALE")

    def test_artifact_of_another_project_is_rejected(self):
        state = dict(self.state())
        state[self.assert_artifact and f"artifact:{self.assert_artifact['id']}"] = {
            **self.assert_artifact, "project_id": "p-other"}
        self.assert_rejected(lambda: self.verify(self.evidence(), state=state), "EVIDENCE_STALE")

    # -- PASSED needs evidence somebody else produced ----------------------

    def test_captured_document_proves_a_criterion_passed(self):
        _, record = self.verify(self.evidence())
        stored = record["criteria_verifications"][CRITERION]
        self.assertEqual(stored["result"], "PASSED")
        self.assertEqual(stored["evidence"], self.evidence())

    def test_verifier_cannot_pass_its_own_artifact(self):
        # a-1 wrote doc-1, so a-1 cannot also be the one who certifies it passed.
        self.assert_rejected(
            lambda: self.verify(self.evidence(), verifier="a-1", authenticated="a-1"), "EVIDENCE_STALE")

    def test_verifier_field_must_be_the_authenticated_actor(self):
        self.assert_rejected(
            lambda: self.verify(self.evidence(), verifier="a-1", authenticated="a-2"), "PERMISSION_DENIED")

    def test_honest_failure_may_cite_the_observation_it_refutes(self):
        _, record = self.verify(self.evidence(), result="FAILED")
        self.assertEqual(record["criteria_verifications"][CRITERION]["result"], "FAILED")

    def test_rejected_verification_leaves_the_record_untouched(self):
        before = copy.deepcopy(self.state())
        self.assert_rejected(lambda: self.verify(self.evidence(digest="sha256:" + "b" * 64)), "EVIDENCE_STALE")
        self.assertEqual(self.state(), before)

    def test_criterion_outside_the_mission_is_rejected(self):
        self.counter += 1
        self.assert_rejected(lambda: self.verify(self.evidence(), criterion="B5_bootstrap_acceptance_verified"),
                             "INVALID_CRITERION")


if __name__ == "__main__":
    unittest.main()
