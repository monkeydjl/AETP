"""M0-05 read-only recovery, pure Replay and real post-commit crash fixtures.

Receipt-only fixtures are deliberate incomplete-history probes. They are not
external tool Actions and cannot arise between commits of the atomic M0 handler.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import unittest
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from aetp.core.commands import CommandResult
from aetp.core.projection import Projection
from aetp.domain.models import Event, ModelValidationError
from aetp.storage.sqlite_store import SQLiteStore
from tests.m0.support import (
    RuntimeHarness,
    clear_projection_fixture,
    kill_process_after_commit,
    make_command,
    make_task_create_command,
    new_test_db_path,
    persist_receipt_only_fixture,
)

try:
    import aetp.core.runtime as runtime_module
except ModuleNotFoundError as exc:
    if exc.name != "aetp.core.runtime":
        raise
    runtime_module = None


def state_digest(state):
    content = json.dumps(state, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


@contextmanager
def effect_tripwires():
    """Real stdlib exits plus labelled sentinels for adapters absent in M0."""
    with ExitStack() as stack:
        spies = {}
        for label, target in {
            "simulation.execute": "aetp.core.runtime.SimulatedRuntime.execute",
            "shell.Popen": "subprocess.Popen",
            "shell.system": "os.system",
            "network.socket": "socket.socket",
            "network.urlopen": "urllib.request.urlopen",
        }.items():
            spies[label] = stack.enter_context(patch(
                target, side_effect=AssertionError(f"forbidden recovery effect: {label}"),
            ))
        # M0 has no model adapter or Runtime.start API. These are forward-path
        # sentinels, NOT evidence that any real external adapter is implemented.
        for label, owner, attribute in [
            ("runtime.start_sentinel", runtime_module.SimulatedRuntime, "start"),
            ("model.invoke_sentinel", runtime_module, "invoke_model"),
        ]:
            spies[label] = stack.enter_context(patch.object(
                owner, attribute, create=True,
                side_effect=AssertionError(f"forbidden recovery effect: {label}"),
            ))
        yield spies


@contextmanager
def observe_read_only_connections():
    real_connect = sqlite3.connect
    connections, write_attempts = [], []
    forbidden = {
        sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_CREATE_INDEX, sqlite3.SQLITE_DROP_INDEX,
        sqlite3.SQLITE_ALTER_TABLE,
    }

    def authorize(action, arg1, arg2, database, trigger):
        if action in forbidden:
            write_attempts.append((action, arg1, arg2))
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    def connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connections.append(connection)
        connection.set_authorizer(authorize)
        return connection

    with patch("sqlite3.connect", side_effect=connect):
        yield connections, write_attempts


class SimulatedRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(runtime_module, "M0-05 runtime module is not implemented")
        self.simulation = runtime_module.SimulatedRuntime()

    def test_simulation_is_deterministic_and_counts_actual_calls(self):
        command = make_task_create_command()
        self.assertEqual(self.simulation.invocation_count, 0)
        first = self.simulation.execute(command)
        second = self.simulation.execute(command)
        self.assertIsInstance(first, CommandResult)
        self.assertEqual(first, second)
        self.assertEqual(first.command_id, command.id)
        self.assertEqual(first.event_ids, ())
        self.assertEqual(first.source, "simulation-only")
        self.assertEqual(first.to_dict()["source"], "simulation-only")
        self.assertIsNone(first.aggregate_revision)
        self.assertEqual(self.simulation.invocation_count, 2)
        with self.assertRaises(AttributeError):
            self.simulation.invocation_count = 100

    def test_simulation_rejects_non_command_without_counting_an_invocation(self):
        for invalid in (None, {}, "task.create", 1):
            with self.subTest(invalid=invalid), self.assertRaises(TypeError):
                self.simulation.execute(invalid)
        self.assertEqual(self.simulation.invocation_count, 0)

    def test_simulation_has_no_persistence_or_external_effects(self):
        with ExitStack() as stack:
            spies = [stack.enter_context(patch(
                target, side_effect=AssertionError("simulation cannot perform IO"),
            )) for target in ("sqlite3.connect", "subprocess.Popen", "os.system", "socket.socket")]
            result = self.simulation.execute(make_task_create_command())
        self.assertEqual(result.event_ids, ())
        self.assertEqual([spy.call_count for spy in spies], [0, 0, 0, 0])
        self.assertEqual(self.simulation.invocation_count, 1)


class ReplayRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(runtime_module, "M0-05 RuntimeRecovery is not implemented")
        self.db_path = new_test_db_path(self)
        self.harness = RuntimeHarness.open(self.db_path)
        self.addCleanup(self.harness.close)

    def recover(self, path=None):
        recovery = runtime_module.RuntimeRecovery.open(path or self.db_path)
        self.addCleanup(recovery.close)
        return recovery

    def pending(self, command_id, *, project_id="p-1"):
        command = make_command(
            command_id=command_id, project_id=project_id, actor_id="a-1",
            command_type="task.create", target_id=f"target:{command_id}",
            payload={"title": "Awaiting terminal fact"}, expected_revision=0,
            idempotency_key=command_id,
        )
        persist_receipt_only_fixture(self.harness.store, command)
        return command

    def test_restart_rebuilds_same_state_and_does_not_invoke_runtime(self):
        before = self.harness.run_demo_flow("p-1")
        self.assertEqual(before["task:demo-task"]["revision"], 2)
        self.assertEqual(before["task:demo-task"]["status"], "pending")
        self.assertEqual(self.harness.runtime.invocation_count, 3)  # Live positive control.
        self.harness.close()
        recovery = self.recover()
        after = recovery.rebuild_project("p-1")
        self.assertEqual(after, before)
        self.assertEqual(state_digest(after), state_digest(before))
        self.assertEqual(recovery.runtime_invocation_count, 0)
        self.assertEqual(recovery.reconcile_pending("p-1"), [])
        with self.assertRaises(AttributeError):
            recovery.runtime_invocation_count = 3

    def test_recovery_counter_reports_actual_simulator_calls_not_a_constant(self):
        simulation = runtime_module.SimulatedRuntime()
        with patch.object(runtime_module, "SimulatedRuntime", return_value=simulation):
            recovery = self.recover()
        self.assertEqual(recovery.runtime_invocation_count, 0)
        # Test-controlled diagnostic call, outside the recovery/replay path.
        simulation.execute(make_task_create_command())
        self.assertEqual(recovery.runtime_invocation_count, 1)
        recovery.rebuild_project("p-1")
        recovery.reconcile_pending("p-1")
        self.assertEqual(recovery.runtime_invocation_count, 1)

    def test_deleted_projection_rows_are_rebuilt_only_from_events(self):
        before = self.harness.run_demo_flow("p-1")
        clear_projection_fixture(self.harness.store, project_id="p-1")
        self.harness.close()
        recovery = self.recover()
        self.assertEqual(recovery.rebuild_project("p-1"), before)
        connection = sqlite3.connect(self.db_path)
        self.addCleanup(connection.close)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM projections").fetchone()[0], 0)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM projection_meta").fetchone()[0], 0)

    def test_projection_and_result_cache_tables_are_not_required_or_recreated(self):
        before = self.harness.run_demo_flow("p-1")
        self.harness.close()
        with sqlite3.connect(self.db_path) as connection:
            connection.executescript("DROP TABLE projections; DROP TABLE projection_meta; DROP TABLE idempotency;")
        connection.close()
        digest = hashlib.sha256(Path(self.db_path).read_bytes()).hexdigest()
        recovery = self.recover()
        self.assertEqual(recovery.rebuild_project("p-1"), before)
        self.assertEqual(recovery.reconcile_pending("p-1"), [])
        recovery.close()
        self.assertEqual(hashlib.sha256(Path(self.db_path).read_bytes()).hexdigest(), digest)

    def test_a_forged_self_consistent_cache_is_not_an_authoritative_fact(self):
        before = self.harness.run_demo_flow("p-1")
        connection = self.harness.store._ensure_open()
        forged = {"task:ghost": {"status": "completed", "owner_id": "intruder"}}
        head = self.harness.store.read_events("p-1")[-1].sequence
        with self.harness.store.transaction():
            connection.execute("UPDATE projections SET state_json = ?", (json.dumps(forged),))
            connection.execute("UPDATE projection_meta SET projection_digest = ?", (
                SQLiteStore._projection_digest("p-1", forged, head),
            ))
        self.assertEqual(self.harness.store.read_projection("p-1"), forged)
        self.assertEqual(self.recover().rebuild_project("p-1"), before)

    def test_open_replay_and_reconciliation_attempt_no_sql_writes(self):
        self.harness.run_demo_flow("p-1")
        self.pending("unresolved")
        self.harness.close()
        before = Path(self.db_path).read_bytes()
        with observe_read_only_connections() as (connections, writes):
            recovery = self.recover()
            self.assertTrue(recovery.rebuild_project("p-1"))
            self.assertEqual(recovery.reconcile_pending("p-1"), ["unresolved"])
            recovery.close()
        self.assertEqual(len(connections), 1)
        self.assertEqual(writes, [])
        self.assertEqual(Path(self.db_path).read_bytes(), before)

    def test_recovery_connection_is_enforced_read_only_by_sqlite(self):
        self.harness.close()
        connections = []
        real_connect = sqlite3.connect

        def capture(*args, **kwargs):
            connection = real_connect(*args, **kwargs)
            connections.append(connection)
            return connection

        with patch("sqlite3.connect", side_effect=capture):
            self.recover()
        self.assertEqual(len(connections), 1)
        with self.assertRaisesRegex(sqlite3.OperationalError, "readonly"):
            connections[0].execute("DELETE FROM events")

    def test_forbidden_call_tripwires_have_positive_controls_then_remain_zero(self):
        self.harness.run_demo_flow("p-1")
        self.pending("unresolved")
        self.harness.close()
        with effect_tripwires() as spies:
            for spy in spies.values():
                with self.assertRaisesRegex(AssertionError, "forbidden recovery effect"):
                    spy()  # Prove that each tripwire can detect its forbidden path.
                self.assertEqual(spy.call_count, 1)
                spy.reset_mock()
            for _ in range(3):
                recovery = self.recover()
                self.assertTrue(recovery.rebuild_project("p-1"))
                self.assertEqual(recovery.reconcile_pending("p-1"), ["unresolved"])
                self.assertEqual(recovery.runtime_invocation_count, 0)
                recovery.close()
            self.assertEqual({name: spy.call_count for name, spy in spies.items()}, {
                name: 0 for name in spies
            })

    def test_pending_ids_follow_receipt_sequence_not_lexical_order_or_task_status(self):
        self.harness.run_demo_flow("p-1")
        self.pending("z-first")
        self.pending("a-second")
        rejected = replace(make_task_create_command(), id="bad-create", idempotency_key="bad-create", payload={"title": ""})
        self.assertEqual(self.harness.handle(rejected).status, "rejected")
        recovery = self.recover()
        self.assertEqual(recovery.reconcile_pending("p-1"), ["z-first", "a-second"])
        self.assertNotIn("task:target:z-first", recovery.rebuild_project("p-1"))
        self.assertEqual(recovery.runtime_invocation_count, 0)

    def test_pending_ids_do_not_trust_a_forged_terminal_result_index(self):
        command = self.pending("still-unresolved")
        forged = CommandResult("accepted", command.id, ("fake-success",), 0, None)
        self.harness.store.record_idempotency_result(("p-1", "a-1", command.id), forged.to_dict())
        self.assertEqual(self.recover().reconcile_pending("p-1"), [command.id])

    def test_terminal_facts_resolve_pending_without_needing_result_index(self):
        command = self.pending("terminal-rejection")
        self.harness.store.append_events([Event(
            id="terminal-rejection:rejected", project_id="p-1", sequence=0,
            type="command.rejected", aggregate_type="task", aggregate_id=command.target_id,
            aggregate_revision=0, causation_id=command.id, correlation_id=command.correlation_id,
            payload={"error": {"code": "UNSUPPORTED_COMMAND"}},
        )])
        self.assertNotIn("result", self.harness.store.read_idempotency(("p-1", "a-1", command.id)))
        self.assertEqual(self.recover().reconcile_pending("p-1"), [])

    def test_projects_are_isolated_and_paused_creation_fact_remains_paused(self):
        self.harness.seed_project("p-2", status="paused")
        self.pending("p1-pending")
        self.pending("p2-pending", project_id="p-2")
        recovery = self.recover()
        self.assertEqual(recovery.reconcile_pending("p-1"), ["p1-pending"])
        self.assertEqual(recovery.reconcile_pending("p-2"), ["p2-pending"])
        self.assertEqual(recovery.rebuild_project("p-2")["project:p-2"]["status"], "paused")
        self.assertNotIn("project:p-1", recovery.rebuild_project("p-2"))
        self.assertEqual(recovery.runtime_invocation_count, 0)

    def test_every_call_uses_current_facts_and_returns_detached_data(self):
        recovery = self.recover()
        before = recovery.rebuild_project("p-1")
        before["project:p-1"]["status"] = "completed"
        self.assertEqual(self.harness.handle(make_task_create_command()).status, "accepted")
        after = recovery.rebuild_project("p-1")
        self.assertEqual(after["project:p-1"]["status"], "planning")
        self.assertIn("task:t-1", after)
        self.assertEqual(recovery.reconcile_pending("p-1"), [])
        self.pending("newly-received")
        pending = recovery.reconcile_pending("p-1")
        pending.clear()
        self.assertEqual(recovery.reconcile_pending("p-1"), ["newly-received"])

    def test_unknown_project_is_empty_and_invalid_project_is_rejected(self):
        recovery = self.recover()
        self.assertEqual(recovery.rebuild_project("unknown"), {})
        self.assertEqual(recovery.reconcile_pending("unknown"), [])
        for invalid in (None, "", " ", " p-1", "p-1 ", True, {}):
            for method in (recovery.rebuild_project, recovery.reconcile_pending):
                with self.subTest(invalid=invalid, method=method.__name__), self.assertRaises(ValueError):
                    method(invalid)

    def test_close_is_idempotent_and_closed_reads_fail(self):
        recovery = self.recover()
        recovery.close()
        recovery.close()
        for method in (recovery.rebuild_project, recovery.reconcile_pending):
            with self.assertRaises(RuntimeError):
                method("p-1")

    def test_missing_database_is_not_created_and_memory_is_not_a_recovery_source(self):
        missing = Path(self.db_path).parent / "not-created" / "missing.sqlite"
        with self.assertRaises((OSError, sqlite3.OperationalError)):
            runtime_module.RuntimeRecovery.open(str(missing))
        self.assertFalse(missing.parent.exists())
        for invalid in ("", " ", ":memory:"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                runtime_module.RuntimeRecovery.open(invalid)
        for invalid in (None, 3, {}):
            with self.subTest(invalid=invalid), self.assertRaises(TypeError):
                runtime_module.RuntimeRecovery.open(invalid)

    def test_special_characters_in_file_name_are_not_uri_options(self):
        path = Path(self.db_path).with_name("copy #mode=rw%20-\u6d4b\u8bd5.sqlite")
        before = self.harness.run_demo_flow("p-1")
        self.harness.close()
        path.write_bytes(Path(self.db_path).read_bytes())
        self.assertEqual(self.recover(str(path)).rebuild_project("p-1"), before)

    def test_invalid_schema_open_closes_connection_and_does_not_initialize_tables(self):
        path = Path(self.db_path).with_name("not-an-event-store.sqlite")
        connection = sqlite3.connect(path)
        connection.execute("CREATE TABLE unrelated (id INTEGER)")
        connection.close()
        before = path.read_bytes()
        with observe_read_only_connections() as (connections, writes):
            with self.assertRaises(sqlite3.DatabaseError):
                runtime_module.RuntimeRecovery.open(str(path))
        self.assertEqual(len(connections), 1)
        self.assertEqual(writes, [])
        with self.assertRaises(sqlite3.ProgrammingError):
            connections[0].execute("SELECT 1")
        self.assertEqual(path.read_bytes(), before)

    def test_non_database_file_fails_without_repair(self):
        path = Path(self.db_path).with_name("invalid.sqlite")
        path.write_bytes(b"this is not a database")
        with self.assertRaises(sqlite3.DatabaseError):
            runtime_module.RuntimeRecovery.open(str(path))
        self.assertEqual(path.read_bytes(), b"this is not a database")

    def test_missing_event_in_durable_history_fails_closed_even_with_valid_cache(self):
        self.harness.run_demo_flow("p-1")
        self.harness.store._ensure_open().execute("DELETE FROM events WHERE sequence = 3 AND project_id = 'p-1'")
        recovery = self.recover()
        for method in (recovery.rebuild_project, recovery.reconcile_pending):
            with self.assertRaisesRegex(ModelValidationError, "sequence"):
                method("p-1")
        self.assertEqual(recovery.runtime_invocation_count, 0)

    def test_unsupported_history_fails_closed_instead_of_starting_runtime(self):
        self.harness.run_demo_flow("p-1")
        self.harness.store._ensure_open().execute(
            "UPDATE events SET type = 'task.started' WHERE type = 'task.claimed'"
        )
        recovery = self.recover()
        with effect_tripwires() as spies:
            for method in (recovery.rebuild_project, recovery.reconcile_pending):
                with self.assertRaisesRegex(ModelValidationError, "unsupported"):
                    method("p-1")
            self.assertTrue(all(spy.call_count == 0 for spy in spies.values()))

    def test_retry_after_response_loss_on_fresh_connection_returns_original_result(self):
        command = make_task_create_command(title="\u4efb\u52a1\u6062\u590d")
        before_count = self.harness.domain_event_count("p-1")
        original = self.harness.commit_then_drop_response(command)
        self.harness.close()
        recovery = self.recover()
        self.assertEqual(recovery.rebuild_project("p-1")["task:t-1"]["title"], "\u4efb\u52a1\u6062\u590d")
        fresh = RuntimeHarness.open(self.db_path)
        self.addCleanup(fresh.close)
        events_before = fresh.store.read_events("p-1")
        for _ in range(3):
            self.assertEqual(fresh.handle(command), original)
        self.assertEqual(fresh.store.read_events("p-1"), events_before)
        self.assertEqual(fresh.domain_event_count("p-1"), before_count + 1)
        self.assertEqual(recovery.runtime_invocation_count, 0)
        self.assertEqual(fresh.runtime.invocation_count, 0)

    def test_real_process_death_after_commit_preserves_original_result_and_single_effect(self):
        command = make_task_create_command()
        before = self.harness.domain_event_count("p-1")
        self.harness.close()
        original, observation = kill_process_after_commit(self.db_path, command)
        self.assertNotEqual(observation["pid"], os.getpid())
        self.assertNotEqual(observation["exit_code"], 0)
        self.assertEqual(original.status, "accepted")
        recovery = self.recover()
        self.assertEqual(recovery.rebuild_project("p-1")["task:t-1"]["status"], "pending")
        fresh = RuntimeHarness.open(self.db_path)
        self.addCleanup(fresh.close)
        durable_events = fresh.store.read_events("p-1")
        self.assertEqual(fresh.handle(command), original)
        self.assertEqual(fresh.store.read_events("p-1"), durable_events)
        self.assertEqual(fresh.domain_event_count("p-1"), before + 1)
        self.assertEqual(recovery.reconcile_pending("p-1"), [])
        self.assertEqual(recovery.runtime_invocation_count, 0)

    def test_pending_uses_one_read_snapshot_during_a_concurrent_commit(self):
        self.harness.store._ensure_open().execute("PRAGMA journal_mode = WAL")
        self.pending("earlier")
        recovery = self.recover()
        real_read_events = SQLiteStore.read_events
        interleaved = []

        def interleave(store, *args, **kwargs):
            events = real_read_events(store, *args, **kwargs)
            if store is not self.harness.store and not interleaved:
                interleaved.append(True)
                self.pending("concurrent")  # A different connection commits after the first SELECT.
            return events

        with patch.object(SQLiteStore, "read_events", interleave):
            try:
                pending = recovery.reconcile_pending("p-1")
            except ModelValidationError as exc:
                self.fail(f"valid concurrent commit produced a mixed recovery snapshot: {exc}")
            self.assertEqual(pending, ["earlier"])
        self.assertEqual(interleaved, [True])
        self.assertEqual(recovery.reconcile_pending("p-1"), ["earlier", "concurrent"])

    def test_orphaned_receipt_or_mismatched_command_digest_fails_closed(self):
        command = self.pending("broken-receipt")
        connection = self.harness.store._ensure_open()
        connection.execute("UPDATE commands SET request_digest = ? WHERE id = ?", ("0" * 64, command.id))
        with self.assertRaisesRegex(ModelValidationError, "digest"):
            self.recover().reconcile_pending("p-1")
        connection.execute("UPDATE commands SET request_digest = ? WHERE id = ?", (command.digest(), command.id))
        connection.execute("DELETE FROM idempotency WHERE command_id = ?", (command.id,))
        connection.execute("DELETE FROM commands WHERE id = ?", (command.id,))
        with self.assertRaisesRegex(ModelValidationError, "Command|command"):
            self.recover().reconcile_pending("p-1")

    def test_receipt_identity_type_digest_correlation_and_target_are_verified(self):
        command = self.pending("validated-receipt")
        connection = self.harness.store._ensure_open()
        original = connection.execute("SELECT payload_json FROM events WHERE causation_id = ?", (command.id,)).fetchone()[0]
        for field, value in (("command_type", "task.claim"), ("request_digest", "0" * 64)):
            payload = json.loads(original)
            payload[field] = value
            connection.execute("UPDATE events SET payload_json = ? WHERE causation_id = ?", (json.dumps(payload), command.id))
            with self.subTest(field=field), self.assertRaises(ModelValidationError):
                self.recover().reconcile_pending("p-1")
            connection.execute("UPDATE events SET payload_json = ? WHERE causation_id = ?", (original, command.id))
        for column, value, restore in (
            ("correlation_id", "foreign", command.correlation_id),
            ("aggregate_id", "foreign", command.target_id),
        ):
            connection.execute(f"UPDATE events SET {column} = ? WHERE causation_id = ?", (value, command.id))
            with self.subTest(field=column), self.assertRaises(ModelValidationError):
                self.recover().reconcile_pending("p-1")
            connection.execute(f"UPDATE events SET {column} = ? WHERE causation_id = ?", (restore, command.id))

    def test_successful_terminal_must_match_the_command_not_just_causation(self):
        self.harness.run_demo_flow("p-1")
        command = self.pending("cannot-be-cleared-by-unrelated-event")
        # The domain reducer can replay this well-formed Task claim/release. Its
        # attribution to a different Command is corrupt and must NOT clear pending.
        connection = self.harness.store._ensure_open()
        connection.execute("UPDATE events SET causation_id = ? WHERE type = 'task.claimed'", (command.id,))
        recovery = self.recover()
        self.assertTrue(recovery.rebuild_project("p-1"))
        with self.assertRaises(ModelValidationError):
            recovery.reconcile_pending("p-1")

    def test_unsupported_command_rejection_is_terminal_without_simulation(self):
        command = make_command(
            command_id="unsupported", actor_id="a-1", command_type="project.pause",
            target_id=None, payload={}, expected_revision=0, idempotency_key="unsupported",
        )
        self.assertEqual(self.harness.handle(command).error_code, "UNSUPPORTED_COMMAND")
        recovery = self.recover()
        self.assertEqual(recovery.reconcile_pending("p-1"), [])
        self.assertEqual(recovery.runtime_invocation_count, 0)

    def test_harness_reopen_never_reseeds_or_runs_simulation(self):
        events = self.harness.store.read_events("p-1")
        self.harness.close()
        fresh = RuntimeHarness.open(self.db_path)
        self.addCleanup(fresh.close)
        self.assertEqual(fresh.store.read_events("p-1"), events)
        self.assertEqual(fresh.runtime.invocation_count, 0)
        fresh.close()
        fresh.close()


class PendingProjectionTests(unittest.TestCase):
    def test_pending_projection_is_pure_ordered_idempotent_and_rejects_gaps(self):
        self.assertTrue(callable(getattr(Projection, "pending_command_ids", None)),
                        "M0-05 pure pending Command projection is not implemented")
        command = make_task_create_command(command_id="cmd-1")
        command2 = replace(command, id="cmd-2", idempotency_key="key2", target_id="t-2")
        received = Event(
            "received", "p-1", 1, "command.received", "task", "t-1", 0,
            command.id, command.correlation_id,
            {"command_type": command.type, "request_digest": command.digest()},
        )
        received2 = replace(
            received, id="received2", sequence=2, causation_id=command2.id,
            aggregate_id=command2.target_id,
            payload={"command_type": command2.type, "request_digest": command2.digest()},
        )
        rejected = replace(received, id="rejected", sequence=3, type="command.rejected", payload={"error": {"code": "TEST_REJECTION"}})
        commands = [command, command2]
        self.assertEqual(Projection.pending_command_ids([rejected, received2, received, received], commands), ["cmd-2"])
        self.assertEqual(Projection.pending_command_ids(iter(()), []), [])
        with self.assertRaisesRegex(ModelValidationError, "sequence"):
            Projection.pending_command_ids([received, rejected], commands)
        with self.assertRaises(TypeError):
            Projection.pending_command_ids([{}], commands)
        with self.assertRaises(TypeError):
            Projection.pending_command_ids([received], [{}])



    def test_wrong_terminal_type_for_the_same_target_cannot_clear_pending(self):
        self.assertTrue(callable(getattr(Projection, "pending_command_ids", None)))
        create = make_task_create_command()
        claim = replace(create, id="claim", type="task.claim", payload={}, idempotency_key="claim")
        claim_again = replace(claim, id="claim-again", expected_revision=1, idempotency_key="claim-again")

        def receipt(command, sequence, revision):
            return Event(
                f"{command.id}:received", "p-1", sequence, "command.received", "task", "t-1", revision,
                command.id, command.correlation_id,
                {"command_type": command.type, "request_digest": command.digest()},
            )

        first = receipt(create, 1, 0)
        second = receipt(claim, 3, 0)
        third = receipt(claim_again, 5, 1)
        events = [
            first, replace(first, id="created", sequence=2, type="task.created", payload={"title": "Task", "status": "pending"}),
            second, replace(second, id="claimed", sequence=4, type="task.claimed", aggregate_revision=1, payload={"actor_id": "a-1", "status": "assigned"}),
            third, replace(third, id="requeued", sequence=6, type="task.requeued", aggregate_revision=2, payload={"actor_id": "a-1", "status": "pending", "reason": "release"}),
        ]
        self.assertEqual(Projection.rebuild(events)["task:t-1"]["status"], "pending")
        with self.assertRaisesRegex(ModelValidationError, "terminal Event type"):
            Projection.pending_command_ids(events, [create, claim, claim_again])

    def test_duplicate_command_boolean_and_integer_payloads_conflict(self):
        first = replace(make_task_create_command(), payload={"extra": True})
        second = replace(first, payload={"extra": 1})
        self.assertNotEqual(first.digest(), second.digest())
        receipt = Event(
            "typed-received", "p-1", 1, "command.received", "task", "t-1", 0,
            second.id, second.correlation_id,
            {"command_type": second.type, "request_digest": second.digest()},
        )
        # The receipt matches the last Command, so only duplicate identity
        # validation can prevent silently discarding the conflicting first one.
        with self.assertRaisesRegex(ModelValidationError, "conflicting duplicate Command identity"):
            Projection.pending_command_ids([receipt], [first, second])

    def test_duplicate_command_integer_and_float_payloads_conflict(self):
        first = replace(make_task_create_command(), payload={"extra": [1]})
        second = replace(first, payload={"extra": [1.0]})
        self.assertNotEqual(first.digest(), second.digest())
        receipt = Event(
            "typed-received", "p-1", 1, "command.received", "task", "t-1", 0,
            second.id, second.correlation_id,
            {"command_type": second.type, "request_digest": second.digest()},
        )
        with self.assertRaisesRegex(ModelValidationError, "conflicting duplicate Command identity"):
            Projection.pending_command_ids([receipt], [first, second])

    def test_duplicate_command_canonical_content_is_harmless(self):
        first = replace(
            make_task_create_command(command_id="typed-duplicate"),
            payload={"title": "Task", "extra": {"enabled": True, "attempts": [1, 1.0]}},
        )
        second = replace(first, payload={"extra": {"attempts": [1, 1.0], "enabled": True}, "title": "Task"})
        receipt = Event(
            "typed-received", "p-1", 1, "command.received", "task", "t-1", 0,
            second.id, second.correlation_id,
            {"command_type": second.type, "request_digest": second.digest()},
        )
        self.assertEqual(Projection.pending_command_ids([receipt], [first, second]), ["typed-duplicate"])

    def test_contradictory_or_unlinked_command_histories_fail_closed(self):
        self.assertTrue(callable(getattr(Projection, "pending_command_ids", None)))
        command = make_task_create_command()
        receipt = Event(
            "received", "p-1", 1, "command.received", "task", "t-1", 0,
            command.id, command.correlation_id,
            {"command_type": command.type, "request_digest": command.digest()},
        )
        rejected = replace(receipt, id="rejected", sequence=2, type="command.rejected", payload={"error": {"code": "TEST_REJECTION"}})
        cases = [
            ([], [command]),
            ([receipt], [command, replace(command, payload={"title": "different"})]),
            ([receipt], [command, replace(command, id="foreign", project_id="p-2")]),
            ([receipt, replace(receipt, id="second-receipt", sequence=2)], [command]),
            ([receipt, rejected, replace(rejected, id="second-terminal", sequence=3)], [command]),
            ([receipt, replace(rejected, payload={"error": {}})], [command]),
        ]
        for index, (events, commands) in enumerate(cases):
            with self.subTest(case=index), self.assertRaises(ModelValidationError):
                Projection.pending_command_ids(events, commands)


if __name__ == "__main__":
    unittest.main()
