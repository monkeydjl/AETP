from copy import deepcopy
from dataclasses import replace

from aetp.core.projection import Projection
from aetp.domain.models import ModelValidationError
from tests.m2.support import MeetingCase


class CheckpointTests(MeetingCase):
    def test_distinct_evidence_across_messages_does_not_make_process_unfinishable(self):
        self.open_discussion()
        self.accept(self.command("task.create", "proofs", {"title": "Collected facts", "acceptance_criteria": ["fact"]}))
        refs = []
        for i in range(33):
            self.accept(self.command("artifact.submit", f"proof-{i}", {
                "task_id": "proofs", "type": "document", "content": f"fact {i}"}))
            artifact = self.state()[f"artifact:proof-{i}"]
            refs.append({"artifact_id": artifact["id"], "content_digest": artifact["content_digest"]})
        self.post("d", evidence=tuple(refs[:32]))
        self.post("d", evidence=tuple(refs[32:]))
        self.synthesize("d")
        decision = self.propose("d")
        self.assertEqual(len(decision["source"]["checkpoint"]["evidence"]), 33)

    def test_consensus_in_independent_answers_converges_when_the_phase_reveals_them(self):
        self.begin_meeting()
        self.post("m", category="analysis", position="A")
        self.post("m", actor="a-2", category="analysis", position="A")
        self.assertEqual(self.state()["meeting:m"]["status"], "individual_analysis")
        self.accept(self.command("meeting.advance", "m"))
        self.assertEqual(self.state()["meeting:m"]["status"], "synthesis")
        self.assertEqual(self.state()["meeting:m"]["termination_reason"], "consensus_threshold")

    def test_forged_phase_checkpoint_cannot_raise_the_fixed_budget(self):
        self.open_discussion(token_budget=10)
        self.post("d")
        self.synthesize("d")
        events = self.store.read_events("p-1")
        payload = deepcopy(events[-1].payload)
        payload["record"]["policy"]["token_budget"] = 1000
        events[-1] = replace(events[-1], payload=payload)
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(events)

    def test_snapshot_cannot_launder_a_historical_disagreement(self):
        self.open_discussion()
        self.post("d", actor="a-2", category="disagreement", position="B", content="Retain original")
        self.synthesize("d")
        self.propose("d")
        events = self.store.read_events("p-1")
        payload = deepcopy(events[-1].payload)
        payload["record"]["source"]["records"][0]["untrusted_input"] = False
        events[-1] = replace(events[-1], payload=payload)
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(events)
