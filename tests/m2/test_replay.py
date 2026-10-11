from copy import deepcopy
from dataclasses import replace
from unittest.mock import patch

from aetp.core.commands import CommandHandler
from aetp.core.projection import Projection
from aetp.domain.models import ModelValidationError
from tests.m2.support import MeetingCase


class ReplayTests(MeetingCase):
    def finished_discussion(self):
        self.open_discussion()
        self.post("d", position="A")
        self.post("d", actor="a-2", category="disagreement", position="B", content="Permanent dissent")
        self.synthesize("d")
        decision = self.propose("d")
        self.accept(self.command("discussion.close", "d", {"decision_id": decision["id"]}))

    def test_replay_uses_only_facts_after_all_process_tables_are_removed(self):
        self.finished_discussion()
        expected = self.state()
        events, commands = self.store.read_events("p-1"), self.commands()
        for table in ("collaboration_entries", "collaboration_usage", "collaboration_processes"):
            self.store._ensure_open().execute(f"DROP TABLE {table}")
        with patch("aetp.meetings.process.ProcessLog.read", side_effect=AssertionError("process IO")), \
             patch.object(self.meter, "verify", side_effect=AssertionError("meter")), \
             patch.object(self.service, "clock", side_effect=AssertionError("clock")):
            self.assertEqual(Projection.rebuild(events), expected)
            self.assertEqual(Projection.pending_command_ids(events, commands), [])

    def test_replay_validates_each_prefix_and_terminal_command_causality(self):
        self.finished_discussion()
        events, commands = self.store.read_events("p-1"), self.commands()
        live = Projection()
        for index, event in enumerate(events, 1):
            live.apply(event)
            self.assertEqual(Projection.rebuild(events[:index]), live.state)
        proposal = next(c for c in commands if c.type == "decision.propose")
        forged = replace(proposal, payload={**proposal.payload, "choice": "B"})
        changed = [replace(e, payload={**e.payload, "request_digest": forged.digest()})
                   if e.causation_id == proposal.id and e.type == "command.received" else e for e in events]
        with self.assertRaises(ModelValidationError):
            Projection.pending_command_ids(changed, [forged if c.id == proposal.id else c for c in commands])

    def test_forged_decision_support_is_not_accepted_as_a_fact(self):
        self.finished_discussion()
        events = self.store.read_events("p-1")
        index = next(i for i, e in enumerate(events) if e.type == "decision.proposed")
        payload = deepcopy(events[index].payload)
        payload["record"]["supporting_agents"] = ["a-1", "a-2"]
        events[index] = replace(events[index], payload=payload)
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(events)

    def test_m0_handler_audits_unsupported_m2_commands_at_correct_address(self):
        command = self.command("meeting.create", "unsupported", {"topic": "x"})
        result = CommandHandler(self.store).handle(command, authenticated_actor_id="a-1")
        self.assertEqual(result.status, "rejected")
        event = self.store.read_events("p-1")[-1]
        self.assertEqual((event.aggregate_type, event.aggregate_id), ("meeting", "unsupported"))
        self.assertEqual(Projection.pending_command_ids(self.store.read_events("p-1"), self.commands()), [])
