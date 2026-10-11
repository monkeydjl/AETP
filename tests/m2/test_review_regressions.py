"""Behavioral regressions for the independent M2-01 R1/R2 findings."""

from copy import deepcopy
from dataclasses import replace
import json
from unittest.mock import patch

from aetp.collaboration.policy import PolicyViolation, canonical_json, digest_value
from aetp.core.projection import Projection
from aetp.domain.models import ModelValidationError
from aetp.meetings.process import ProcessLog
from aetp.meetings.records import Contribution, summarize
from aetp.meetings.service import MeetingService
from aetp.storage.sqlite_store import SQLiteStore
from tests.m2.support import MeetingCase


class CompactedRetryTests(MeetingCase):
    def settled(self, kind="discussion", identifier="d"):
        if kind == "discussion":
            self.open_discussion(identifier)
        else:
            self.begin_meeting(identifier)
        original = self.contribution(identifier, identifier=f"original-{identifier}", position="A",
                                     category="analysis" if kind == "meeting" else "opinion")
        receipt = self.meter.issue(original, call_id=f"call-{identifier}", tokens=2)
        accepted = self.service.post(original, authenticated_actor_id="a-1", receipt=receipt)
        self.post(identifier, actor="a-2", position="B", content="Preserve this alternative",
                  category="analysis" if kind == "meeting" else "disagreement")
        if kind == "meeting":
            self.accept(self.command("meeting.advance", identifier))
        self.synthesize(identifier)
        decision = self.propose(identifier, identifier=f"proposal-{identifier}")
        if kind == "meeting":
            self.accept(self.command("meeting.advance", identifier, {"decision_id": decision["id"]}))
        self.accept(self.command(f"{kind}.close", identifier,
                                 {"decision_id": decision["id"]} if kind == "discussion" else {}))
        self.assertEqual(self.service.post(original, authenticated_actor_id="a-1", receipt=receipt), accepted)
        self.service.compact("p-1", kind, identifier, authenticated_actor_id="a-1")
        return original, receipt, accepted

    def assert_confirmation(self, service, original, receipt, accepted):
        try:
            actual = service.post(original, authenticated_actor_id="a-1", receipt=receipt)
        except PolicyViolation as exc:
            self.fail(f"Expected the original confirmation after compaction, got {exc.code}")
        self.assertEqual(actual, accepted)
        return actual

    def test_identical_retry_after_compaction_returns_the_original_for_both_process_kinds(self):
        for kind in ("discussion", "meeting"):
            with self.subTest(kind=kind):
                original, receipt, accepted = self.settled(kind, identifier=kind)
                before, usage = self.store.read_events("p-1"), self.usage(kind)
                returned = self.assert_confirmation(self.service, original, receipt, accepted)
                returned["content"] = "An edited return value cannot edit the source"
                self.assert_confirmation(self.service, original, receipt, accepted)
                self.assertEqual(self.store.read_events("p-1"), before)
                self.assertEqual(self.usage(kind), usage)
                self.assertEqual(self.transcript(kind), [])

    def test_compacted_id_conflicts_cover_the_complete_contribution_semantics(self):
        original, receipt, _ = self.settled()
        before, usage = self.store.read_events("p-1"), self.usage("d")
        for changes in ({"content": "replacement"}, {"context": "replacement context"},
                        {"category": "question"}, {"position": "B"}, {"references": ("different-reference",)}):
            with self.subTest(changes=changes), self.assertRaises(PolicyViolation) as caught:
                self.service.post(replace(original, **changes), authenticated_actor_id="a-1", receipt=receipt)
            self.assertEqual(caught.exception.code, "MESSAGE_ID_CONFLICT")
        self.assertEqual(self.store.read_events("p-1"), before)
        self.assertEqual(self.usage("d"), usage)

    def test_restart_can_confirm_a_compacted_message_without_meter_or_clock_access(self):
        original, _, accepted = self.settled()
        before, usage = self.store.read_events("p-1"), self.usage("d")
        with SQLiteStore.open(self.fixture.db_path) as other:
            service = MeetingService(other, clock=lambda: self.fail("a retry must not read the clock"))
            self.assert_confirmation(service, original, None, accepted)
        self.assertEqual(self.store.read_events("p-1"), before)
        self.assertEqual(self.usage("d"), usage)

    def test_compacted_retry_still_checks_authenticated_author_and_participation(self):
        original, receipt, _ = self.settled()
        self.accept(self.command("agent.register", "a-3", {"model_id": "model-3"}, actor="bootstrap"))
        before = self.store.read_events("p-1")
        cases = [(original, "a-2", "ACTOR_MISMATCH"),
                 (replace(original, author_id="a-3"), "a-3", "PERMISSION_DENIED"),
                 (replace(original, author_id="unknown"), "unknown", "PERMISSION_DENIED")]
        for entry, actor, code in cases:
            with self.subTest(actor=actor), self.assertRaises(PolicyViolation) as caught:
                self.service.post(entry, authenticated_actor_id=actor, receipt=receipt)
            self.assertEqual(caught.exception.code, code)
        self.assertEqual(self.store.read_events("p-1"), before)

    def test_new_or_cross_process_messages_cannot_reopen_a_compacted_process(self):
        original, receipt, _ = self.settled()
        self.settled(identifier="other")
        for entry in (replace(original, id="new"), replace(original, conversation_id="other")):
            with self.subTest(entry=entry.id), self.assertRaises(PolicyViolation) as caught:
                self.service.post(entry, authenticated_actor_id="a-1", receipt=receipt)
            self.assertEqual(caught.exception.code, "PROCESS_NOT_OPEN")
        self.assertEqual(self.usage("d"), {"messages": 2, "tokens": 3, "compacted": True})

    def test_missing_consumption_evidence_is_not_bypassed_by_a_compacted_retry(self):
        original, receipt, _ = self.settled()
        self.store._ensure_open().execute("DELETE FROM collaboration_usage")
        with self.assertRaisesRegex(PolicyViolation, "PROCESS_UNRECONCILED"):
            self.service.post(original, authenticated_actor_id="a-1", receipt=receipt)


class HistoricalCheckpointTests(MeetingCase):
    def proposal_with_history(self):
        self.ready_debate(max_rounds=4, no_new_evidence_rounds=4)
        self.post("m", content="First debate round")
        self.accept(self.command("meeting.advance", "m"))
        self.post("m", actor="a-2", content="Second debate round")
        self.synthesize("m")
        return self.propose("m")

    @staticmethod
    def rewrite_content(row):
        changed = deepcopy(row)
        changed["content"] = "A different answer, inserted after the reveal"
        entry = Contribution.from_dict({name: changed[name] for name in Contribution.__dataclass_fields__})
        changed["semantic_digest"] = entry.digest()
        changed["receipt"]["subject_digest"] = entry.digest()
        return changed

    def test_replay_rejects_each_prior_checkpoint_when_the_final_source_is_unchanged(self):
        self.proposal_with_history()
        events, commands = self.store.read_events("p-1"), self.commands()
        self.assertEqual(Projection.rebuild(events), self.state())
        self.assertEqual(Projection.pending_command_ids(events, commands), [])
        indices = [i for i, event in enumerate(events) if event.type == "meeting.advanced"
                   and event.payload["record"]["status"] == "debate"]
        self.assertEqual(len(indices), 2)
        for index in indices:
            with self.subTest(sequence=events[index].sequence):
                payload = deepcopy(events[index].payload)
                payload["record"]["checkpoint"]["digest"] = "sha256:" + "0" * 64
                changed = list(events)
                changed[index] = replace(events[index], payload=payload)
                with self.assertRaises(ModelValidationError):
                    Projection.rebuild(changed)
                with self.assertRaises(ModelValidationError):
                    Projection.pending_command_ids(changed, commands)

    def test_resealed_final_summary_cannot_hide_a_changed_independent_answer(self):
        self.proposal_with_history()
        events = self.store.read_events("p-1")
        index = next(i for i, event in enumerate(events) if event.type == "decision.proposed")
        proposal = deepcopy(events[index].payload)
        record, source = proposal["record"], proposal["record"]["source"]
        source["records"][0] = self.rewrite_content(source["records"][0])
        source["checkpoint"] = summarize(source["records"], source["participants"])
        record["source_digest"] = digest_value(source)
        record["content_digest"] = digest_value({key: value for key, value in record.items() if key != "content_digest"})
        events[index] = replace(events[index], payload=proposal)
        index = next(i for i, event in enumerate(events) if event.type == "meeting.synthesizing")
        payload = deepcopy(events[index].payload)
        payload["record"]["checkpoint"] = deepcopy(source["checkpoint"])
        events[index] = replace(events[index], payload=payload)
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(events)

    def test_process_reconciliation_checks_revealed_answers_after_more_material_arrives(self):
        self.ready_debate()
        self.post("m", content="New material after the reveal")
        connection = self.store._ensure_open()
        rows = self.transcript("m")
        rows[0] = self.rewrite_content(rows[0])
        row = rows[0]
        connection.execute("UPDATE collaboration_entries SET record=? WHERE entry_id=?",
                           (canonical_json(row), row["id"]))
        connection.execute("UPDATE collaboration_usage SET receipt=? WHERE call_id=?",
                           (canonical_json(row["receipt"]), row["receipt"]["call_id"]))
        meta = json.loads(connection.execute("SELECT metadata FROM collaboration_processes").fetchone()[0])
        meta["digest"] = digest_value(rows)
        connection.execute("UPDATE collaboration_processes SET metadata=?", (canonical_json(meta),))
        with self.assertRaisesRegex(PolicyViolation, "PROCESS_UNRECONCILED"):
            self.transcript("m")

    def test_legacy_m2_cache_rebuilds_and_allows_a_real_proposal_transaction(self):
        self.ready_debate()
        self.post("m", content="New material")
        self.synthesize("m")
        events = self.store.read_events("p-1")
        legacy = deepcopy(self.state())
        for key, row in legacy.items():
            if key.startswith(("meeting:", "discussion:")):
                row.pop("checkpoint_history", None)
        connection = self.store._ensure_open()
        connection.execute("UPDATE projections SET state_json=? WHERE project_id=?", (canonical_json(legacy), "p-1"))
        checksum = self.store._projection_digest("p-1", legacy, events[-1].sequence)
        connection.execute("UPDATE projection_meta SET projection_digest=? WHERE project_id=?", (checksum, "p-1"))
        self.assertEqual(self.state(), Projection.rebuild(events))
        self.assertEqual(self.propose("m")["status"], "proposed")
        self.assertEqual(Projection.pending_command_ids(self.store.read_events("p-1"), self.commands()), [])

    def test_compacted_meeting_history_replays_from_facts_at_every_prefix_without_process_io(self):
        decision = self.proposal_with_history()
        self.accept(self.command("meeting.advance", "m", {"decision_id": decision["id"]}))
        self.accept(self.command("meeting.close", "m"))
        self.service.compact("p-1", "meeting", "m", authenticated_actor_id="a-1")
        expected = self.state()
        events, commands = self.store.read_events("p-1"), self.commands()
        for table in ("collaboration_entries", "collaboration_usage", "collaboration_processes"):
            self.store._ensure_open().execute(f"DROP TABLE {table}")
        with patch.object(ProcessLog, "read", side_effect=AssertionError("process IO")), \
             patch.object(self.meter, "verify", side_effect=AssertionError("meter")), \
             patch.object(self.service, "clock", side_effect=AssertionError("clock")):
            live = Projection()
            for index, event in enumerate(events, 1):
                live.apply(event)
                self.assertEqual(Projection.rebuild(events[:index]), live.state)
            self.assertEqual(live.state, expected)
            self.assertEqual(Projection.pending_command_ids(events, commands), [])
