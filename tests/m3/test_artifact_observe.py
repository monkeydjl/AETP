"""Bootstrap evidence must come from a real observation, not a synthetic digest.

The bootstrap runner needs to prove B0..B5 before any Runtime Task or Session
exists. The only legitimate way to mint an Artifact is ``artifact.capture``,
which requires exactly those. ``artifact.observe`` is the controlled command
that fills that gap: it records a document observation made by an Agent under
its own name, in a fixed and replayable shape, and nothing else.

These cases pin the contract (who may observe what) and the refusal paths.
"""


from aetp.acceptance.service import AcceptanceService
from tests.m3.support import PlanningCase

CONTENT = '{"b0":"discovery facts","python":"3.14"}'


class ArtifactObserveTests(PlanningCase):
    configure_scope = False

    def setUp(self):
        super().setUp()
        self.service = AcceptanceService(self.store, owner_id="human-owner", clock=lambda: self.clock_value)
        self.observe_payload = {"content": CONTENT, "observer_note": "B0 environment discovery"}

    def observe(self, identifier="proof-b0", payload=None, *, actor="a-1", authenticated=None):
        payload = self.observe_payload if payload is None else payload
        command = self.command("artifact.observe", identifier, payload, actor=actor)
        return self.service.handle(command, authenticated_actor_id=authenticated or actor)

    def test_agent_observation_is_recorded_as_a_real_document(self):
        result = self.observe()
        self.assertEqual(result.status, "accepted", result.to_dict())
        artifact = self.state()["artifact:proof-b0"]
        self.assertEqual(artifact["type"], "document")
        self.assertEqual(artifact["created_by"], "a-1")
        self.assertEqual(artifact["content"], CONTENT)
        # ``digest`` is the record digest over the whole Artifact; the content
        # digest is recomputed from the bytes the observer supplied.
        from aetp.collaboration.policy import digest_text
        self.assertEqual(artifact["content_digest"], digest_text(CONTENT))
        self.assertNotEqual(artifact["content_digest"], artifact["digest"])
        self.assertEqual(artifact["origin"]["kind"], "agent_observation")

    def test_observed_digest_recomputes_from_recorded_content(self):
        from aetp.collaboration.policy import digest_text
        self.assertEqual(self.observe().status, "accepted")
        artifact = self.state()["artifact:proof-b0"]
        self.assertEqual(artifact["content_digest"], digest_text(CONTENT))

    def test_observation_cannot_claim_another_author(self):
        result = self.observe(payload={"content": CONTENT, "created_by": "a-2"})
        self.assertEqual((result.status, result.error_code), ("rejected", "INVALID_PAYLOAD"))

    def test_observation_requires_the_authenticated_actor(self):
        # The core handler refuses a declared actor that differs from the
        # authenticated channel actor before the rule ever runs.
        result = self.observe(authenticated="a-2")
        self.assertEqual((result.status, result.error_code), ("rejected", "ACTOR_MISMATCH"))

    def test_observer_must_be_an_agent(self):
        result = self.observe(actor="human-owner")
        self.assertEqual((result.status, result.error_code), ("rejected", "PERMISSION_DENIED"))

    def test_observation_cannot_overwrite_an_existing_artifact(self):
        self.assertEqual(self.observe().status, "accepted")
        result = self.observe()
        self.assertEqual((result.status, result.error_code), ("rejected", "REVISION_CONFLICT"))

    def test_observation_requires_a_note_and_content(self):
        for payload in ({"content": CONTENT}, {"observer_note": "no content"},
                        {"content": "", "observer_note": "empty"}, {"content": CONTENT, "observer_note": ""}):
            with self.subTest(payload=payload):
                result = self.observe("proof-x", payload)
                self.assertEqual((result.status, result.error_code), ("rejected", "INVALID_PAYLOAD"))

    def test_observation_is_a_real_artifact_for_mission_evidence(self):
        from aetp.acceptance.mission import evidence_artifact
        self.assertEqual(self.observe().status, "accepted")
        artifact = self.state()["artifact:proof-b0"]
        resolved = evidence_artifact(self.state(), "proof-b0", artifact["content_digest"], "p-1")
        self.assertEqual(resolved["id"], "proof-b0")

    def test_observed_artifact_cannot_be_forged_by_a_different_digest(self):
        from aetp.acceptance.mission import evidence_artifact
        from aetp.collaboration.policy import PolicyViolation
        self.assertEqual(self.observe().status, "accepted")
        with self.assertRaises(PolicyViolation) as caught:
            evidence_artifact(self.state(), "proof-b0", "sha256:" + "0" * 64, "p-1")
        self.assertEqual(caught.exception.code, "EVIDENCE_STALE")
