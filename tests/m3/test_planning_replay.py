"""Faults and forged candidate facts must not bypass the Command chain."""

import copy
from contextlib import ExitStack
from dataclasses import replace
import sqlite3
from unittest.mock import patch

from aetp.collaboration.policy import digest_value
from aetp.core.projection import Projection
from aetp.core.runtime import RuntimeRecovery
from aetp.domain.models import Command, Event, ModelValidationError
from tests.m0.support import clear_projection_fixture, install_event_failure_fixture, install_result_failure_fixture
from tests.m3.support import PlanningCase


class PlanningReplayTests(PlanningCase):
    def facts(self):
        return self.store.read_events("p-1")

    def tampered(self, selected, payload):
        return [replace(event, payload=payload) if event.id == selected.id else event for event in self.facts()]

    def test_each_prefix_and_restart_rebuild_without_live_facilities(self):
        self.blueprint()
        self.accept(self.change(self.blueprint_content()))
        self.accept(self.control("pause"))
        self.accept(self.change(self.blueprint_content()))
        self.accept(self.control("resume"))
        events, commands, expected = self.facts(), self.commands(), self.state()
        self.assertEqual(expected["blueprint:bp-1"]["latest_proposal_version"], 3)
        self.assertIsNone(expected["blueprint:bp-1"]["active_version"])
        from aetp.runtime.document import DocumentRuntime
        from aetp.runtime.service import ExecutionService
        from aetp.workspace.documents import DocumentWorkspace
        from aetp.meetings.process import ProcessLog
        guarded = []
        with ExitStack() as stack:
            for target, name in ((self.service, "clock"), (self.service, "handle"), (self.service, "_followups"),
                                 (ExecutionService, "recover"), (ExecutionService, "dispatch"),
                                 (ExecutionService, "start_session"), (DocumentRuntime, "register"),
                                 (DocumentWorkspace, "write"), (DocumentWorkspace, "query"), (ProcessLog, "read")):
                guarded.append(stack.enter_context(patch.object(target, name, side_effect=AssertionError("Replay invoked live IO"))))
            cursor = Projection("p-1")
            for index, event in enumerate(events, 1):
                cursor.apply(event)
                prefix = events[:index]
                self.assertEqual(Projection.rebuild(prefix), cursor.state)
                receipt_ids = {item.causation_id for item in prefix if item.type == "command.received"}
                Projection.pending_command_ids(prefix, [command for command in commands if command.id in receipt_ids])
            self.assertEqual(cursor.state, expected)
            self.assertEqual(Projection.pending_command_ids(events, commands), [])
            clear_projection_fixture(self.store, project_id="p-1")
            self.assertEqual(self.store.read_projection("p-1"), expected)
            recovery = RuntimeRecovery.open(self.fixture.db_path)
            try:
                self.assertEqual(recovery.rebuild_project("p-1"), expected)
                self.assertEqual(recovery.reconcile_pending("p-1"), [])
            finally:
                recovery.close()
            self.assertTrue(all(guard.call_count == 0 for guard in guarded))

    def test_receipt_only_proposal_is_pending_and_creates_no_candidate(self):
        self.team()
        before = self.state()
        command = self.command("blueprint.propose", "bp-1", {"content": self.blueprint_content()})
        self.accept(command)
        receipt = next(event for event in self.facts() if event.causation_id == command.id and event.type == "command.received")
        prefix = self.facts()[:receipt.sequence]
        self.assertEqual(Projection.rebuild(prefix), before)
        self.assertEqual(Projection.pending_command_ids(prefix, self.commands()), [command.id])

    def test_planning_effect_requires_its_matching_receipt_even_without_command_table(self):
        self.blueprint()
        selected = next(event for event in self.facts() if event.type == "blueprint.proposed")
        events = [event for event in self.facts() if not (event.type == "command.received" and event.causation_id == selected.causation_id)]
        events = [replace(event, sequence=index) for index, event in enumerate(events, 1)]
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(events)

    def test_resealed_author_cannot_disagree_with_receipt_digest(self):
        self.team()
        selected = next(event for event in self.facts() if event.type == "team.proposed")
        payload = copy.deepcopy(selected.payload)
        payload["command"]["actor_id"] = "a-2"
        candidate = payload["record"]["versions"]["1"]
        candidate["proposed_by"] = "a-2"
        candidate.pop("content_digest")
        candidate["content_digest"] = digest_value(candidate)
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(self.tampered(selected, payload))

    def test_changed_persisted_command_and_receipt_cannot_change_effect(self):
        self.blueprint()
        selected = next(event for event in self.facts() if event.type == "blueprint.proposed")
        original = next(command for command in self.commands() if command.id == selected.causation_id)
        changed_payload = copy.deepcopy(original.payload)
        changed_payload["content"]["architecture"] = "Different architecture"
        for changed in (replace(original, actor_id="a-2"), replace(original, expected_revision=99),
                        replace(original, payload=changed_payload)):
            events = [replace(event, payload={"command_type": changed.type, "request_digest": changed.digest()})
                      if event.type == "command.received" and event.causation_id == changed.id else event for event in self.facts()]
            commands = [changed if command.id == changed.id else command for command in self.commands()]
            with self.assertRaises(ModelValidationError):
                Projection.pending_command_ids(events, commands)

    def test_record_graph_source_and_authority_tampering_are_rejected(self):
        self.blueprint()
        selected = next(event for event in self.facts() if event.type == "blueprint.proposed")
        for mutation in ("active", "source", "graph", "digest", "old_version"):
            payload = copy.deepcopy(selected.payload)
            candidate = payload["record"]["versions"]["1"]
            if mutation == "active":
                payload["record"]["active_version"] = 1
            elif mutation == "source":
                candidate["untrusted_input"] = False
            elif mutation == "graph":
                candidate["dag"]["edges"] = []
            elif mutation == "digest":
                candidate["content_digest"] = "sha256:" + "0" * 64
            else:
                payload["record"]["versions"] = {}
            with self.assertRaises(ModelValidationError):
                Projection.rebuild(self.tampered(selected, payload))

    def test_schema_cannot_fall_back_to_legacy_and_audit_cannot_smuggle_record(self):
        self.blueprint()
        selected = next(event for event in self.facts() if event.type == "blueprint.proposed")
        for marker in (None, "future-planning"):
            payload = copy.deepcopy(selected.payload)
            if marker is None:
                payload.pop("planning_schema")
            else:
                payload["planning_schema"] = marker
            with self.assertRaises(ModelValidationError):
                Projection.rebuild(self.tampered(selected, payload))
        forged = replace(selected, type="command.rejected")
        with self.assertRaises(ModelValidationError):
            Projection.rebuild([forged if event.id == selected.id else event for event in self.facts()])

    def test_configuration_replay_checks_preexisting_tasks(self):
        events = self.facts()
        configured = next(event for event in events if event.type == "project.planning_configured")
        insertion = Event("older-task", "p-1", configured.sequence, "task.created", "task", "old-task", 0,
                          "old-task-command", "test", {"title": "Task before configuration", "status": "pending"})
        events.insert(configured.sequence - 2, insertion)
        events = [replace(event, sequence=index) for index, event in enumerate(events, 1)]
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(events)

    def test_clock_regression_rejects_new_candidate_without_changing_old(self):
        first = self.team()
        self.clock_value -= 1
        self.reject(self.revise_team(self.team_content()), "CLOCK_REGRESSION")
        self.assertEqual(self.candidate("team", "team-1"), first)


class PlanningAtomicityTests(PlanningCase):
    def test_retry_returns_original_result_without_reobserving_clock(self):
        self.team()
        command = self.command("blueprint.propose", "bp-1", {"content": self.blueprint_content()})
        first = self.accept(command)
        events = self.store.read_events("p-1")
        with patch.object(self.service, "clock", side_effect=AssertionError("retry sampled clock")):
            self.assertEqual(self.accept(command), first)
        self.assertEqual(self.store.read_events("p-1"), events)
        changed = replace(command, payload={**command.payload, "source_decisions": []})
        self.reject(changed, "IDEMPOTENCY_CONFLICT")

    def test_sqlite_effect_failure_rolls_back_request_and_full_version(self):
        first = self.blueprint()
        command = self.change(self.blueprint_content())
        before_events = self.store.read_events("p-1")
        remove = install_event_failure_fixture(self, self.store, "blueprint.change_requested")
        with self.assertRaises(ValueError):
            self.service.handle(command, authenticated_actor_id=command.actor_id)
        self.assertEqual(self.store.read_events("p-1"), before_events)
        self.assertEqual(self.candidate("blueprint", "bp-1"), first)
        self.assertIsNone(self.store.read_idempotency(("p-1", command.actor_id, command.idempotency_key)))
        remove()
        self.accept(command)
        self.assertEqual(self.candidate("blueprint", "bp-1")["version"], 2)

    def test_sqlite_result_failure_does_not_leave_accepted_planning_effect(self):
        first = self.team()
        command = self.revise_team(self.team_content())
        before_events = self.store.read_events("p-1")
        remove = install_result_failure_fixture(self, self.store)
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.handle(command, authenticated_actor_id=command.actor_id)
        self.assertEqual(self.store.read_events("p-1"), before_events)
        self.assertEqual(self.candidate("team", "team-1"), first)
        remove()
        self.accept(command)
