import json

from aetp.core.projection import Projection
from tests.m2.support import MeetingCase


class DecisionTests(MeetingCase):
    def test_missing_members_stay_in_the_consensus_denominator(self):
        self.open_discussion()
        self.post("d", position="A")
        self.synthesize("d")
        decision = self.propose("d")
        self.assertEqual(decision["consensus_level"], 0.5)
        self.assertEqual(decision["missing_participants"], ["a-2"])

    def test_changed_position_does_not_erase_old_dissent(self):
        self.open_discussion()
        self.post("d", actor="a-2", position="B", category="disagreement", content="Keep the earlier concern")
        self.post("d", actor="a-2", position="A", category="agreement")
        self.synthesize("d")
        decision = self.propose("d")
        self.assertEqual(decision["supporting_agents"], ["a-2"])
        self.assertIn("Keep the earlier concern", json.dumps(decision["minority_opinions"]))

    def test_dissent_survives_finalization_and_process_compaction(self):
        self.open_discussion()
        self.post("d", position="A", content="Prefer A")
        self.post("d", actor="a-2", position="B", category="disagreement", content="B avoids a risk")
        self.synthesize("d")
        decision = self.propose("d")
        self.assertEqual(decision["supporting_agents"], ["a-1"])
        self.assertEqual(decision["minority_opinions"][0]["author_id"], "a-2")
        self.assertEqual(decision["minority_opinions"][0]["content"], "B avoids a risk")
        self.assertEqual(decision["consensus_level"], 0.5)
        self.accept(self.command("discussion.close", "d", {"decision_id": decision["id"]}))
        self.service.compact("p-1", "discussion", "d", authenticated_actor_id="a-1")
        replayed = Projection.rebuild(self.store.read_events("p-1"))
        self.assertEqual(replayed["decision:decision-1"], decision)
        self.assertIn("B avoids a risk", json.dumps(decision))

    def test_proposer_cannot_supply_other_agents_support_or_clear_input_trust(self):
        self.open_discussion()
        self.synthesize("d")
        base = {"title": "x", "choice": "A", "alternatives": ["A", "B"], "reasoning": "x"}
        for field, value in (("supporting_agents", ["a-1", "a-2"]), ("positions", {"a-2": "A"}), ("untrusted_input", False)):
            with self.subTest(field=field):
                self.reject(self.command("decision.propose", f"forged-{field}", {**base, field: value}), "INVALID_PAYLOAD")

    def test_direct_peer_proposal_needs_no_meeting_or_task_and_never_approves_itself(self):
        decision = self.propose(actor="a-2", risk_level="high")
        self.assertEqual((decision["proposed_by"], decision["status"]), ("a-2", "proposed"))
        self.assertTrue(decision["untrusted_input"])
        self.assertEqual(decision["authority"], "proposal_only")
        self.reject(self.command("decision.approve", decision["id"], actor="a-2"), "ENFORCEMENT_UNAVAILABLE")

    def test_supersession_creates_a_new_immutable_proposal_and_keeps_the_old_one(self):
        old = self.propose(identifier="old")
        new = self.propose(identifier="new", choice="B", supersedes={"id": "old", "digest": old["content_digest"]})
        self.assertEqual(self.state()["decision:old"], old)
        self.assertEqual(new["supersedes"]["id"], "old")
        self.assertEqual(new["status"], "proposed")
        self.reject(self.command("decision.propose", "old", {
            "title": "overwrite", "choice": "B", "alternatives": ["A", "B"], "reasoning": "x"}), "REVISION_CONFLICT")

    def test_source_revision_and_proposal_close_link_cannot_be_substituted(self):
        self.open_discussion()
        self.synthesize("d")
        self.reject(self.command("decision.propose", "stale", {
            "title": "x", "choice": "A", "alternatives": ["A", "B"], "reasoning": "x",
            "source": {"kind": "discussion", "id": "d", "revision": 0}}), "REVISION_CONFLICT")
        other = self.propose(identifier="unrelated")
        self.reject(self.command("discussion.close", "d", {"decision_id": other["id"]}), "INVALID_REFERENCE")

    def test_compaction_cannot_erase_unsettled_process_material(self):
        self.open_discussion()
        self.post("d", category="disagreement", content="Keep this objection")
        with self.assertRaisesRegex(Exception, "PROCESS_NOT_SETTLED"):
            self.service.compact("p-1", "discussion", "d", authenticated_actor_id="a-1")
        self.assertEqual(self.transcript("d")[0]["content"], "Keep this objection")
