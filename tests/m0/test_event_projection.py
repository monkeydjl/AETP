"""M0-03 sequencing, pure replay, and disposable Projection-cache contracts."""

from __future__ import annotations

import sqlite3
import unittest
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from unittest.mock import patch

from aetp.core.commands import CommandHandler
from aetp.domain.models import Event
from aetp.storage.sqlite_store import SQLiteStore
from tests.m0.support import (
    clear_projection_fixture,
    install_event_failure_fixture,
    install_projection_failure_fixture,
    make_command,
    make_task_create_command,
    open_command_fixture,
)

try:
    from aetp.core.projection import Projection
except ModuleNotFoundError as exc:
    if exc.name != "aetp.core.projection":
        raise
    Projection = None


CREATED_TASK = {
    "id": "t-1", "project_id": "p-1", "revision": 0,
    "title": "Demo task", "status": "pending", "owner_id": None,
}
SEED_STATE = {
    "project:p-1": {"id": "p-1", "project_id": "p-1", "revision": 0, "status": "planning"},
    "agent:a-1": {"id": "a-1", "project_id": "p-1", "revision": 0, "model_id": "model-1", "status": "available"},
    "agent:a-2": {"id": "a-2", "project_id": "p-1", "revision": 0, "model_id": "model-2", "status": "available"},
}


def created_event():
    return Event(
        "z-created", "p-1", 1, "task.created", "task", "t-1", 0,
        "create", "task-chain", {"title": "Demo task", "status": "pending"},
    )


def claimed_event():
    return replace(
        created_event(), id="a-claimed", sequence=2, type="task.claimed",
        aggregate_revision=1, causation_id="claim",
        payload={"actor_id": "a-1", "status": "assigned"},
    )


def requeued_event():
    return replace(
        claimed_event(), id="m-requeued", sequence=3, type="task.requeued",
        aggregate_revision=2, causation_id="release",
        payload={"actor_id": "a-1", "reason": "release", "status": "pending"},
    )


@contextmanager
def deny_sql_writes(connection):
    """A real SQLite authorizer, not a replacement for persistence behavior."""
    forbidden = {
        sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
        sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE,
        sqlite3.SQLITE_TRANSACTION, sqlite3.SQLITE_SAVEPOINT,
    }
    connection.set_authorizer(
        lambda action, *_: sqlite3.SQLITE_DENY if action in forbidden else sqlite3.SQLITE_OK
    )
    try:
        yield
    finally:
        connection.set_authorizer(None)


class ProjectionReducerTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(Projection, "M0-03 Projection is not implemented")
        self.projection = Projection()

    def test_incremental_claim_and_release_preserve_metadata_and_revision(self):
        self.projection.apply(created_event())
        self.assertEqual(self.projection.state, {"task:t-1": CREATED_TASK})
        self.projection.apply(claimed_event())
        self.assertEqual(self.projection.state, {"task:t-1": {
            **CREATED_TASK, "revision": 1, "status": "assigned", "owner_id": "a-1",
        }})
        self.projection.apply(requeued_event())
        self.assertEqual(self.projection.state, {"task:t-1": {**CREATED_TASK, "revision": 2}})
        self.assertEqual(self.projection.last_sequence, 3)

    def test_rebuild_orders_a_generator_by_sequence_not_id_or_payload_timestamp(self):
        events = [created_event(), claimed_event(), requeued_event()]
        events = [replace(event, payload={**event.payload, "timestamp": 100 - event.sequence}) for event in events]
        rebuilt = Projection.rebuild(event for event in reversed(events))
        self.assertEqual(rebuilt, {"task:t-1": {**CREATED_TASK, "revision": 2}})
        self.assertEqual(Projection.rebuild([]), {})

    def test_exact_redelivery_has_no_second_effect_even_after_newer_events(self):
        for event in [created_event(), claimed_event(), created_event(), claimed_event(), requeued_event()]:
            self.projection.apply(event)
        self.assertEqual(self.projection.state, {"task:t-1": {**CREATED_TASK, "revision": 2}})
        self.assertEqual(self.projection.last_sequence, 3)
        self.assertEqual(Projection.rebuild([created_event(), created_event()]), {"task:t-1": CREATED_TASK})

    def test_conflicting_event_identity_is_rejected_without_mutation(self):
        self.projection.apply(created_event())
        with self.assertRaises(ValueError):
            self.projection.apply(replace(created_event(), payload={"title": "changed"}))
        self.assertEqual(self.projection.state, {"task:t-1": CREATED_TASK})
        self.assertEqual(self.projection.last_sequence, 1)
        self.projection.apply(claimed_event())
        self.assertEqual(self.projection.state["task:t-1"]["revision"], 1)

    def test_duplicate_sequence_for_a_different_event_is_rejected(self):
        self.projection.apply(created_event())
        with self.assertRaises(ValueError):
            self.projection.apply(replace(created_event(), id="other-event", aggregate_id="t-other"))
        self.assertEqual(self.projection.state, {"task:t-1": CREATED_TASK})
        self.assertEqual(self.projection.last_sequence, 1)

    def test_missing_sequence_is_not_silently_skipped(self):
        self.projection.apply(created_event())
        with self.assertRaises(ValueError):
            self.projection.apply(replace(claimed_event(), sequence=3))
        self.assertEqual(self.projection.last_sequence, 1)
        self.assertEqual(self.projection.state, {"task:t-1": CREATED_TASK})
        self.projection.apply(claimed_event())
        self.assertEqual(self.projection.last_sequence, 2)

    def test_unassigned_sequence_is_not_a_replayable_fact(self):
        with self.assertRaises(ValueError):
            self.projection.apply(replace(created_event(), sequence=0))
        self.assertEqual(self.projection.state, {})
        self.assertEqual(self.projection.last_sequence, 0)

    def test_aggregate_revision_gap_is_rejected_without_consuming_sequence(self):
        self.projection.apply(created_event())
        with self.assertRaises(ValueError):
            self.projection.apply(replace(claimed_event(), aggregate_revision=2))
        self.assertEqual(self.projection.state, {"task:t-1": CREATED_TASK})
        self.assertEqual(self.projection.last_sequence, 1)
        self.projection.apply(claimed_event())
        self.assertEqual(self.projection.state["task:t-1"]["revision"], 1)

    def test_nonzero_creation_revision_is_rejected(self):
        with self.assertRaises(ValueError):
            self.projection.apply(replace(created_event(), aggregate_revision=1))
        self.assertEqual(self.projection.state, {})

    def test_missing_aggregate_does_not_bind_or_partially_change_projection(self):
        with self.assertRaises(ValueError):
            self.projection.apply(replace(claimed_event(), sequence=1))
        self.assertEqual(self.projection.state, {})
        self.assertEqual(self.projection.last_sequence, 0)
        self.projection.apply(replace(created_event(), project_id="p-other"))
        self.assertEqual(self.projection.state["task:t-1"]["project_id"], "p-other")

    def test_second_creation_cannot_overwrite_existing_aggregate(self):
        self.projection.apply(created_event())
        with self.assertRaises(ValueError):
            self.projection.apply(replace(created_event(), id="create-again", sequence=2))
        self.assertEqual(self.projection.state, {"task:t-1": CREATED_TASK})

    def test_command_audits_do_not_create_aggregates_or_advance_domain_revision(self):
        self.projection.apply(replace(created_event(), type="command.received", aggregate_revision=99))
        self.projection.apply(replace(created_event(), id="rejected", sequence=2, type="command.rejected", aggregate_revision=99))
        self.assertEqual(self.projection.state, {})
        self.projection.apply(replace(created_event(), id="effect", sequence=3))
        self.projection.apply(replace(created_event(), id="later-audit", sequence=4, type="command.rejected", aggregate_revision=99))
        self.assertEqual(self.projection.state, {"task:t-1": CREATED_TASK})
        self.assertEqual(self.projection.last_sequence, 4)

    def test_domain_event_type_must_match_aggregate_address(self):
        with self.assertRaises(ValueError):
            self.projection.apply(replace(created_event(), aggregate_type="agent"))
        with self.assertRaises(ValueError):
            self.projection.apply(replace(created_event(), type="project.created", aggregate_type="project", aggregate_id="wrong-project"))
        self.assertEqual(self.projection.state, {})

    def test_other_project_cannot_enter_the_same_projection(self):
        self.projection.apply(created_event())
        with self.assertRaises(ValueError):
            self.projection.apply(replace(claimed_event(), project_id="p-other"))
        self.assertEqual(self.projection.state, {"task:t-1": CREATED_TASK})
        self.assertEqual(self.projection.last_sequence, 1)

    def test_future_event_types_cannot_implicitly_complete_a_task(self):
        self.projection.apply(created_event())
        for kind in ["task.completed", "task.started", "project.paused", "agent.left"]:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.projection.apply(replace(claimed_event(), type=kind))
        self.assertEqual(self.projection.state, {"task:t-1": CREATED_TASK})
        self.assertEqual(self.projection.last_sequence, 1)

    def test_typed_keys_separate_same_named_entities(self):
        events = [
            replace(created_event(), id="project", project_id="shared", type="project.created", aggregate_type="project", aggregate_id="shared", payload={"status": "planning"}),
            replace(created_event(), id="agent", project_id="shared", sequence=2, type="agent.created", aggregate_type="agent", aggregate_id="shared", payload={"model_id": "demo", "status": "available"}),
            replace(created_event(), id="task", project_id="shared", sequence=3, aggregate_id="shared"),
        ]
        state = Projection.rebuild(events)
        self.assertEqual(set(state), {"project:shared", "agent:shared", "task:shared"})
        self.assertEqual(state["agent:shared"]["model_id"], "demo")
        self.assertEqual(state["task:shared"]["title"], "Demo task")

    def test_payload_cannot_override_identity_revision_or_claim_ownership(self):
        self.projection.apply(replace(created_event(), payload={
            **created_event().payload, "id": "forged", "revision": 42, "owner_id": "a-rogue",
        }))
        self.assertEqual(self.projection.state, {"task:t-1": CREATED_TASK})
        returned = self.projection.state
        returned["task:t-1"]["title"] = "changed by reader"
        returned.clear()
        self.assertEqual(self.projection.state, {"task:t-1": CREATED_TASK})

    def test_malformed_claim_and_unqualified_created_completion_fail_closed(self):
        self.projection.apply(created_event())
        for payload in [{}, {"actor_id": " "}, {"actor_id": "a-1", "status": "completed"}]:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.projection.apply(replace(claimed_event(), payload=payload))
        self.assertEqual(self.projection.state, {"task:t-1": CREATED_TASK})
        other = Projection()
        with self.assertRaises(ValueError):
            other.apply(replace(created_event(), payload={"title": "fake", "status": "completed"}))
        self.assertEqual(other.state, {})

    def test_replay_computes_literal_state_with_external_effect_paths_denied(self):
        events = [created_event(), claimed_event(), requeued_event()]
        with ExitStack() as stack:
            for owner, name in [(CommandHandler, "handle"), (SQLiteStore, "open"), (SQLiteStore, "append_events"), (SQLiteStore, "read_events")]:
                stack.enter_context(patch.object(owner, name, side_effect=AssertionError("replay attempted IO")))
            for name in ["sqlite3.connect", "subprocess.Popen", "os.system", "socket.socket"]:
                stack.enter_context(patch(name, side_effect=AssertionError("replay attempted external effect")))
            self.assertEqual(Projection.rebuild(events), {"task:t-1": {**CREATED_TASK, "revision": 2}})


class EventProjectionStoreTests(unittest.TestCase):
    def setUp(self):
        self.fixture = open_command_fixture(self)
        self.store = self.fixture.store

    def state(self, project_id="p-1"):
        read = getattr(self.store, "read_projection", None)
        self.assertTrue(callable(read), "M0-03 read_projection is not implemented")
        return read(project_id)

    def submit(self, command):
        return self.fixture.handler.handle(command, authenticated_actor_id=command.actor_id)

    def task_command(self, kind, revision, key):
        return make_command(
            command_id=key, actor_id="a-1", command_type=kind, target_id="t-1",
            payload={}, expected_revision=revision, idempotency_key=key,
        )

    def test_rebuild_from_events_equals_incremental_projection(self):
        self.assertEqual(self.submit(make_task_create_command()).status, "accepted")
        expected = {**SEED_STATE, "task:t-1": CREATED_TASK}
        self.assertEqual(self.state(), expected)
        events = self.store.read_events("p-1")
        clear_projection_fixture(self.store, project_id="p-1")
        self.assertEqual(self.store.read_events("p-1"), events)
        self.assertIsNotNone(self.store.read_idempotency(("p-1", "a-1", "k-1")))
        self.assertEqual(Projection.rebuild(events), expected)
        with deny_sql_writes(self.store._ensure_open()):
            self.assertEqual(self.state(), expected)

    def test_claim_release_and_rejection_audits_project_exact_current_state(self):
        self.assertEqual(self.submit(make_task_create_command()).status, "accepted")
        self.assertEqual(self.submit(self.task_command("task.claim", 0, "claim")).status, "accepted")
        self.assertEqual(self.state()["task:t-1"], {**CREATED_TASK, "revision": 1, "status": "assigned", "owner_id": "a-1"})
        stale = self.task_command("task.release", 0, "stale")
        self.assertEqual(self.submit(stale).error_code, "REVISION_CONFLICT")
        before_retry = self.store.read_events("p-1")
        self.assertEqual(self.submit(stale).error_code, "REVISION_CONFLICT")
        self.assertEqual(self.store.read_events("p-1"), before_retry)
        self.assertEqual(self.submit(self.task_command("task.release", 1, "release")).status, "accepted")
        self.assertEqual(self.state(), {**SEED_STATE, "task:t-1": {**CREATED_TASK, "revision": 2}})
        self.assertEqual([event.sequence for event in self.store.read_events("p-1")], list(range(1, 15)))

    def test_store_assigns_final_sequence_to_drafts_without_mutating_them(self):
        drafts = [replace(created_event(), sequence=0), replace(claimed_event(), sequence=0)]
        try:
            self.store.append_events(drafts)
        except ValueError as exc:
            self.fail(f"Sequencer must number valid internal drafts: {exc}")
        events = self.store.read_events("p-1", after_sequence=6)
        self.assertEqual(events, [replace(drafts[0], sequence=7), replace(drafts[1], sequence=8)])
        self.assertEqual([event.sequence for event in drafts], [0, 0])
        self.assertEqual(self.state()["task:t-1"]["revision"], 1)

    def test_positive_sequence_hint_cannot_skip_the_store_cursor(self):
        before = self.store.read_events("p-1")
        with self.assertRaises(ValueError):
            self.store.append_events([replace(created_event(), sequence=8)])
        self.assertEqual(self.store.read_events("p-1"), before)
        with self.store.transaction():
            self.assertEqual(self.store.next_sequence("p-1"), 7)

    def test_sequence_allocation_requires_an_active_transaction(self):
        with self.assertRaises(RuntimeError):
            self.store.next_sequence("p-1")
        with self.store.transaction():
            self.assertEqual(self.store.next_sequence("p-1"), 7)
            self.assertEqual(self.store.next_sequence("p-1"), 7)

    def test_numbering_and_cache_are_project_scoped(self):
        self.assertEqual(self.state(), SEED_STATE)
        self.store.append_events([replace(created_event(), project_id="p-2", sequence=0)])
        self.assertEqual([event.sequence for event in self.store.read_events("p-2")], [1])
        self.assertEqual(self.state("p-2"), {"task:t-1": {**CREATED_TASK, "project_id": "p-2"}})
        clear_projection_fixture(self.store, project_id="p-2")
        self.assertEqual(self.state(), SEED_STATE)
        with self.store.transaction():
            self.assertEqual(self.store.next_sequence("p-1"), 7)
            self.assertEqual(self.store.next_sequence("p-2"), 2)

    def test_fresh_connection_continues_durable_sequence_and_cache(self):
        self.assertEqual(self.state(), SEED_STATE)
        with SQLiteStore.open(self.fixture.db_path) as reopened:
            reopened.append_events([replace(created_event(), sequence=0)])
            self.assertEqual(reopened.read_events("p-1")[-1].sequence, 7)
            self.assertEqual(reopened.read_projection("p-1"), {**SEED_STATE, "task:t-1": CREATED_TASK})
        self.assertEqual(self.state(), {**SEED_STATE, "task:t-1": CREATED_TASK})

    def test_read_projection_is_detached_and_performs_no_sql_writes(self):
        self.assertEqual(self.state(), SEED_STATE)
        connection = self.store._ensure_open()
        before_changes = connection.total_changes
        with deny_sql_writes(connection):
            returned = self.state()
            returned["agent:a-1"]["model_id"] = "reader modification"
            self.assertEqual(self.state(), SEED_STATE)
            self.assertEqual(self.state("absent-project"), {})
        self.assertEqual(connection.total_changes, before_changes)

    def test_deleted_cache_is_rebuilt_from_facts_before_the_next_append(self):
        self.assertEqual(self.submit(make_task_create_command()).status, "accepted")
        self.assertEqual(self.state(), {**SEED_STATE, "task:t-1": CREATED_TASK})
        clear_projection_fixture(self.store, project_id="p-1")
        result = self.submit(self.task_command("task.claim", 0, "claim"))
        self.assertEqual(result.status, "accepted")
        self.assertEqual(self.state(), {**SEED_STATE, "task:t-1": {**CREATED_TASK, "revision": 1, "status": "assigned", "owner_id": "a-1"}})

    def test_corrupt_or_lagging_cache_cannot_authorize_or_change_commands(self):
        self.assertEqual(self.submit(make_task_create_command()).status, "accepted")
        self.assertEqual(self.state(), {**SEED_STATE, "task:t-1": CREATED_TASK})
        connection = self.store._ensure_open()
        connection.execute("UPDATE projections SET state_json = ? WHERE project_id = ?", ('{"task:t-1":{"revision":99}}', "p-1"))
        with deny_sql_writes(connection):
            self.assertEqual(self.state(), {**SEED_STATE, "task:t-1": CREATED_TASK})
        result = self.submit(self.task_command("task.claim", 0, "claim"))
        self.assertEqual(result.status, "accepted")
        connection.execute("UPDATE projection_meta SET last_sequence = 1 WHERE project_id = ?", ("p-1",))
        self.assertEqual(self.state()["task:t-1"]["revision"], 1)
        self.assertEqual(self.submit(self.task_command("task.release", 1, "release")).status, "accepted")
        self.assertEqual(self.state()["task:t-1"], {**CREATED_TASK, "revision": 2})

    def test_caught_duplicate_id_batch_leaves_no_partial_events_or_projection(self):
        before = self.store.read_events("p-1")
        with self.store.transaction():
            with self.assertRaises(ValueError):
                self.store.append_events([
                    replace(created_event(), sequence=7),
                    replace(created_event(), id=before[0].id, sequence=8, aggregate_id="other"),
                ])
            self.assertEqual(self.store.read_events("p-1"), before)
            self.assertEqual(self.state(), SEED_STATE)
            self.assertEqual(self.store.next_sequence("p-1"), 7)
            self.assertEqual(self.submit(make_task_create_command()).status, "accepted")
        self.assertEqual(self.state(), {**SEED_STATE, "task:t-1": CREATED_TASK})

    def test_caught_revision_gap_rolls_back_the_whole_append_batch(self):
        self.assertEqual(self.state(), SEED_STATE)
        before = self.store.read_events("p-1")
        with self.store.transaction():
            with self.assertRaises(ValueError):
                self.store.append_events([
                    replace(created_event(), sequence=7),
                    replace(claimed_event(), sequence=8, aggregate_revision=2),
                ])
            self.assertEqual(self.store.read_events("p-1"), before)
            self.assertEqual(self.state(), SEED_STATE)
            self.assertEqual(self.store.next_sequence("p-1"), 7)

    def test_event_insert_failure_keeps_cache_and_facts_at_the_same_boundary(self):
        self.assertEqual(self.state(), SEED_STATE)
        before = self.store.read_events("p-1")
        remove = install_event_failure_fixture(self, self.store)
        with self.assertRaises(ValueError):
            self.submit(make_task_create_command())
        self.assertEqual(self.store.read_events("p-1"), before)
        self.assertEqual(self.state(), SEED_STATE)
        self.assertIsNone(self.store.read_idempotency(("p-1", "a-1", "k-1")))
        remove()
        self.assertEqual(self.submit(make_task_create_command()).status, "accepted")
        self.assertEqual(self.store.read_events("p-1")[-1].sequence, 8)

    def test_projection_write_failure_rolls_back_command_event_and_result_batch(self):
        self.assertEqual(self.state(), SEED_STATE)
        before = self.store.read_events("p-1")
        remove = install_projection_failure_fixture(self, self.store)
        with self.assertRaises(ValueError):
            self.submit(make_task_create_command())
        self.assertEqual(self.store.read_events("p-1"), before)
        self.assertEqual(self.state(), SEED_STATE)
        self.assertIsNone(self.store.read_idempotency(("p-1", "a-1", "k-1")))
        remove()
        self.assertEqual(self.submit(make_task_create_command()).status, "accepted")
        self.assertEqual(self.state(), {**SEED_STATE, "task:t-1": CREATED_TASK})
        self.assertEqual(self.store.read_events("p-1")[-1].sequence, 8)

    def test_outer_rollback_discards_projection_updates_and_reuses_sequence(self):
        self.assertEqual(self.state(), SEED_STATE)
        with self.assertRaisesRegex(RuntimeError, "abort outer"):
            with self.store.transaction():
                self.assertEqual(self.submit(make_task_create_command()).status, "accepted")
                self.assertIn("task:t-1", self.state())
                raise RuntimeError("abort outer")
        self.assertEqual(self.state(), SEED_STATE)
        self.assertEqual(self.store.read_events("p-1")[-1].sequence, 6)
        self.assertEqual(self.submit(make_task_create_command()).status, "accepted")
        self.assertEqual(self.store.read_events("p-1")[-1].sequence, 8)

    def test_event_insert_precedes_any_persisted_projection_change(self):
        self.assertEqual(self.state(), SEED_STATE)
        statements = []
        connection = self.store._ensure_open()
        connection.set_trace_callback(statements.append)
        try:
            self.assertEqual(self.submit(make_task_create_command()).status, "accepted")
        finally:
            connection.set_trace_callback(None)
        normalized = [" ".join(sql.lower().split()) for sql in statements]
        event_indexes = [i for i, sql in enumerate(normalized) if sql.startswith("insert into events")]
        cache_indexes = [i for i, sql in enumerate(normalized) if sql.startswith(("insert into projections", "update projections", "insert into projection_meta", "update projection_meta"))]
        self.assertEqual(len(event_indexes), 2)
        self.assertTrue(cache_indexes, "successful append must persist its derived cache")
        self.assertLess(max(event_indexes), min(cache_indexes))
        self.assertEqual(self.state(), {**SEED_STATE, "task:t-1": CREATED_TASK})


if __name__ == "__main__":
    unittest.main()
