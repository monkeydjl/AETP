"""M1-02 behavioral failure fixtures; not full-protocol conformance."""

import json
import multiprocessing
import os
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from aetp.collaboration.policy import PolicyViolation, canonical_json
from aetp.collaboration.service import CollaborationService
from aetp.core.commands import CommandHandler
from aetp.core.projection import Projection
from aetp.core.runtime import RuntimeRecovery
from aetp.domain.models import Event, ModelValidationError
from tests.m0.support import install_event_failure_fixture
from tests.m1.execution_support import (
    DocumentRuntime,
    ExecutionCase,
    ExecutionService,
    competing_claim,
    foreign_workspace_reconciler,
    process_document_worker,
    process_revoker,
)


class LeaseBoundaryTests(ExecutionCase):
    def test_advancing_wall_clock_uses_one_observation_for_each_atomic_event_batch(self):
        def advancing_clock():
            self.clock.advance(1)
            return self.clock()
        self.service.clock = advancing_clock
        self.claim()
        self.start()
        self.assertEqual(self.task()["status"], "in_progress")
        self.accept(self.command("project.pause", "p-1", {}, actor="bootstrap"))
        frozen = self.service.governance_time("p-1")
        self.clock.advance(1000)
        self.assertEqual(self.service.governance_time("p-1"), frozen)

    def test_claim_atomically_binds_owner_lease_and_monotonic_epoch(self):
        task = self.claim()
        binding = task["bindings"][task["current_binding_id"]]
        self.assertEqual((task["status"], task["owner_id"], task["lease_epoch"]), ("assigned", "a-1", 1))
        self.assertEqual((task["lease"]["owner_id"], task["lease"]["binding_id"], task["lease"]["lease_epoch"]),
                         ("a-1", binding["id"], 1))
        self.assertEqual(binding["agent_id"], "a-1")
        self.assertIsNone(binding["session"])
        self.assertEqual(Projection.rebuild(self.store.read_events("p-1")), self.state())

    def test_renewal_keeps_epoch_and_binding_but_extends_expiry(self):
        before = self.claim()
        self.clock.advance(10_000)
        self.accept(self.command("lease.renew", "t-1", self.fence()))
        after = self.task()
        self.assertEqual((after["lease_epoch"], after["current_binding_id"]),
                         (1, before["current_binding_id"]))
        self.assertEqual(after["lease"]["expires_at_governance_ms"] - before["lease"]["expires_at_governance_ms"], 10_000)

    def test_sqlite_failure_rolls_back_claim_owner_lease_receipt_and_idempotency(self):
        before = self.store.read_events("p-1")
        command = self.command("task.claim", "t-1", {})
        install_event_failure_fixture(self, self.store, "task.claimed")
        with self.assertRaises(ValueError) as failed:
            self.service.handle(command, authenticated_actor_id="a-1")
        self.assertIsInstance(failed.exception.__cause__, sqlite3.IntegrityError)
        self.assertIn("injected event failure", str(failed.exception.__cause__))
        self.assertEqual(self.store.read_events("p-1"), before)
        self.assertEqual((self.task()["status"], self.task()["owner_id"], self.task()["lease_epoch"]),
                         ("pending", None, 0))
        with closing(sqlite3.connect(self.fixture.db_path)) as connection:
            self.assertEqual(connection.execute("SELECT count(*) FROM commands WHERE id = ?", (command.id,)).fetchone()[0], 0)
        self.assertIsNone(self.store.read_idempotency(("p-1", "a-1", command.idempotency_key)))

    def test_two_processes_cannot_claim_the_same_revision_or_allocate_two_epochs(self):
        context = multiprocessing.get_context("spawn")
        ready, output, go = context.Queue(), context.Queue(), context.Event()
        commands = [self.command("task.claim", "t-1", {}, actor=actor) for actor in ("a-1", "a-2")]
        workers = [context.Process(target=competing_claim, args=(self.fixture.db_path, str(self.root),
                    command.to_dict(), ready, go, output)) for command in commands]
        try:
            for worker in workers:
                worker.start()
            for _ in workers:
                self.assertTrue(ready.get(timeout=15))
            go.set()
            results = [output.get(timeout=20) for _ in workers]
            for worker in workers:
                worker.join(timeout=10)
                self.assertEqual(worker.exitcode, 0)
            self.assertEqual(sorted(row.get("status", "error") for row in results), ["accepted", "rejected"], results)
            self.assertEqual(self.task()["lease_epoch"], 1)
            self.assertEqual(len(self.task()["bindings"]), 1)
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                    worker.join(5)
            ready.close()
            output.close()

    def test_legacy_handlers_cannot_change_an_execution_tasks_ownership(self):
        for index, service in enumerate((CommandHandler(self.store), CollaborationService(self.store))):
            command = self.command("task.claim", "t-1", {}, key=f"legacy-claim-{index}")
            result = service.handle(command, authenticated_actor_id="a-1")
            self.assertEqual(result.error_code, "EXECUTION_CONTEXT_REQUIRED")
        self.assertEqual(self.task()["lease_epoch"], 0)

    def test_stale_epoch_reports_and_renewals_are_archived_without_advancing_task(self):
        self.claim()
        old = self.fence()
        self.handoff()
        self.claim(actor="a-2")
        before = self.task()
        self.assertEqual(before["lease_epoch"], 2)
        for kind, payload in (("lease.renew", old), ("execution.report", {**old, "summary": "late completion"})):
            self.reject(self.command(kind, "t-1", payload), "STALE_EXECUTION")
        self.assertEqual(self.task(), before)
        with closing(sqlite3.connect(self.fixture.db_path)) as connection:
            payload = connection.execute("SELECT payload_json FROM commands WHERE type = 'execution.report'").fetchone()[0]
        self.assertEqual(json.loads(payload)["summary"], "late completion")

    def test_start_requires_runtime_channel_and_unforgeable_registered_session(self):
        self.claim()
        self.reject(self.command("execution.start", "t-1", self.fence()), "ENFORCEMENT_UNAVAILABLE")
        session = self.start()
        self.assertEqual(self.task()["status"], "in_progress")
        self.assertEqual(self.task()["bindings"][session.binding_id]["session"]["id"], session.id)
        payload = {**self.fence(), "operation": "document.write", "arguments": {"content": "hi"}}
        self.reject(self.command("tool.request", "t-1", payload), "SESSION_INVALID")
        self.reject(self.command("tool.request", "t-1", payload), "SESSION_INVALID", session=replace(session))
        self.reject(self.command("tool.request", "t-1", payload, actor="a-2"), "PERMISSION_DENIED", session=session)
        self.assertFalse(any(key.startswith("action:") for key in self.state()))

    def test_pause_freezes_lease_clock_but_does_not_extend_session_credentials(self):
        self.claim()
        self.start()
        expiry = self.task()["lease"]["expires_at_governance_ms"]
        self.clock.advance(10_000)
        self.accept(self.command("project.pause", "p-1", {}, actor="bootstrap"))
        self.clock.advance(400_000)
        self.assertEqual(self.service.governance_time("p-1"), 10_000)
        self.reject(self.command("tool.request", "t-1", {**self.fence(), "operation": "document.write",
                    "arguments": {"content": "paused"}}), "PROJECT_PAUSED", session=self.session)
        self.accept(self.command("project.resume", "p-1", {}, actor="bootstrap"))
        self.assertEqual(self.task()["lease"]["expires_at_governance_ms"], expiry)
        self.reject(self.command("tool.request", "t-1", {**self.fence(), "operation": "document.write",
                    "arguments": {"content": "expired credential"}}), "SESSION_EXPIRED", session=self.session)

    def test_expired_lease_cannot_renew_or_start_and_requeue_allocates_new_epoch(self):
        self.claim()
        self.clock.advance(400_000)
        self.reject(self.command("lease.renew", "t-1", self.fence()), "STALE_EXECUTION")
        result, session = self.service.start_session(self.command("execution.start", "t-1", self.fence()),
                                                    authenticated_actor_id="a-1")
        self.assertEqual(result.error_code, "STALE_EXECUTION")
        self.assertIsNone(session)
        self.accept(self.command("lease.revoke", "t-1", {**self.fence(), "reason": "expired"}, actor="bootstrap"))
        self.accept(self.command("task.requeue", "t-1", {}, actor="bootstrap"))
        self.claim(actor="a-2")
        self.assertEqual((self.task()["owner_id"], self.task()["lease_epoch"]), ("a-2", 2))

    def test_claim_retry_returns_original_binding_without_starting_runtime(self):
        command = self.command("task.claim", "t-1", {})
        first = self.accept(command)
        before = self.store.read_events("p-1")
        self.assertEqual(self.accept(command), first)
        self.assertEqual(self.store.read_events("p-1"), before)
        self.assertEqual(self.runtime.sessions(), {})


class DocumentBoundaryTests(ExecutionCase):
    def setUp(self):
        super().setUp()
        self.claim()
        self.start()

    def test_pending_and_in_flight_commit_before_real_document_effect_and_retry_does_not_rewrite(self):
        action = self.request("Overview\nFailure case: 保留现场。\n")
        self.assertEqual(action["status"], "pending")
        path = self.workspace.path_for(action)
        self.assertFalse(path.exists())
        actual_write = self.workspace.write
        observations = []

        def observed_write(record, authorize):
            observations.append((self.store.in_transaction, self.state()[f"action:{record['id']}"]["status"]))
            return actual_write(record, authorize)

        with patch.object(self.workspace, "write", side_effect=observed_write):
            completed = self.dispatch(action)
        self.assertEqual(observations, [(False, "in_flight")])
        self.assertEqual(completed["status"], "completed")
        self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["content"], "Overview\nFailure case: 保留现场。\n")
        before = path.read_bytes(), path.stat().st_mtime_ns
        with patch.object(self.workspace, "write", side_effect=AssertionError("duplicate external effect")):
            self.assertEqual(self.dispatch(action), completed)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)
        self.assertEqual(self.task()["status"], "in_progress")

    def test_failed_dispatch_transaction_never_touches_the_file_and_original_intent_can_dispatch(self):
        action = self.request()
        remove = install_event_failure_fixture(self, self.store, "tool.invoked")
        with self.assertRaises(ValueError):
            self.dispatch(action)
        self.assertFalse(self.workspace.path_for(action).exists())
        self.assertEqual(self.state()[f"action:{action['id']}"]["status"], "pending")
        remove()
        self.assertEqual(self.dispatch(action)["status"], "completed")

    def test_path_arguments_absolute_traversal_ads_and_other_workspace_are_all_refused(self):
        for path in ("../escape.txt", "C:\\outside.txt", "draft:secret", str(self.root.parent / "other-copy")):
            with self.subTest(path=path):
                self.reject(self.command("tool.request", "t-1", {**self.fence(), "operation": "document.write",
                    "arguments": {"content": "bad", "path": path}}), "WORKSPACE_SCOPE_DENIED", session=self.session)
        self.assertFalse(any(key.startswith("action:") for key in self.state()))

    def test_fixed_policy_rejects_approval_operations_even_if_client_labels_them_low(self):
        for operation in ("shell.execute", "network.request", "document.publish", "credential.read"):
            with self.subTest(operation=operation):
                self.reject(self.command("tool.request", "t-1", {**self.fence(), "operation": operation,
                    "arguments": {}, "risk_level": "low", "approval_required": False}), "APPROVAL_REQUIRED", session=self.session)
        self.reject(self.command("tool.request", "t-1", {**self.fence(), "operation": "unregistered.tool",
                    "arguments": {}}), "ENFORCEMENT_UNAVAILABLE", session=self.session)
        self.reject(self.command("tool.request", "t-1", {**self.fence(), "operation": "document.write",
                    "arguments": {"content": "low"}, "approval_required": True}), "APPROVAL_REQUIRED", session=self.session)
        self.assertFalse(any(key.startswith("action:") for key in self.state()))

    def test_tool_completion_claim_from_an_agent_cannot_forge_a_runtime_result(self):
        action = self.request()
        self.reject(self.command("tool.report", action["id"], {"status": "completed", "result": {}}, actor="a-1"),
                    "ENFORCEMENT_UNAVAILABLE", session=self.session)
        self.assertEqual(self.state()[f"action:{action['id']}"]["status"], "pending")
        self.assertFalse(self.workspace.path_for(action).exists())

    def test_new_binding_writes_an_independent_copy_and_preserves_the_old_document(self):
        old = self.dispatch(self.request("Agent A draft"))
        old_path = self.workspace.path_for(old)
        before = old_path.read_bytes()
        self.handoff()
        self.claim(actor="a-2")
        self.start(actor="a-2")
        new = self.dispatch(self.request("Agent B draft", actor="a-2"))
        new_path = self.workspace.path_for(new)
        self.assertNotEqual(old_path.parent, new_path.parent)
        self.assertEqual(old_path.read_bytes(), before)
        self.assertEqual(json.loads(new_path.read_text(encoding="utf-8"))["content"], "Agent B draft")

    def test_junction_in_binding_path_cannot_redirect_the_actual_write(self):
        import _winapi
        action = self.request()
        path = self.workspace.path_for(action)
        outside = self.root.parent / "outside-junction"
        outside.mkdir()
        sentinel = outside / "sentinel.txt"
        sentinel.write_text("unchanged", encoding="utf-8")
        path.parent.parent.mkdir(parents=True, exist_ok=True)
        _winapi.CreateJunction(str(outside), str(path.parent))
        result = self.dispatch(action)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(sorted(p.name for p in outside.iterdir()), ["sentinel.txt"])
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "unchanged")

    def test_missing_pinned_root_is_not_recreated_under_an_old_workspace_identity(self):
        action = self.request()
        self.root.rmdir()  # Empty fixture-owned root; no source or user data.
        self.assertEqual(self.dispatch(action)["status"], "unknown")
        self.assertFalse(self.root.exists())

    def test_hardlinked_final_object_cannot_be_written_or_treated_as_confirmed_output(self):
        action = self.request()
        path = self.workspace.path_for(action)
        path.parent.mkdir(parents=True, exist_ok=True)
        outside = self.root.parent / "outside-hardlink.txt"
        outside.write_text("keep me", encoding="utf-8")
        os.link(outside, path)
        self.assertEqual(self.dispatch(action)["status"], "unknown")
        self.assertEqual(outside.read_text(encoding="utf-8"), "keep me")
        self.assertEqual(self.service.reconcile("p-1", action["id"])["status"], "unknown")

    def test_unpublished_object_blocks_new_hardlink_before_content_write(self):
        from aetp.workspace import windows_files
        action = self.request("Overview\nFailure case\nSingle immutable document")
        target = self.workspace.path_for(action)
        outside = self.root.parent / "outside-during-write.json"
        real_stream = windows_files.file_stream
        errors = []

        @contextmanager
        def concurrent_link(handle, *, write):
            if write:
                try:
                    os.link(windows_files._native(target), windows_files._native(outside))
                except OSError as exc:
                    errors.append(exc.winerror)
            with real_stream(handle, write=write) as stream:
                yield stream

        with patch.object(windows_files, "file_stream", side_effect=concurrent_link):
            result = self.dispatch(action)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(errors), 1)
        self.assertFalse(outside.exists())
        self.assertEqual(json.loads(target.read_text(encoding="utf-8"))["content"],
                         "Overview\nFailure case\nSingle immutable document")

    def test_link_inserted_during_creation_is_rejected_before_any_content_write(self):
        from aetp.workspace import windows_files
        action = self.request()
        target = self.workspace.path_for(action)
        outside = self.root.parent / "outside-before-pin.json"
        real_open = windows_files._open

        def concurrent_link(path, access, share, disposition, flags):
            handle = real_open(path, access, share, disposition, flags)
            if disposition == 1:
                os.link(windows_files._native(target), windows_files._native(outside))
            return handle

        with patch.object(windows_files, "_open", side_effect=concurrent_link):
            result = self.dispatch(action)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(outside.read_bytes(), b"")
        self.assertEqual(self.service.reconcile("p-1", action["id"])["status"], "unknown")

    def test_failed_flush_does_not_publish_a_partial_document_or_allow_retry(self):
        action = self.request()
        target = self.workspace.path_for(action)
        with patch("aetp.workspace.documents.os.fsync", side_effect=OSError("fixture flush failure")):
            result = self.dispatch(action)
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(target.exists())
        recovery = self.service.recover("p-1")
        self.assertEqual(recovery["barrier"], "closed")
        self.assertIn(action["id"], recovery["unknown_actions"])

    def test_unavailable_unpublished_file_enforcement_prevents_content_write(self):
        from aetp.workspace import windows_files
        action = self.request()
        target = self.workspace.path_for(action)
        with patch.object(windows_files._api, "SetFileInformationByHandle", return_value=0):
            result = self.dispatch(action)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(target.read_bytes(), b"")
        self.assertEqual(self.service.reconcile("p-1", action["id"])["status"], "unknown")

    def test_pinned_parent_cannot_be_renamed_between_validation_and_file_open(self):
        from aetp.workspace import windows_files
        action = self.request()
        target = self.workspace.path_for(action)
        real_open = windows_files.open_object
        denied = []
        attempts = []

        def replace_parent(path, *, create):
            if create and Path(path) == target:
                try:
                    target.parent.rename(target.parent.with_name("moved-copy"))
                except PermissionError as exc:
                    denied.append(True)
                    attempts.append((type(exc).__name__, exc.winerror))
                except OSError as exc:
                    attempts.append((type(exc).__name__, exc.winerror))
                    raise
                else:
                    attempts.append("rename succeeded")
                    self.fail("validated directory was replaceable before file open")
            return real_open(path, create=create)

        with patch.object(windows_files, "open_object", side_effect=replace_parent):
            result = self.dispatch(action)
        self.assertEqual(result["status"], "completed", attempts)
        self.assertEqual(denied, [True])

    def test_paused_or_revoked_execution_cannot_dispatch_an_already_queued_action(self):
        action = self.request()
        self.accept(self.command("project.pause", "p-1", {}, actor="bootstrap"))
        with self.assertRaisesRegex(Exception, "PROJECT_PAUSED"):
            self.dispatch(action)
        self.assertFalse(self.workspace.path_for(action).exists())
        self.accept(self.command("lease.revoke", "t-1", {**self.fence(), "reason": "handoff"}))
        self.service.recover("p-1")
        self.assertEqual(self.state()[f"action:{action['id']}"]["status"], "cancelled")
        self.assertFalse(self.workspace.path_for(action).exists())

    def test_no_external_effect_can_run_inside_a_caller_database_transaction(self):
        action = self.request()
        with self.store.transaction():
            with self.assertRaisesRegex(RuntimeError, "transaction"):
                self.dispatch(action)
        self.assertFalse(self.workspace.path_for(action).exists())


class ProviderFailureBoundaryTests(ExecutionCase):
    """A provider that raises must be accounted for, not silently treated as safe.

    dispatch() and reconcile() each wrap the provider call in a deliberately wide
    except: an unknown outcome is the honest answer when a provider dies mid-write,
    and the alternative — a stack trace out of the effect path — would leave the
    Action IN_FLIGHT with nothing recording why. Those branches carried no test,
    so their two properties were only asserted in prose.
    """

    def setUp(self):
        super().setUp()
        self.claim()
        self.start()

    def test_dispatch_that_raises_reports_unknown_and_leaves_no_file(self):
        action = self.request()
        path = self.workspace.path_for(action)
        with patch.object(self.workspace, "write", side_effect=OSError("provider vanished")):
            result = self.dispatch(action)
        # An exception tells us the write did not report success. It does not tell
        # us the write did not happen, so the outcome is unknown, never completed.
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["reason"], "PROVIDER_OUTCOME_UNKNOWN")
        self.assertFalse(path.exists())
        self.assertEqual(self.state()[f"action:{action['id']}"]["status"], "unknown")

    def test_reconcile_that_raises_reports_unknown_rather_than_claiming_completion(self):
        action = self.request()
        with patch.object(self.workspace, "write", side_effect=OSError("provider vanished")):
            self.dispatch(action)
        with patch.object(self.workspace, "query", side_effect=RuntimeError("provider still down")):
            result = self.service.reconcile("p-1", action["id"])
        # A failed query is not evidence of non-execution; it is evidence of nothing.
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["reason"], "QUERY_UNAVAILABLE")
        self.assertEqual(self.state()[f"action:{action['id']}"]["status"], "unknown")

    def test_a_masked_provider_error_never_publishes_a_completion_receipt(self):
        action = self.request()
        with patch.object(self.workspace, "write", side_effect=OSError("provider vanished")):
            result = self.dispatch(action)
        self.assertIsNone(result.get("result"))
        with patch.object(self.workspace, "query", side_effect=RuntimeError("provider still down")):
            reconciled = self.service.reconcile("p-1", action["id"])
        self.assertIsNone(reconciled.get("result"))


class RecoveryBoundaryTests(ExecutionCase):
    def setUp(self):
        super().setUp()
        self.claim()
        self.start()

    def lose_response(self, action):
        real_write = self.workspace.write

        def effect_then_disconnect(record, authorize):
            real_write(record, authorize)
            raise ConnectionResetError("effect happened, response was lost")

        with patch.object(self.workspace, "write", side_effect=effect_then_disconnect):
            result = self.dispatch(action)
        self.assertEqual(result["status"], "unknown")
        self.assertTrue(self.workspace.path_for(action).exists())
        return result

    def test_crash_after_dispatch_marker_without_file_remains_unknown_and_blocks_fresh_intents(self):
        action = self.request()
        with patch.object(self.workspace, "write", side_effect=SystemExit("host crash before provider")):
            with self.assertRaises(SystemExit):
                self.dispatch(action)
        self.assertEqual(self.state()[f"action:{action['id']}"]["status"], "in_flight")
        self.assertFalse(self.workspace.path_for(action).exists())
        self.service = ExecutionService(self.store, self.runtime, clock=self.clock)
        with self.assertRaisesRegex(PolicyViolation, "RECOVERY_REQUIRED"):
            self.dispatch(action)
        with patch.object(self.workspace, "write", side_effect=AssertionError("recovery must not dispatch")):
            recovery = self.service.recover("p-1")
        self.assertEqual(recovery["barrier"], "closed")
        self.assertEqual(recovery["unknown_actions"], [action["id"]])
        self.assertEqual(self.state()[f"action:{action['id']}"]["status"], "unknown")
        self.reject(self.command("tool.request", "t-1", {**self.fence(), "operation": "document.write",
                    "arguments": {"content": "new key, same attempted work"}}), "RECONCILIATION_REQUIRED", session=self.session)
        self.accept(self.command("lease.revoke", "t-1", {**self.fence(), "reason": "handoff"}))
        self.reject(self.command("task.requeue", "t-1", {}), "RECONCILIATION_REQUIRED")
        self.assertEqual(len([key for key in self.state() if key.startswith("action:")]), 1)

    def test_success_with_lost_response_queries_original_identity_without_a_second_effect(self):
        action = self.lose_response(self.request("durable external document"))
        path = self.workspace.path_for(action)
        original = path.read_bytes(), path.stat().st_mtime_ns
        self.service = ExecutionService(self.store, self.runtime, clock=self.clock)
        with patch.object(self.workspace, "write", side_effect=AssertionError("blind retry")):
            recovery = self.service.recover("p-1")
            completed = self.dispatch(action)
        self.assertEqual(recovery["barrier"], "open")
        self.assertEqual((completed["id"], completed["status"], completed["dispatch_count"], completed["query_count"]),
                         (action["id"], "completed", 1, 1))
        self.assertEqual(completed["result"]["arguments_digest"], action["arguments_digest"])
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), original)

    def test_lost_completion_commit_leaves_inflight_and_is_reconciled_from_the_real_file(self):
        action = self.request("write before report transaction fails")
        remove = install_event_failure_fixture(self, self.store, "tool.completed")
        with self.assertRaises(ValueError):
            self.dispatch(action)
        self.assertEqual(self.state()[f"action:{action['id']}"]["status"], "in_flight")
        self.assertTrue(self.workspace.path_for(action).exists())
        remove()
        self.assertEqual(self.service.reconcile("p-1", action["id"])["status"], "completed")
        self.assertEqual(self.state()[f"action:{action['id']}"]["dispatch_count"], 1)

    def test_existing_file_with_wrong_action_target_content_or_digest_never_confirms_unknown(self):
        action = self.lose_response(self.request("exact result"))
        path = self.workspace.path_for(action)
        original = path.read_bytes()
        before_task = self.task()
        for field, value in (("action_id", "some-other-action"), ("object_key", "another-target"),
                             ("content", "forged body"), ("arguments_digest", "sha256:" + "0" * 64)):
            document = json.loads(original)
            document[field] = value
            path.write_text(canonical_json(document), encoding="utf-8")
            self.assertEqual(self.service.reconcile("p-1", action["id"])["status"], "unknown", field)
        self.assertEqual(self.task(), before_task)
        path.write_bytes(original)
        self.assertEqual(self.service.reconcile("p-1", action["id"])["status"], "completed")

    def test_revoked_unknown_is_reconciled_as_history_before_requeue_and_new_epoch(self):
        action = self.lose_response(self.request())
        self.accept(self.command("lease.revoke", "t-1", {**self.fence(), "reason": "handoff"}))
        before = self.task()
        self.reject(self.command("task.requeue", "t-1", {}), "RECONCILIATION_REQUIRED")
        recovered = self.service.recover("p-1")
        record = self.state()[f"action:{action['id']}"]
        self.assertEqual((record["status"], record["historical"]), ("completed", True))
        self.assertEqual(self.task(), before)
        self.assertEqual(recovered["unknown_actions"], [])
        self.accept(self.command("task.requeue", "t-1", {}))
        self.claim(actor="a-2")
        self.assertEqual(self.task()["lease_epoch"], 2)

    def test_restart_keeps_missing_session_blocked_and_cannot_remint_it_by_retrying_start(self):
        runtime = DocumentRuntime(self.workspace)
        self.service = ExecutionService(self.store, runtime, clock=self.clock)
        before = self.task()
        recovery = self.service.recover("p-1")
        self.assertEqual((recovery["barrier"], recovery["missing_sessions"]), ("closed", [self.session.id]))
        result, session = self.service.start_session(self.last_start_command, authenticated_actor_id="a-1")
        self.assertEqual(result.status, "accepted")  # Original receipt, not a fresh start.
        self.assertIsNone(session)
        self.assertEqual(runtime.sessions(), {})
        self.assertEqual(self.task(), before)
        self.reject(self.command("tool.request", "t-1", {**self.fence(), "operation": "document.write",
                    "arguments": {"content": "no recovered authority"}}), "SESSION_INVALID", session=self.session)

    def test_pure_replay_does_not_query_write_activate_or_treat_action_as_pending_command(self):
        self.lose_response(self.request())
        before_events, before_state = self.store.read_events("p-1"), self.state()
        with patch.object(self.workspace, "write", side_effect=AssertionError("Replay write")), \
             patch.object(self.workspace, "query", side_effect=AssertionError("Replay query")), \
             patch.object(self.runtime, "register", side_effect=AssertionError("Replay start")):
            recovery = RuntimeRecovery.open(self.fixture.db_path)
            try:
                self.assertEqual(recovery.rebuild_project("p-1"), before_state)
                self.assertEqual(recovery.reconcile_pending("p-1"), [])
            finally:
                recovery.close()
        self.assertEqual(self.store.read_events("p-1"), before_events)

    def test_revocation_at_provider_entry_blocks_directory_creation_as_well_as_final_file(self):
        action = self.request()
        real_write = self.workspace.write

        def revoked_before_access(record, authorize):
            self.accept(self.command("lease.revoke", "t-1", {**self.fence(), "reason": "handoff"}))
            return real_write(record, authorize)

        with patch.object(self.workspace, "write", side_effect=revoked_before_access):
            result = self.dispatch(action)
        self.assertEqual(result["status"], "unknown")
        self.assertFalse(self.workspace.path_for(action).parent.exists())
        self.assertEqual(self.task()["status"], "blocked")

    def test_receipt_only_command_keeps_recovery_barrier_closed_without_dispatch(self):
        command = self.command("tool.request", "t-1", {**self.fence(), "operation": "document.write",
                                "arguments": {"content": "receipt only, no accepted Action"}})
        with self.store.transaction():
            self.store.append_command(command)
            self.store.append_events([Event(id=f"{command.id}:received", project_id="p-1",
                sequence=self.store.next_sequence("p-1"), type="command.received", aggregate_type="task", aggregate_id="t-1",
                aggregate_revision=self.task()["revision"], causation_id=command.id, correlation_id=command.correlation_id,
                payload={"command_type": command.type, "request_digest": command.digest()})])
        state_before = self.state()
        with patch.object(self.workspace, "write", side_effect=AssertionError("receipt is not dispatch authority")):
            recovery = self.service.recover("p-1")
        self.assertEqual(recovery["barrier"], "closed")
        self.assertEqual(recovery["pending_commands"], [command.id])
        self.assertEqual(self.state(), state_before)

    def test_action_receipt_cannot_hide_a_different_persisted_request_body(self):
        self.request("Event body")
        recovery = RuntimeRecovery.open(self.fixture.db_path)
        try:
            commands = recovery._read_commands("p-1")
        finally:
            recovery.close()
        original = next(command for command in commands if command.type == "tool.request")
        modified = replace(original, payload={**original.payload, "arguments": {"content": "different persisted request"}})
        commands = [modified if command.id == original.id else command for command in commands]
        events = [replace(event, payload={"command_type": modified.type, "request_digest": modified.digest()})
                  if event.causation_id == original.id and event.type == "command.received" else event
                  for event in self.store.read_events("p-1")]
        with self.assertRaises(ModelValidationError):
            Projection.pending_command_ids(events, commands)


class CheckpointBoundaryTests(ExecutionCase):
    def setUp(self):
        super().setUp()
        self.claim()
        self.start()

    def test_checkpoint_captures_task_agent_context_remaining_work_and_confirmed_document(self):
        action = self.dispatch(self.request("Overview\nFailure case\n"))
        before = self.task()
        checkpoint = self.checkpoint()
        snapshot = checkpoint["snapshot"]
        self.assertEqual(snapshot["task"], before)
        self.assertEqual((snapshot["agent"]["id"], snapshot["agent"]["model_id"]), ("a-1", "model-1"))
        self.assertEqual(snapshot["git"]["status"], "not_applicable")
        self.assertEqual(snapshot["decisions"]["status"], "not_applicable")
        self.assertEqual(snapshot["document_actions"], [{"action_id": action["id"],
            "result_digest": action["result"]["envelope_digest"], "content_digest": action["result"]["content_digest"]}])
        self.assertEqual(snapshot["remaining_work"], ["Add recovery detail"])
        self.assertEqual(snapshot["context_snapshot"]["source"]["actor_id"], "a-1")
        self.assertTrue(snapshot["context_snapshot"]["source"]["untrusted_input"])
        snapshot["task"]["owner_id"] = "forged"
        self.assertEqual(self.task(), before)
        self.assertEqual(Projection.rebuild(self.store.read_events("p-1")), self.state())

    def test_second_agent_restores_checkpoint_and_appends_real_output_in_new_epoch(self):
        original = self.dispatch(self.request("Overview\nFailure case\n"))
        checkpoint = self.checkpoint()
        original_bytes = self.workspace.path_for(original).read_bytes()
        self.handoff()
        task = self.claim(actor="a-2")
        binding = task["bindings"][task["current_binding_id"]]
        self.assertEqual((binding["resume_checkpoint_id"], task["lease_epoch"]), (checkpoint["id"], 2))
        self.start(actor="a-2")
        restored = self.dispatch(self.request(actor="a-2", operation="document.restore",
            arguments={"checkpoint_id": checkpoint["id"]}))
        self.assertEqual(restored["status"], "completed")
        continued = self.dispatch(self.request(actor="a-2", operation="document.append",
            arguments={"source_action_id": restored["id"], "text": "Recovery: query before retry.\n"}))
        self.assertEqual(continued["status"], "completed")
        self.assertEqual(json.loads(self.workspace.path_for(continued).read_text(encoding="utf-8"))["content"],
                         "Overview\nFailure case\nRecovery: query before retry.\n")
        self.assertEqual(self.workspace.path_for(original).read_bytes(), original_bytes)
        self.assertNotEqual(self.workspace.path_for(original).parent, self.workspace.path_for(restored).parent)
        self.assertEqual(self.task()["status"], "in_progress")

    def test_restore_rechecks_actual_source_instead_of_trusting_checkpoint_metadata(self):
        original = self.dispatch(self.request("confirmed source"))
        checkpoint = self.checkpoint()
        self.handoff()
        self.claim(actor="a-2")
        self.start(actor="a-2")
        action = self.request(actor="a-2", operation="document.restore", arguments={"checkpoint_id": checkpoint["id"]})
        self.workspace.path_for(original).write_text("tampered after checkpoint", encoding="utf-8")
        self.assertEqual(self.dispatch(action)["status"], "unknown")
        self.assertFalse(self.workspace.path_for(action).exists())

    def test_checkpoint_cannot_freeze_an_unreconciled_result_as_a_confirmed_document(self):
        action = self.request()
        with patch.object(self.workspace, "write", side_effect=SystemExit("crash")):
            with self.assertRaises(SystemExit):
                self.dispatch(action)
        self.reject(self.command("checkpoint.create", "t-1", {**self.fence(),
                    "context_snapshot": "unconfirmed", "remaining_work": ["query action"]}),
                    "RECONCILIATION_REQUIRED", session=self.session)
        self.assertFalse(any(key.startswith("checkpoint:") for key in self.state()))


class ProcessBoundaryTests(ExecutionCase):
    def crash_window(self, mode, expected):
        self.claim()
        context = multiprocessing.get_context("spawn")
        output, child = context.Pipe(duplex=False)
        worker = context.Process(target=process_document_worker, args=(self.fixture.db_path, str(self.root), mode, child))
        try:
            worker.start()
            child.close()
            self.assertTrue(output.poll(15), "worker did not reach external effect boundary")
            observation = output.recv()
            self.assertIn("action_id", observation, observation)
            worker.join(10)
            self.assertEqual(worker.exitcode, 73)
            identifier = observation["action_id"]
            self.assertEqual(self.state()[f"action:{identifier}"]["status"], "in_flight")
            before_task = self.task()
            recovered = self.service.recover("p-1")
            action = self.state()[f"action:{identifier}"]
            self.assertEqual((action["status"], action["dispatch_count"], action["query_count"]), (expected, 1, 1))
            self.assertEqual(recovered["barrier"], "closed")  # Its external Session died; do not invent a new one.
            self.assertEqual(len(recovered["missing_sessions"]), 1)
            self.assertEqual(self.runtime.sessions(), {})
            self.assertEqual(self.task(), before_task)
            if expected == "completed":
                self.assertEqual(json.loads(self.workspace.path_for(action).read_text(encoding="utf-8"))["content"],
                                 "document from a separate process")
            else:
                self.assertFalse(self.workspace.path_for(action).exists())
        finally:
            if worker.is_alive():
                worker.terminate()
                worker.join(5)
            output.close()
            child.close()

    def test_process_death_after_dispatch_marker_is_unknown_and_never_retried(self):
        self.crash_window("crash_before", "unknown")

    def test_process_death_after_file_effect_is_reconciled_without_restarting_session(self):
        self.crash_window("crash_after", "completed")

    def test_process_death_before_publication_discards_bytes_and_remains_unknown(self):
        self.crash_window("crash_unpublished", "unknown")

    def test_separate_process_with_foreign_workspace_provider_cannot_reconcile_or_read_action(self):
        """A distinct process/provider cannot confirm another workspace's unresolved Action output."""
        from tests.m0.support import install_event_failure_fixture

        self.claim()
        self.start()
        action = self.request()
        source_path = self.workspace.path_for(action)

        # Fault-inject loss of the completion commit after the real provider file
        # effect. This leaves an actually unresolved Action and a genuine source
        # file for another process to query during reconciliation.
        remove_failure = install_event_failure_fixture(self, self.store, "tool.completed")
        try:
            with self.assertRaises(ValueError):
                self.dispatch(action)
        finally:
            remove_failure()
        self.assertEqual(self.state()[f"action:{action['id']}"]["status"], "in_flight")
        self.assertTrue(source_path.exists())
        before_bytes = source_path.read_bytes()

        context = multiprocessing.get_context("spawn")
        ready_parent, ready_child = context.Pipe(duplex=False)
        output_parent, output_child = context.Pipe(duplex=False)
        go = context.Event()
        foreign_root = self.root.parent / "foreign-workspace-process"
        child = context.Process(
            target=foreign_workspace_reconciler,
            args=(self.fixture.db_path, str(foreign_root), action["id"], ready_child, go, output_child),
        )
        try:
            child.start()
            ready_child.close()
            output_child.close()

            self.assertTrue(ready_parent.poll(20), "foreign provider process did not initialize")
            ready = ready_parent.recv()
            self.assertNotEqual(ready.get("provider_id"), action["workspace_provider_id"])
            self.assertNotEqual(ready.get("pid"), os.getpid())

            go.set()
            self.assertTrue(output_parent.poll(20), "foreign provider process did not report reconciliation")
            message = output_parent.recv()
            # A mismatched Provider identity is rejected at the Event/Projection
            # boundary, before the foreign provider can confirm a result.
            self.assertEqual(message.get("error"), "PolicyViolation", message)
            self.assertEqual(message.get("detail"), "WORKSPACE_MISMATCH", message)

            child.join(10)
            self.assertFalse(child.is_alive(), "foreign provider process did not exit")
            self.assertEqual(child.exitcode, 0)

            # The foreign provider could neither read/confirm nor mutate the
            # source object; the real Action remains unresolved until its owner
            # reconciles it with the matching workspace identity.
            self.assertEqual(source_path.read_bytes(), before_bytes)
            self.assertEqual(self.state()[f"action:{action['id']}"]["status"], "in_flight")
            try:
                owner_reconciliation = self.service.reconcile("p-1", action["id"])
            except PolicyViolation as exc:
                self.fail(f"foreign Provider rejection poisoned owner reconciliation: {exc.code}")
            self.assertEqual(owner_reconciliation["status"], "completed")
            self.assertEqual(source_path.read_bytes(), before_bytes)
        finally:
            go.set()
            if child.is_alive():
                child.terminate()
                child.join(5)
            ready_parent.close()
            ready_child.close()
            output_parent.close()
            output_child.close()

    def test_separate_process_revocation_cannot_pass_an_active_resource_access(self):
        self.claim()
        context = multiprocessing.get_context("spawn")
        output, writer_child = context.Pipe(duplex=False)
        release_effect = context.Event()
        writer = context.Process(target=process_document_worker,
            args=(self.fixture.db_path, str(self.root), "delayed", writer_child, release_effect))
        revoked, revoker_child = context.Pipe(duplex=False)
        revoker = None
        try:
            writer.start()
            writer_child.close()
            self.assertTrue(output.poll(15))
            inflight = output.recv()
            self.assertEqual(inflight.get("phase"), "in_flight", inflight)
            command = self.command("lease.revoke", "t-1", {**self.fence(), "reason": "handoff"})
            revoker = context.Process(target=process_revoker,
                args=(self.fixture.db_path, str(self.root), command.to_dict(), revoker_child))
            revoker.start()
            revoker_child.close()
            self.assertTrue(revoked.poll(15))
            self.assertEqual(revoked.recv(), {"phase": "attempting_revocation"})
            self.assertFalse(revoked.poll(0.25), "revocation crossed the held resource gate")
            self.assertEqual(self.task()["status"], "in_progress")
            release_effect.set()
            self.assertTrue(output.poll(15))
            result = output.recv()
            self.assertEqual(result.get("status"), "completed", result)
            self.assertTrue(revoked.poll(15))
            result = revoked.recv()
            self.assertEqual(result.get("status"), "accepted", result)
            writer.join(10)
            revoker.join(10)
            self.assertEqual((writer.exitcode, revoker.exitcode), (0, 0))
            events = self.store.read_events("p-1")
            self.assertLess(next(event.sequence for event in events if event.type == "tool.completed"),
                            next(event.sequence for event in events if event.type == "lease.revoked"))
            self.assertEqual(self.task()["status"], "blocked")
        finally:
            release_effect.set()
            for worker in (writer, revoker):
                if worker is not None and worker.is_alive():
                    worker.terminate()
                    worker.join(5)
            for pipe in (output, writer_child, revoked, revoker_child):
                pipe.close()


if __name__ == "__main__":
    import unittest
    unittest.main()
