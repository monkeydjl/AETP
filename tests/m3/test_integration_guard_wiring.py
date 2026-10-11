"""Shared boundary placement tests, not live declaration/merge acceptance.

SQLite tests inject a boundary rejection over genuine old event prefixes.
Projection candidate tests explicitly seed disposable private in-memory state;
they do not append those candidates to the Event Store or mint an InputReceipt.
"""

import copy
from dataclasses import replace
import unittest
from unittest.mock import patch

from aetp.core.commands import CommandHandler
from aetp.core.projection import Projection
from aetp.domain.models import Event, ModelValidationError
from aetp.collaboration.service import CollaborationService
from aetp.meetings.service import MeetingService
from aetp.governance.service import GovernanceService
from aetp.planning.service import PlanningService
from aetp.acceptance.service import AcceptanceService
from aetp.integration import guards
from tests.m3.quality_support import QualityCase
from tests.m3.integration_record_support import RecordCase
from tests.m3.test_integration_shared_guards import request, configuration


class CommandGuardWiringTests(QualityCase):
    def test_all_eight_service_entries_apply_guard_inside_writer_before_evaluate(self):
        services = [CommandHandler(self.store), CollaborationService(self.store), MeetingService(self.store),
            self.execution, GovernanceService(self.store), PlanningService(self.store),
            AcceptanceService(self.store), self.service]
        for service in services:
            for kind in ("task.complete", "task.quality.complete", "project.task_quality.configure"):
                with self.subTest(service=type(service).__name__, kind=kind):
                    before = self.state()
                    target = "p-1" if kind.startswith("project.") else "t-1"
                    command = self.command(kind, target, configuration() if target == "p-1" else {})
                    code = "INTEGRATION_SCOPE_CONFLICT" if target == "p-1" else "INTEGRATION_REQUIRED"
                    offset = len(self.store.read_events("p-1"))
                    def decision(actual, state):
                        self.assertTrue(self.store.in_transaction)
                        self.assertEqual(actual, command)
                        self.assertEqual(state, before)
                        return code  # Explicit fault injection; no persisted declaration asserted.
                    with patch.object(guards, "command_error", side_effect=decision) as boundary, patch.object(
                            service, "_evaluate", return_value=(service._rejected(command, "TEST_EVALUATOR_REACHED"), [])) as evaluator:
                        result = service.handle(command, authenticated_actor_id=command.actor_id)
                    self.assertEqual(result.error_code, code)
                    boundary.assert_called_once()
                    evaluator.assert_not_called()
                    events = self.store.read_events("p-1")[offset:]
                    self.assertEqual([e.type for e in events], ["command.received", "command.rejected"])
                    self.assertEqual(self.state(), before)

    def test_idempotent_rejection_skips_guard_and_actor_mismatch_precedes_it(self):
        handler = CommandHandler(self.store)
        command = self.command("task.complete", "t-1")
        with patch.object(guards, "command_error", return_value="INTEGRATION_REQUIRED") as boundary:
            first = handler.handle(command, authenticated_actor_id="a-1")
            self.assertEqual(first.error_code, "INTEGRATION_REQUIRED")
            boundary.assert_called_once()
        events = self.store.read_events("p-1")
        with patch.object(guards, "command_error", side_effect=AssertionError("retry must not reevaluate")):
            self.assertEqual(handler.handle(command, authenticated_actor_id="a-1"), first)
            changed = replace(command, payload={"another": True})
            self.assertEqual(handler.handle(changed, authenticated_actor_id="a-1").error_code, "IDEMPOTENCY_CONFLICT")
            self.assertEqual(handler.handle(command, authenticated_actor_id="a-2").error_code, "ACTOR_MISMATCH")
        self.assertEqual(self.store.read_events("p-1"), events)

    def test_previously_accepted_configuration_retry_does_not_restore_old_policy(self):
        command = self.command("project.task_quality.configure", "p-1", configuration(), actor="human-owner")
        receipt = self.input_authority.issue(command, exposure="internal")
        first = self.service.handle(command, authenticated_actor_id="human-owner", input_receipt=receipt)
        self.assertEqual(first.status, "accepted")
        self.configure_task_quality(version="newer-policy", exempt=False)
        before, events = self.state(), self.store.read_events("p-1")
        with patch.object(guards, "command_error", side_effect=AssertionError("no retroactive re-evaluation")):
            retry = self.service.handle(command, authenticated_actor_id="human-owner", input_receipt=receipt)
        self.assertEqual(retry, first)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.store.read_events("p-1"), events)

    def test_gate_rejection_audit_and_result_rollback_together(self):
        handler = CommandHandler(self.store)
        command = self.command("task.complete", "t-1")
        before, events = self.state(), self.store.read_events("p-1")
        with patch.object(guards, "command_error", return_value="INTEGRATION_REQUIRED") as boundary:
            with patch.object(self.store, "record_idempotency_result", side_effect=RuntimeError("injected result failure")):
                with self.assertRaisesRegex(RuntimeError, "injected result failure"):
                    handler.handle(command, authenticated_actor_id="a-1")
            boundary.assert_called_once()
        self.assertEqual(self.state(), before)
        self.assertEqual(self.store.read_events("p-1"), events)
        # Reusing ID/key can only succeed if the Command and result row rolled back too.
        with patch.object(guards, "command_error", return_value="INTEGRATION_REQUIRED"):
            retry = handler.handle(command, authenticated_actor_id="a-1")
        self.assertEqual(retry.error_code, "INTEGRATION_REQUIRED")
        self.assertEqual(len(self.store.read_events("p-1")), len(events) + 2)

    def test_real_guard_on_candidate_view_persists_only_rejection_not_candidate(self):
        self.configure_task_quality(version="candidate-without-exemption", exempt=False)
        before = self.state()
        probe = RecordCase()
        probe.state, probe.at = copy.deepcopy(before), self.clock_value
        candidate = probe.result()[0][3]  # Synthetic historical proof, no live declaration.
        command = self.command("task.complete", "t-1")
        actual_guard = guards.command_error
        def candidate_view(actual, state):
            self.assertTrue(self.store.in_transaction)
            self.assertEqual(state, before)
            return actual_guard(actual, {**state, "project:p-1": candidate})
        with patch.object(guards, "command_error", side_effect=candidate_view) as boundary:
            result = CommandHandler(self.store).handle(command, authenticated_actor_id="a-1")
        boundary.assert_called_once()
        self.assertEqual(result.error_code, "INTEGRATION_REQUIRED")
        self.assertEqual(self.state(), before)
        self.assertNotIn("integration_contract", self.state()["project:p-1"])
        self.assertEqual([e.type for e in self.store.read_events("p-1")[-2:]],
                         ["command.received", "command.rejected"])

    def test_no_registry_keeps_real_quality_configuration_and_replay_unchanged(self):
        self.configure_task_quality(version="compatible-policy", exempt=False)
        state = self.state()
        self.assertNotIn("integration_contract", state["project:p-1"])
        self.assertEqual(Projection.rebuild(self.store.read_events("p-1")), state)


def event(kind="project.created", *, identifier="p-1", aggregate="project", payload=None):
    return Event(id="boundary-event", project_id="p-1", sequence=1, type=kind,
        aggregate_type=aggregate, aggregate_id=identifier, aggregate_revision=0,
        causation_id="boundary-command", correlation_id="boundary-correlation",
        payload={} if payload is None else payload)


def snapshot(projection):
    return (projection.state, projection.project_id, projection.last_sequence, dict(projection._seen),
        projection._governance_cursor, projection._planning_cursor,
        projection._acceptance_cursor, projection._quality_cursor)


class ProjectionGuardWiringTests(unittest.TestCase):
    def test_pre_guard_failure_publishes_nothing_and_event_can_retry(self):
        projection = Projection()
        value = event(payload={"status": "planning"})
        before = snapshot(projection)
        with patch.object(guards, "validate_fact", side_effect=ModelValidationError("injected pre-guard")):
            with self.assertRaisesRegex(ModelValidationError, "injected pre-guard"):
                projection.apply(value)
        self.assertEqual(snapshot(projection), before)
        projection.apply(value)
        self.assertEqual(projection.last_sequence, 1)
        projection.apply(value)
        self.assertEqual(projection.last_sequence, 1)

    def test_post_guard_failure_publishes_neither_state_nor_cursors(self):
        projection = Projection()
        value = event(payload={"status": "planning"})
        before = snapshot(projection)
        with patch.object(guards, "validate_record", side_effect=ModelValidationError("injected post-guard")):
            with self.assertRaisesRegex(ModelValidationError, "injected post-guard"):
                projection.apply(value)
        self.assertEqual(snapshot(projection), before)
        projection.apply(value)
        self.assertEqual(projection.state["project:p-1"]["status"], "planning")

    def test_unregistered_schema_cannot_hide_in_audit_or_old_domain_events(self):
        for kind in ("command.received", "command.rejected", "project.created"):
            for marker in (None, "aetp-integration-contract-1", "future"):
                with self.subTest(kind=kind, marker=marker):
                    projection = Projection()
                    before = snapshot(projection)
                    with self.assertRaisesRegex(ModelValidationError, "Integration"):
                        projection.apply(event(kind, payload={"integration_schema": marker}))
                    self.assertEqual(snapshot(projection), before)

    def test_cache_with_any_integration_key_requires_full_facts(self):
        for value in (None, {}, {"schema": "aetp-integration-contract-1", "tasks": {}}):
            with self.subTest(value=value), self.assertRaises(ValueError):
                Projection._from_cache("p-1", {"project:p-1": {"integration_contract": value}}, 0)
        Projection._from_cache("p-1", {"project:p-1": {}}, 0)

    def test_only_closed_declaration_and_rejection_dialects_are_registered(self):
        for kind in ("project.integration.declare", "git.merge"):
            self.assertEqual(request(kind).type, kind)
        for kind in ("project.integration.remove", "git.merge.execute", "git.merge.complete"):
            with self.subTest(kind=kind), self.assertRaises(ModelValidationError):
                request(kind)


class CandidateProjectionGuardTests(RecordCase):
    def setUp(self):
        super().setUp()
        self.state["project:p-1"] = self.result()[0][3]
        self.projection = Projection("p-1")
        # Explicit white-box candidate, NOT a cache or accepted live prefix.
        self.projection._state = copy.deepcopy(self.state)

    def test_required_completion_is_blocked_before_legacy_reducer_without_schema(self):
        value = event("task.completed", aggregate="task", identifier="t-1")
        before = snapshot(self.projection)
        with self.assertRaisesRegex(ModelValidationError, "required Integration"):
            self.projection.apply(value)
        self.assertEqual(snapshot(self.projection), before)

    def test_derived_project_loss_is_rejected_independently_of_old_reducer(self):
        # Fault-inject an old reducer dropping the registry; no domain logic trusted.
        value = event("project.created")
        dropped = copy.deepcopy(self.project())
        dropped.pop("integration_contract")
        before = snapshot(self.projection)
        with patch.object(Projection, "_reduce_domain", return_value=dropped):
            with self.assertRaisesRegex(ModelValidationError, "Integration declarations"):
                self.projection.apply(value)
        self.assertEqual(snapshot(self.projection), before)

    def test_unimplemented_task_status_rejected_from_derived_old_schema(self):
        value = event("task.claimed", aggregate="task", identifier="t-1")
        before = snapshot(self.projection)
        with patch("aetp.runtime.projection.reduce_record", return_value={**self.task(), "status": "integrated"}):
            with self.assertRaisesRegex(ModelValidationError, "Integration success"):
                self.projection.apply(value)
        self.assertEqual(snapshot(self.projection), before)
