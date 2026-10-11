"""Governance causal proofs, atomic compounds and effect-free fact recovery."""

import copy
import multiprocessing
import os
from dataclasses import replace
from unittest.mock import patch

from aetp.core.projection import Projection
from aetp.domain.models import Event, ModelValidationError
from aetp.runtime.policy import governance
from tests.m2.governance_support import GovernanceCase, governance_process


class GovernanceReplayTests(GovernanceCase):
    def facts(self):
        return self.store.read_events("p-1")

    def prefix_commands(self, events):
        received = {event.causation_id for event in events if event.type == "command.received"}
        return [command for command in self.commands() if command.id in received]

    def tamper_context(self, kind, change):
        events = self.facts()
        selected = next(event for event in events if event.type == kind)
        payload = copy.deepcopy(selected.payload)
        change(payload["context"])
        altered = [replace(event, payload=payload) if event.id == selected.id else event for event in events]
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(altered)
        with self.assertRaises(ModelValidationError):
            Projection.pending_command_ids(altered, self.commands())

    def test_internal_auto_grant_rejects_nonexistent_or_wrong_parent(self):
        self.request_approval(trusted=True)
        for identifier in ("absent-parent", self.commands()[0].id):
            with self.subTest(parent=identifier):
                self.tamper_context("approval.granted", lambda context: context.update(parent_command_id=identifier))

    def test_internal_child_cannot_remove_its_parent_link(self):
        self.request_approval(trusted=True)
        self.tamper_context("approval.granted", lambda context: context.pop("parent_command_id"))

    def test_governance_context_does_not_ignore_unknown_authority_fields(self):
        self.request_approval(trusted=True)
        self.tamper_context("approval.granted", lambda context: context.update(bootstrap_owner="a-1"))

    def test_governance_event_cannot_fall_back_to_legacy_reducer_without_schema_marker(self):
        self.request_approval()
        self.accept(self.grant())
        grant = next(event for event in self.facts() if event.type == "approval.granted")
        for schema in (None, "aetp-governance-unknown"):
            with self.subTest(schema=schema):
                payload = copy.deepcopy(grant.payload)
                if schema is None:
                    del payload["governance_schema"]
                else:
                    payload["governance_schema"] = schema
                events = [replace(event, payload=payload) if event.id == grant.id else event for event in self.facts()]
                with self.assertRaises(ModelValidationError):
                    Projection.rebuild(events)
                with self.assertRaises(ModelValidationError):
                    Projection.pending_command_ids(events, self.commands())

    def test_governed_project_replay_cannot_accept_a_legacy_bootstrap_pause_fact(self):
        command = self.command("project.pause", "p-1", actor="bootstrap")
        events = self.facts()
        project = self.state()["project:p-1"]
        received = Event(command.id + ":received", "p-1", len(events) + 1, "command.received", "project", "p-1",
            project["revision"], command.id, command.correlation_id,
            {"command_type": command.type, "request_digest": command.digest()})
        paused = Event(command.id + ":effect", "p-1", len(events) + 2, "project.paused", "project", "p-1",
            project["revision"] + 1, command.id, command.correlation_id,
            {"actor_id": "bootstrap", "observed_at_ms": self.clock_value, "status": "paused",
             "elapsed_ms": governance(project, self.clock_value)})
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(events + [received, paused])
        with self.assertRaises(ModelValidationError):
            Projection.pending_command_ids(events + [received, paused], self.commands() + [command])

    def test_expiry_root_requires_host_tick_trigger(self):
        self.request_approval(ttl_ms=1)
        self.clock_value += 1
        self.service.tick("p-1")
        for trigger in (None, "client_request"):
            with self.subTest(trigger=trigger):
                self.tamper_context("approval.expired", lambda context: context.update(trigger=trigger))

    def test_expiry_root_requires_deterministic_command_identity(self):
        self.request_approval(ttl_ms=1)
        self.clock_value += 1
        self.service.tick("p-1")
        expired = next(event for event in self.facts() if event.type == "approval.expired")
        prefix = [replace(event, causation_id="arbitrary-expiry-id") if event.id == expired.id else event
                  for event in self.facts() if event.sequence <= expired.sequence]
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(prefix)

    def test_child_identity_does_not_collide_when_parent_and_target_contain_delimiters(self):
        for parent, target in (("x", "y:approval.grant:z"), ("x:approval.grant:y", "z")):
            command = replace(self.request_command(target), id=parent, idempotency_key=parent)
            receipt = self.input_authority.issue(command, exposure="internal")
            result = self.service.handle(command, authenticated_actor_id="a-1", input_receipt=receipt)
            self.assertEqual(result.status, "accepted", result.to_dict())
            self.assertEqual(self.approval(target)["status"], "approved")
        self.assertEqual(sum(event.type == "approval.granted" for event in self.facts()), 2)

    def test_auto_approval_parent_is_pending_until_its_grant_fact(self):
        command = self.request_command()
        receipt = self.input_authority.issue(command, exposure="internal")
        self.assertEqual(self.service.handle(command, authenticated_actor_id="a-1", input_receipt=receipt).status, "accepted")
        requested = next(event for event in self.facts() if event.type == "approval.requested")
        prefix = self.facts()[:requested.sequence]
        self.assertEqual(Projection.rebuild(prefix)["approval:ap-1"]["status"], "pending")
        self.assertIn(command.id, Projection.pending_command_ids(prefix, self.prefix_commands(prefix)))
        self.assertEqual(Projection.pending_command_ids(self.facts(), self.commands()), [])

    def test_pause_parent_is_pending_until_intervention_fact(self):
        command = self.control("pause")
        self.accept(command)
        paused = next(event for event in self.facts() if event.type == "project.paused")
        prefix = self.facts()[:paused.sequence]
        self.assertEqual(Projection.rebuild(prefix)["project:p-1"]["status"], "paused")
        self.assertIn(command.id, Projection.pending_command_ids(prefix, self.prefix_commands(prefix)))
        self.assertEqual(Projection.pending_command_ids(self.facts(), self.commands()), [])

    def test_high_expiry_remains_pending_until_escalation_and_task_impact(self):
        self.request_approval(risk_level="high", ttl_ms=1)
        self.clock_value += 1
        self.service.tick("p-1")
        expired = next(event for event in self.facts() if event.type == "approval.expired")
        for kind in ("approval.expired", "approval.escalated"):
            with self.subTest(prefix_ends=kind):
                end = next(event.sequence for event in self.facts() if event.type == kind)
                prefix = self.facts()[:end]
                self.assertIn(expired.causation_id, Projection.pending_command_ids(prefix, self.prefix_commands(prefix)))
        self.assertEqual(Projection.pending_command_ids(self.facts(), self.commands()), [])

    def test_required_children_cannot_be_reordered(self):
        self.request_approval(risk_level="high", ttl_ms=1)
        self.clock_value += 1
        self.service.tick("p-1")
        events = self.facts()
        expired = next(event for event in events if event.type == "approval.expired")
        # Both effects individually have valid current aggregates; only their
        # required causal order distinguishes this forged history.
        tail = events[expired.sequence:]
        self.assertEqual([event.type for event in tail],
                         ["command.received", "approval.escalated", "command.received", "task.blocked"])
        reordered = events[:expired.sequence] + tail[2:] + tail[:2]
        reordered = [replace(event, sequence=index) for index, event in enumerate(reordered, 1)]
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(reordered)

    def test_unrelated_root_cannot_hide_an_omitted_required_child(self):
        self.request_approval(trusted=True)
        self.accept(self.control("pause"))
        grant = next(event for event in self.facts() if event.type == "approval.granted")
        events = [event for event in self.facts() if event.causation_id != grant.causation_id]
        events = [replace(event, sequence=index) for index, event in enumerate(events, 1)]
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(events)

    def test_rejected_audit_with_governance_envelope_cannot_complete_required_child(self):
        self.request_approval(trusted=True)
        self.accept(self.control("pause"))
        for kind in ("approval.granted", "intervention.recorded"):
            with self.subTest(child=kind):
                child = next(event for event in self.facts() if event.type == kind)
                payload = copy.deepcopy(child.payload)
                payload["error"] = {"code": "FORGED_CHILD_REJECTION"}
                payload["continuations"] = []
                altered = replace(child, type="command.rejected", payload=payload)
                events = [altered if event.id == child.id else event for event in self.facts()]
                with self.assertRaises(ModelValidationError):
                    Projection.rebuild(events)
                with self.assertRaises(ModelValidationError):
                    Projection.pending_command_ids(events, self.commands())

    def test_changed_persisted_command_and_receipt_cannot_replace_event_parameters(self):
        command = self.request_command()
        self.accept(command)
        for change in ({"actor_id": "a-2"}, {"expected_revision": 99},
                       {"payload": {**command.payload, "ttl_ms": 999}}):
            with self.subTest(change=change):
                altered = replace(command, **change)
                events = [replace(event, payload={"command_type": altered.type, "request_digest": altered.digest()})
                          if event.type == "command.received" and event.causation_id == command.id else event
                          for event in self.facts()]
                commands = [altered if item.id == command.id else item for item in self.commands()]
                with self.assertRaises(ModelValidationError):
                    Projection.pending_command_ids(events, commands)

    def test_every_event_prefix_rebuilds_without_clock_runtime_or_followup_execution(self):
        self.request_approval(trusted=True)
        self.accept(self.control("pause"))
        self.clock_value += 5
        self.accept(self.control("resume"))
        events, commands, expected = self.facts(), self.commands(), self.state()
        no_effect = AssertionError("pure Replay invoked a live facility")
        with patch.object(self.service, "clock", side_effect=no_effect), \
             patch.object(self.service, "_followups", side_effect=no_effect), \
             patch.object(self.execution, "recover", side_effect=no_effect), \
             patch.object(self.execution, "dispatch", side_effect=no_effect), \
             patch.object(self.execution, "start_session", side_effect=no_effect), \
             patch.object(self.workspace, "query", side_effect=no_effect), \
             patch.object(self.workspace, "write", side_effect=no_effect):
            cursor = Projection("p-1")
            for index, event in enumerate(events, 1):
                cursor.apply(event)
                self.assertEqual(Projection.rebuild(events[:index]), cursor.state)
            self.assertEqual(cursor.state, expected)
            self.assertEqual(Projection.pending_command_ids(events, commands), [])


class GovernanceAtomicityTests(GovernanceCase):
    def test_normal_rejected_child_rolls_back_parent_and_keeps_only_rejection_audit(self):
        before, count = self.state(), len(self.store.read_events("p-1"))
        command = self.control("pause")
        real = self.service._evaluate
        def reject_child(candidate, actor):
            if candidate.type == "intervention.record":
                return self.service._rejected(candidate, "INJECTED_CHILD_REJECTION"), []
            return real(candidate, actor)
        with patch.object(self.service, "_evaluate", side_effect=reject_child):
            result = self.reject(command, "INJECTED_CHILD_REJECTION")
        self.assertEqual(self.state(), before)
        self.assertEqual([event.type for event in self.store.read_events("p-1")[count:]],
                         ["command.received", "command.rejected"])
        self.assertFalse(any(item.type == "intervention.record" for item in self.commands()))
        self.assertEqual(self.service.handle(command, authenticated_actor_id=command.actor_id), result)

    def test_append_failure_after_first_child_rolls_back_whole_compound(self):
        self.request_approval(risk_level="high")
        before, events, commands = self.state(), self.store.read_events("p-1"), self.commands()
        command = self.command("approval.revoke", "ap-1", {"reason": "Stop high risk", "mode": "safety"}, actor="human-owner")
        real = self.store.append_events
        def fail_last_child(batch):
            if any(event.type == "task.blocked" for event in batch):
                raise OSError("injected append failure after escalation")
            return real(batch)
        with patch.object(self.store, "append_events", side_effect=fail_last_child):
            with self.assertRaisesRegex(OSError, "injected append failure"):
                self.service.handle(command, authenticated_actor_id=command.actor_id)
        self.assertEqual(self.state(), before)
        self.assertEqual(self.store.read_events("p-1"), events)
        self.assertEqual(self.commands(), commands)
        self.assertIsNone(self.store.read_idempotency(("p-1", command.actor_id, command.idempotency_key)))
        self.accept(command)
        self.assertEqual(self.task()["status"], "blocked")

    def test_lost_parent_response_retry_does_not_read_clock_or_repeat_children(self):
        command = self.control("pause")
        first = self.accept(command)
        before = self.store.read_events("p-1")
        with patch.object(self.service, "clock", side_effect=AssertionError("new clock")), \
             patch.object(self.service, "_followups", side_effect=AssertionError("new child")):
            self.assertEqual(self.accept(command), first)
        self.assertEqual(self.store.read_events("p-1"), before)


class GovernanceProcessTests(GovernanceCase):
    def setUp(self):
        super().setUp()
        self.process_context = multiprocessing.get_context("spawn")
        self.processes = []
        self.addCleanup(self.close_processes)

    def close_processes(self):
        for process in self.processes:
            if process.is_alive():
                process.terminate()
            process.join(5)

    def worker(self, command=None, *, mode="command", at=None, go=None):
        context = self.process_context
        ready, output, done = context.Queue(), context.Queue(), context.Event()
        go = context.Event() if go is None else go
        process = context.Process(target=governance_process,
            args=(self.fixture.db_path, mode, command.to_dict() if command else None,
                  self.clock_value if at is None else at, ready, go, output, done))
        self.processes.append(process)
        process.start()
        self.assertNotEqual(ready.get(timeout=10)["pid"], os.getpid())
        return process, go, output, done

    def finished(self, worker, *, consumed_attempt=False):
        process, _, output, done = worker
        if not consumed_attempt:
            self.assertEqual(output.get(timeout=10)["phase"], "attempting")
        message = output.get(timeout=10)
        self.assertEqual(message["phase"], "result", message)
        self.assertTrue(done.wait(5))
        process.join(5)
        self.assertEqual(process.exitcode, 0)
        return message["result"]

    def test_two_process_approvers_cannot_both_grant_the_same_revision(self):
        self.request_approval()
        go = self.process_context.Event()
        workers = [self.worker(self.grant(actor=actor), go=go) for actor in ("a-2", "human-peer")]
        go.set()
        results = [self.finished(worker) for worker in workers]
        self.assertEqual(sorted(result["status"] for result in results), ["accepted", "rejected"])
        self.assertEqual(next(result["error_code"] for result in results if result["status"] == "rejected"), "REVISION_CONFLICT")
        self.assertEqual(self.event_types().count("approval.granted"), 1)
        self.assertEqual(Projection.pending_command_ids(self.store.read_events("p-1"), self.commands()), [])

    def test_cross_process_grant_at_expiry_cannot_revive_the_expired_request(self):
        self.request_approval(ttl_ms=1)
        go = self.process_context.Event()
        grant = self.worker(self.grant(), at=1001, go=go)
        expiry = self.worker(mode="tick", at=1001, go=go)
        go.set()
        denied, expired = self.finished(grant), self.finished(expiry)
        self.assertEqual(denied["status"], "rejected")
        self.assertIn(denied["error_code"], {"APPROVAL_EXPIRED", "REVISION_CONFLICT", "APPROVAL_FINAL"})
        self.assertEqual(expired["expired_approval_ids"], ["ap-1"])
        self.assertEqual(self.approval()["status"], "expired")
        self.assertEqual(self.event_types().count("approval.expired"), 1)
        self.assertEqual(self.event_types().count("approval.escalated"), 1)
        self.assertNotIn("approval.granted", self.event_types())

    def test_other_process_revocation_waits_for_actual_write_to_release_resource_gate(self):
        self.request_approval()
        self.accept(self.grant())
        action = self.request_document()
        revoke = self.command("approval.revoke", "ap-1", {"mode": "safety", "reason": "Concurrent human revoke"}, actor="human-owner")
        worker = self.worker(revoke)
        _, go, output, done = worker
        write = self.workspace.write
        def write_while_revoker_waits(record, authorize):
            self.assertFalse(self.store.in_transaction)
            go.set()
            self.assertEqual(output.get(timeout=5)["phase"], "attempting")
            self.assertFalse(done.wait(0.2), "revocation bypassed the held resource gate")
            return write(record, authorize)
        with patch.object(self.workspace, "write", side_effect=write_while_revoker_waits):
            completed = self.execution.dispatch("p-1", action["id"], session=self.session)
        self.assertEqual(self.finished(worker, consumed_attempt=True)["status"], "accepted")
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(self.workspace.query(completed)["status"], "confirmed")
        self.assertLess(self.event_types().index("tool.completed"), self.event_types().index("approval.revoked"))
        self.assertEqual(self.approval()["impact"]["actions"][0]["status"], "completed")

    def test_other_process_pause_committed_before_dispatch_prevents_provider_call(self):
        self.request_approval()
        self.accept(self.grant())
        action = self.request_document()
        worker = self.worker(self.control("pause"))
        worker[1].set()
        self.assertEqual(self.finished(worker)["status"], "accepted")
        with patch.object(self.workspace, "write", side_effect=AssertionError("write after pause")) as write:
            with self.assertRaisesRegex(Exception, "PROJECT_PAUSED"):
                self.execution.dispatch("p-1", action["id"], session=self.session)
        write.assert_not_called()
        self.assertEqual(self.state()[f"action:{action['id']}"]["dispatch_count"], 0)
        self.assertFalse(self.workspace.path_for(action).exists())
