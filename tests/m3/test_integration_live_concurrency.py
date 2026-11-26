"""Real SQLite failures, two spawned processes, fact-only recovery and ordering."""
import multiprocessing
import os
import sqlite3
from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import patch

from aetp.core.projection import Projection
from aetp.core.runtime import RuntimeRecovery
from aetp.domain.models import Command, ModelValidationError
from aetp.governance.trust import InputAuthority
from aetp.integration.service import IntegrationContractService
from aetp.storage.sqlite_store import SQLiteStore
from tests.m0.support import (
    clear_projection_fixture,
    install_event_failure_fixture,
    install_result_failure_fixture,
)
from tests.m3.integration_live_support import IntegrationCase
from tests.m3.test_task_quality_replay import GUARDS


def _declaration_worker(path, data, at, barrier, output):
    """Each process owns its connection/authority; no receipt capability is pickled."""
    try:
        with SQLiteStore.open(path) as store:
            authority = InputAuthority("fixture-input-gateway")
            service = IntegrationContractService(store, owner_id="human-owner",
                input_authority=authority, clock=lambda: at)
            command = Command.from_dict(data)
            proof = authority.issue(command, exposure="internal")
            barrier.wait(timeout=30)
            result = service.handle(command, authenticated_actor_id=command.actor_id,
                                    input_receipt=proof)
            output.send({"pid": os.getpid(), "result": result.to_dict()})
    except BaseException as exc:
        output.send({"pid": os.getpid(), "error": type(exc).__name__, "message": str(exc)})
    finally:
        output.close()


class IntegrationConcurrencyTests(IntegrationCase):
    def race(self, commands):
        context = multiprocessing.get_context("spawn")
        barrier = context.Barrier(2)
        children, readers, writers = [], [], []
        try:
            for command in commands:
                reader, writer = context.Pipe(duplex=False)
                child = context.Process(target=_declaration_worker, args=(str(self.fixture.db_path),
                    command.to_dict(), self.clock_value, barrier, writer))
                readers.append(reader); writers.append(writer); children.append(child)
                child.start(); writer.close()
            messages = []
            for reader in readers:
                self.assertTrue(reader.poll(60), "spawned writer did not report")
                messages.append(reader.recv())
            for child in children:
                child.join(30)
                self.assertFalse(child.is_alive())
                self.assertEqual(child.exitcode, 0)
            self.assertEqual(len({row["pid"] for row in messages}), 2)
            self.assertNotIn(os.getpid(), [row["pid"] for row in messages])
            self.assertFalse(any("error" in row for row in messages), messages)
            self.assertEqual(Projection.pending_command_ids(self.store.read_events("p-1"), self.commands()), [])
            return [row["result"] for row in messages]
        finally:
            for pipe in readers + writers: pipe.close()
            for child in children:
                if child.pid is not None:
                    if child.is_alive(): child.terminate()
                    child.join(10)
                    if child.is_alive(): child.kill(); child.join(10)
                    if child.is_alive(): raise RuntimeError("owned test child not reaped")
                child.close()

    def assert_rollback(self, command, before, state):
        self.assertEqual(self.store.read_events("p-1"), before)
        self.assertEqual(self.state(), state)
        self.assertNotIn(command.id, [row.id for row in self.commands()])

    def test_domain_event_failure_rolls_back_command_receipt_result_and_same_key_retry(self):
        command = self.declaration()
        proof = self.input_authority.issue(command, exposure="internal")
        before, state = self.store.read_events("p-1"), self.state()
        remove = install_event_failure_fixture(self, self.store, "project.integration_declared")
        with self.assertRaises(ValueError) as caught:
            self.service.handle(command, authenticated_actor_id=command.actor_id, input_receipt=proof)
        self.assertIsInstance(caught.exception.__cause__, sqlite3.IntegrityError)
        remove()
        self.assert_rollback(command, before, state)
        result = self.service.handle(command, authenticated_actor_id=command.actor_id, input_receipt=proof)
        self.assertEqual(result.status, "accepted", result.to_dict())
        self.assertEqual(self.event_types().count("project.integration_declared"), 1)

    def test_result_failure_rolls_back_every_fact_and_same_key_can_succeed(self):
        command = self.declaration()
        before, state = self.store.read_events("p-1"), self.state()
        remove = install_result_failure_fixture(self, self.store)
        with self.assertRaises(sqlite3.IntegrityError): self.submit(command)
        remove()
        self.assert_rollback(command, before, state)
        self.assertEqual(self.submit(command).status, "accepted")

    def test_merge_rejection_result_failure_also_rolls_back(self):
        self.declare()
        command = self.merge()
        before, state = self.store.read_events("p-1"), self.state()
        remove = install_result_failure_fixture(self, self.store)
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.handle(command, authenticated_actor_id=command.actor_id)
        remove()
        self.assert_rollback(command, before, state)
        result = self.service.handle(command, authenticated_actor_id=command.actor_id)
        self.assertEqual(result.error_code, "ENFORCEMENT_UNAVAILABLE")
        self.assertEqual(self.state(), state)

    def test_lost_response_returns_saved_declaration_without_new_authority_or_clock(self):
        command, saved = self.declare()
        before = self.store.read_events("p-1")
        def transport(): raise ConnectionError("response lost after commit")
        with self.assertRaises(ConnectionError): transport()
        with patch.object(self.service, "_evaluate", side_effect=AssertionError("reevaluate")):
            result = self.service.handle(command, authenticated_actor_id=command.actor_id)
        self.assertEqual(result, saved)
        self.assertEqual(self.store.read_events("p-1"), before)

    def test_two_processes_same_project_revision_commit_one_declaration(self):
        results = self.race([self.declaration(reason="first"), self.declaration(reason="second")])
        self.assertEqual(sorted(row["status"] for row in results), ["accepted", "rejected"])
        self.assertEqual(next(row["error_code"] for row in results if row["status"] == "rejected"), "REVISION_CONFLICT")
        self.assertEqual(self.event_types().count("project.integration_declared"), 1)

    def test_two_processes_declaration_and_exemption_cannot_both_commit(self):
        declaration = self.declaration()
        exemption = self.command("project.task_quality.configure", "p-1", {
            "version": "racing-exemption", "max_evidence_age_ms": 60000,
            "integration_exemptions": [{"task_id": "t-1", "scope": "standalone_fixed_json_document", "reason": "standalone"}]},
            actor="human-owner")
        results = self.race([declaration, exemption])
        self.assertEqual(sorted(row["status"] for row in results), ["accepted", "rejected"])
        self.assertIn(next(row["error_code"] for row in results if row["status"] == "rejected"),
                      {"REVISION_CONFLICT", "INTEGRATION_SCOPE_CONFLICT"})
        project = self.state()["project:p-1"]
        policy = project["task_quality_policy"]
        exemptions = policy["versions"][policy["current_version"]]["policy"]["integration_exemptions"]
        self.assertNotEqual("integration_contract" in project, bool(exemptions))

    def test_task_revision_committed_before_writer_invalidates_declaration(self):
        command = self.declaration()
        before = self.state()["project:p-1"]
        self.enroll_quality()
        self.assertNotEqual(self.task()["revision"], command.payload["expected_task_revision"])
        self.assertEqual(self.submit(command).error_code, "REVISION_CONFLICT")
        self.assertEqual(self.state()["project:p-1"], before)

    def test_declaration_before_quality_completion_is_fail_closed(self):
        self.verified_quality()
        self.declare()
        task = self.task()
        result = self.qcall("task.quality.complete", actor="a-2")
        self.assertEqual(result.error_code, "INTEGRATION_REQUIRED")
        self.assertEqual(self.task(), task)

    def test_completed_task_cannot_later_gain_requirement(self):
        self.configure_task_quality(version="completion-exemption", exempt=True)
        self.verified_quality()
        self.quality_complete()
        self.configure_task_quality(version="completed-unexempt", exempt=False)
        command = self.declaration()
        self.assertEqual(self.submit(command).error_code, "INVALID_TRANSITION")
        self.assertEqual(self.task()["status"], "completed")
        self.assertNotIn("integration_contract", self.state()["project:p-1"])

    def test_declaration_receipt_cannot_interleave_a_quality_compound(self):
        self.ready_quality()
        self.quality_review()
        self.declare()
        events = self.store.read_events("p-1")
        start = next(i for i, event in enumerate(events) if event.type == "review.quality_requested")
        receipt = next(event for event in events if event.type == "command.received"
                       and event.payload["command_type"] == "project.integration.declare")
        projection = Projection()
        for event in events[:start + 1]: projection.apply(event)
        state, cursor = projection.state, projection._quality_cursor
        with self.assertRaises(ModelValidationError):
            projection.apply(replace(receipt, sequence=projection.last_sequence + 1))
        self.assertEqual(projection.state, state)
        self.assertIs(projection._quality_cursor, cursor)
        for event in events[start + 1:]: projection.apply(event)
        self.assertEqual(projection.state, self.state())

    def test_deleted_cache_reopen_and_readonly_recovery_use_facts_without_runtime(self):
        command, saved = self.declare()
        self.declare(version=2)
        self.service.handle(self.merge(), authenticated_actor_id="a-1")
        expected, events = self.state(), self.store.read_events("p-1")
        clear_projection_fixture(self.store, project_id="p-1")
        with SQLiteStore.open(self.fixture.db_path) as reopened:
            self.assertEqual(Projection.rebuild(reopened.read_events("p-1")), expected)
            service = IntegrationContractService(reopened)
            self.assertEqual(service.handle(command, authenticated_actor_id=command.actor_id), saved)
        recovery = RuntimeRecovery.open(self.fixture.db_path)
        try:
            with ExitStack() as stack:
                calls = [stack.enter_context(patch(name, side_effect=AssertionError(name))) for name in GUARDS]
                self.assertEqual(recovery.rebuild_project("p-1"), expected)
                self.assertEqual(recovery.reconcile_pending("p-1"), [])
                self.assertEqual(recovery.runtime_invocation_count, 0)
                for call in calls: call.assert_not_called()
        finally: recovery.close()
        self.assertEqual(self.store.read_events("p-1"), events)

    def test_corrupt_cache_cannot_erase_registry_on_next_writer(self):
        self.declare()
        with self.store.transaction():
            self.store._ensure_open().execute("UPDATE projections SET state_json = '{}' WHERE project_id = ?", ("p-1",))
        self.declare(version=2)
        history = self.state()["project:p-1"]["integration_contract"]["tasks"]["t-1"]
        self.assertEqual(set(history["versions"]), {"1", "2"})
