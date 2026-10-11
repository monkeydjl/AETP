"""M0-04: durable retry semantics and real shared-file process competition.

The pre-existing Handler scenarios are regression coverage, not invented RED.
New API/fixture assertions and a foreign durable result identity expose gaps.
Only test utilities inject faults; all Commands and races use real SQLite.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.util
import json
import multiprocessing
import os
import sqlite3
import unittest
from dataclasses import replace
from pathlib import Path

from aetp.core.commands import CommandHandler, CommandResult
from aetp.core.projection import Projection
from aetp.domain.models import Command
from aetp.storage.sqlite_store import SQLiteStore
from tests.m0 import support
from tests.m0.support import (
    clear_projection_fixture,
    install_event_failure_fixture,
    install_result_failure_fixture,
    make_command,
    make_task_create_command,
    open_command_fixture,
)


def require_idempotency(testcase):
    testcase.assertIsNotNone(
        importlib.util.find_spec("aetp.core.idempotency"),
        "M0-04 idempotency API is not implemented yet",
    )
    # Do not mask import errors within the implementation.
    return importlib.import_module("aetp.core.idempotency")


def durable_rows(store):
    """Snapshot real authoritative rows, excluding disposable caches/audits."""
    connection = store._ensure_open()
    return {
        table: connection.execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3").fetchall()
        for table in ("commands", "events", "idempotency")
    }


def claim_command(*, actor_id="a-1", key="claim-1", revision=0):
    return make_command(
        command_id=f"cmd-{key}", actor_id=actor_id, command_type="task.claim",
        target_id="t-1", payload={}, expected_revision=revision,
        idempotency_key=key,
    )


class CanonicalDigestTests(unittest.TestCase):
    def test_digest_matches_hand_written_canonical_immutable_command(self):
        api = require_idempotency(self)
        # Literal protocol data, not Command.to_json() as its own oracle.
        canonical = (
            '{"actor_id":"a-1","correlation_id":"corr-k-1",'
            '"expected_revision":0,"id":"cmd-k-1","idempotency_key":"k-1",'
            '"payload":{"title":"Demo task"},"project_id":"p-1",'
            '"target_id":"t-1","type":"task.create"}'
        )
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        command = make_task_create_command()
        self.assertEqual(api.canonical_digest(command), expected)
        self.assertEqual(command.digest(), expected)  # existing on-disk format

    def test_nested_key_order_is_normalized_but_unicode_is_preserved(self):
        api = require_idempotency(self)
        # Explicit escapes preserve the real Unicode fixture across shell encodings.
        first = replace(make_task_create_command(), payload={
            "z": [1, {"b": 2, "a": 1}], "title": "\u4efb\u52a1", "a": True,
        })
        second = replace(first, payload={
            "a": True, "title": "\u4efb\u52a1", "z": [1, {"a": 1, "b": 2}],
        })
        canonical = (
            '{"actor_id":"a-1","correlation_id":"corr-k-1",'
            '"expected_revision":0,"id":"cmd-k-1","idempotency_key":"k-1",'
            '"payload":{"a":true,"title":"\u4efb\u52a1","z":[1,{"a":1,"b":2}]},'
            '"project_id":"p-1","target_id":"t-1","type":"task.create"}'
        )
        expected = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        escaped_canonical = canonical.replace("\u4efb\u52a1", "\\u4efb\\u52a1")
        escaped_digest = hashlib.sha256(escaped_canonical.encode("utf-8")).hexdigest()
        self.assertFalse(first.payload["title"].isascii())
        self.assertNotEqual(expected, escaped_digest)
        self.assertEqual(api.canonical_digest(first), expected)
        self.assertEqual(api.canonical_digest(second), expected)

    def test_every_immutable_command_field_binds_the_digest(self):
        api = require_idempotency(self)
        original = make_task_create_command()
        changes = {
            "id": "new-command", "project_id": "p-2", "actor_id": "a-2",
            "type": "task.claim", "target_id": "t-2", "payload": {"title": "New"},
            "expected_revision": 1, "idempotency_key": "new-key",
            "correlation_id": "new-context",
        }
        original_digest = api.canonical_digest(original)
        for field, value in changes.items():
            with self.subTest(field=field):
                self.assertNotEqual(
                    api.canonical_digest(replace(original, **{field: value})),
                    original_digest,
                )

    def test_unvalidated_non_command_input_cannot_be_digested(self):
        api = require_idempotency(self)
        for invalid in (None, {}, make_task_create_command().to_dict(), "command"):
            with self.subTest(value=invalid), self.assertRaises(TypeError):
                api.canonical_digest(invalid)


class IdempotencyLookupTests(unittest.TestCase):
    def setUp(self):
        self.fixture = open_command_fixture(self)

    def lookup_api(self):
        api = require_idempotency(self)
        return api, api.IdempotencyResult(self.fixture.store)

    def test_missing_scope_does_not_reserve_or_write_anything(self):
        api, lookup = self.lookup_api()
        command = make_task_create_command()
        connection = self.fixture.store._ensure_open()
        before = durable_rows(self.fixture.store)
        writes = connection.total_changes
        self.assertIsNone(lookup.lookup(("p-1", "a-1", "k-1"), api.canonical_digest(command)))
        self.assertEqual(connection.total_changes, writes)
        self.assertFalse(connection.in_transaction)
        self.assertEqual(durable_rows(self.fixture.store), before)

    def test_lookup_returns_detached_original_result_without_writes(self):
        api, lookup = self.lookup_api()
        command = make_task_create_command()
        result = self.fixture.handler.handle(command, authenticated_actor_id="a-1")
        connection = self.fixture.store._ensure_open()
        writes = connection.total_changes
        scope = ("p-1", "a-1", "k-1")
        returned = lookup.lookup(scope, api.canonical_digest(command))
        self.assertIsInstance(returned, CommandResult)
        self.assertEqual(returned, result)
        detached = returned.to_dict()
        detached["event_ids"].append("not-a-durable-event")
        self.assertEqual(lookup.lookup(scope, api.canonical_digest(command)), result)
        self.assertEqual(connection.total_changes, writes)

    def test_lookup_scope_includes_project_trusted_actor_and_key(self):
        api, lookup = self.lookup_api()
        command = make_task_create_command()
        self.fixture.handler.handle(command, authenticated_actor_id="a-1")
        for scope in (("p-2", "a-1", "k-1"), ("p-1", "a-2", "k-1"), ("p-1", "a-1", "k-2")):
            with self.subTest(scope=scope):
                self.assertIsNone(lookup.lookup(scope, api.canonical_digest(command)))

    def test_digest_conflict_cannot_overwrite_original_result(self):
        api, lookup = self.lookup_api()
        command = make_task_create_command()
        original = self.fixture.handler.handle(command, authenticated_actor_id="a-1")
        before = durable_rows(self.fixture.store)
        with self.assertRaises(api.IdempotencyConflict):
            lookup.lookup(("p-1", "a-1", "k-1"), api.canonical_digest(replace(command, payload={"title": "different"})))
        self.assertEqual(durable_rows(self.fixture.store), before)
        self.assertEqual(lookup.lookup(("p-1", "a-1", "k-1"), api.canonical_digest(command)), original)

    def test_lookup_rejects_invalid_digest_at_boundary(self):
        _, lookup = self.lookup_api()
        for invalid in (None, 5, b"a" * 64):
            with self.subTest(value=invalid), self.assertRaises(TypeError):
                lookup.lookup(("p-1", "a-1", "k-1"), invalid)
        for invalid in ("", "a" * 63, "a" * 65, "g" * 64, "A" * 64, " " + "a" * 63):
            with self.subTest(value=invalid), self.assertRaises(ValueError):
                lookup.lookup(("p-1", "a-1", "k-1"), invalid)

    def test_lookup_rejects_invalid_scope_instead_of_broadening_it(self):
        api, lookup = self.lookup_api()
        digest = api.canonical_digest(make_task_create_command())
        for scope in (None, ("p-1", "a-1"), ["p-1", "a-1", "k-1"], ("p-1", "", "k-1")):
            with self.subTest(scope=scope), self.assertRaises(ValueError):
                lookup.lookup(scope, digest)


class DurableIdempotencyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = open_command_fixture(self)

    def handle(self, command):
        return self.fixture.handler.handle(command, authenticated_actor_id=command.actor_id)

    def events(self):
        return self.fixture.store.read_events("p-1", after_sequence=self.fixture.after_sequence)

    def assert_replay_matches(self):
        events = self.fixture.store.read_events("p-1")
        self.assertEqual(self.fixture.store.read_projection("p-1"), Projection.rebuild(events))

    def test_exact_retry_returns_original_result_and_no_duplicate_batch(self):
        command = make_task_create_command(idempotency_key="same")
        first = self.handle(command)
        self.assertEqual(first.status, "accepted")
        self.assertEqual(first.aggregate_revision, 0)
        self.assertEqual([event.type for event in self.events()], ["command.received", "task.created"])
        before = durable_rows(self.fixture.store)
        self.assertEqual(self.handle(Command.from_dict(command.to_dict())), first)
        self.assertEqual(durable_rows(self.fixture.store), before)
        self.assertEqual({table: len(rows) for table, rows in before.items()}, {"commands": 4, "events": 8, "idempotency": 4})
        self.assert_replay_matches()

    def test_same_key_changed_content_or_identity_conflicts_without_writes(self):
        command = make_task_create_command(idempotency_key="same")
        first = self.handle(command)
        before = durable_rows(self.fixture.store)
        for field, value in {
            "id": "new-command", "payload": {"title": "different"},
            "expected_revision": 1, "target_id": "t-2", "type": "task.claim",
            "correlation_id": "other-context",
        }.items():
            with self.subTest(field=field):
                changed = replace(command, **{field: value})
                self.assertEqual(self.handle(changed), CommandResult(
                    "rejected", changed.id, (), None, "IDEMPOTENCY_CONFLICT",
                ))
                self.assertEqual(durable_rows(self.fixture.store), before)
        self.assertEqual(self.handle(command), first)

    def test_rejected_result_stays_original_even_when_precondition_later_changes(self):
        command = claim_command()
        rejected = self.handle(command)
        self.assertEqual((rejected.status, rejected.error_code, rejected.aggregate_revision), ("rejected", "INVALID_TARGET", None))
        self.assertEqual([event.type for event in self.events()], ["command.received", "command.rejected"])
        self.assertEqual(self.handle(make_task_create_command()).status, "accepted")
        before = durable_rows(self.fixture.store)
        self.assertEqual(self.handle(command), rejected)
        self.assertEqual(durable_rows(self.fixture.store), before)
        self.assertEqual(len(self.fixture.store.read_events("p-1")), 10)
        self.assertEqual(self.fixture.store.read_projection("p-1")["task:t-1"]["status"], "pending")
        self.assert_replay_matches()

    def test_project_actor_and_key_scopes_accept_distinct_intents(self):
        original = make_task_create_command(idempotency_key="shared")
        self.assertEqual(self.handle(original).status, "accepted")
        for command in (
            replace(original, id="other-actor", actor_id="a-2", target_id="t-2"),
            replace(original, id="other-key", idempotency_key="new-key", target_id="t-3"),
        ):
            self.assertEqual(self.handle(command).status, "accepted")
        for command in (
            make_command(command_id="seed-p2", actor_id="bootstrap", command_type="project.create", target_id=None,
                         payload={"status": "planning"}, expected_revision=0, idempotency_key="seed-p2", project_id="p-2"),
            make_command(command_id="seed-p2-a1", actor_id="bootstrap", command_type="agent.register", target_id="a-1",
                         payload={"model_id": "model-1"}, expected_revision=0, idempotency_key="seed-p2-a1", project_id="p-2"),
            replace(original, id="other-project", project_id="p-2"),
        ):
            self.assertEqual(self.handle(command).status, "accepted")
        for scope, command_id in (
            (("p-1", "a-1", "shared"), original.id),
            (("p-1", "a-2", "shared"), "other-actor"),
            (("p-1", "a-1", "new-key"), "other-key"),
            (("p-2", "a-1", "shared"), "other-project"),
        ):
            record = self.fixture.store.read_idempotency(scope)
            self.assertEqual(record["command_id"], command_id)
            self.assertEqual(record["result"]["status"], "accepted")
        self.assertEqual(len(self.fixture.store.read_events("p-1")), 12)
        self.assertEqual(len(self.fixture.store.read_events("p-2")), 6)

    def test_actor_mismatch_precedes_lookup_and_only_enters_security_audit(self):
        first = make_task_create_command(idempotency_key="shared")
        second = replace(first, id="actor-two", actor_id="a-2", target_id="t-2")
        self.handle(first)
        self.handle(second)
        before = durable_rows(self.fixture.store)
        result = self.fixture.handler.handle(first, authenticated_actor_id="a-2")
        self.assertEqual(result, CommandResult("rejected", first.id, (), None, "ACTOR_MISMATCH"))
        self.assertEqual(durable_rows(self.fixture.store), before)
        self.assertEqual([row["error_code"] for row in self.fixture.store.read_security_audit(authenticated_actor_id="a-2")], ["ACTOR_MISMATCH"])

    def test_reopen_and_deleted_cache_do_not_lose_original_result(self):
        command = make_task_create_command()
        original = self.handle(command)
        expected_state = self.fixture.store.read_projection("p-1")
        clear_projection_fixture(self.fixture.store, project_id="p-1")
        before = durable_rows(self.fixture.store)
        self.fixture.store.close()
        reopened = SQLiteStore.open(self.fixture.db_path)
        self.addCleanup(reopened.close)
        connection = reopened._ensure_open()
        writes = connection.total_changes
        self.assertEqual(CommandHandler(reopened).handle(command, authenticated_actor_id="a-1"), original)
        self.assertEqual(reopened.read_projection("p-1"), expected_state)
        self.assertEqual(durable_rows(reopened), before)
        self.assertEqual(connection.total_changes, writes)
        self.assertEqual(connection.execute("SELECT COUNT(*) FROM projections").fetchone()[0], 0)

    def test_missing_durable_result_fails_closed_without_resubmission(self):
        command = make_task_create_command()
        self.handle(command)
        connection = self.fixture.store._ensure_open()
        connection.execute("UPDATE idempotency SET result_json = NULL WHERE command_id = ?", (command.id,))
        before = durable_rows(self.fixture.store)
        with self.assertRaises(RuntimeError):
            self.handle(command)
        self.assertEqual(durable_rows(self.fixture.store), before)
        self.assertFalse(connection.in_transaction)

    def test_foreign_durable_result_identity_fails_closed(self):
        command = make_task_create_command()
        self.handle(command)
        foreign = self.handle(make_task_create_command(idempotency_key="foreign"))
        self.assertEqual(foreign.error_code, "REVISION_CONFLICT")
        connection = self.fixture.store._ensure_open()
        connection.execute("UPDATE idempotency SET result_json = ? WHERE command_id = ?", (json.dumps(foreign.to_dict()), command.id))
        before = durable_rows(self.fixture.store)
        with self.assertRaises(RuntimeError):
            self.handle(command)
        self.assertEqual(durable_rows(self.fixture.store), before)
        self.assertFalse(connection.in_transaction)

    def test_malformed_durable_result_is_not_treated_as_an_absent_key(self):
        command = make_task_create_command()
        self.handle(command)
        connection = self.fixture.store._ensure_open()
        for corrupt in ('{"status":"accepted"}', '{"broken":', '[]'):
            with self.subTest(corrupt=corrupt):
                connection.execute("UPDATE idempotency SET result_json = ? WHERE command_id = ?", (corrupt, command.id))
                before = durable_rows(self.fixture.store)
                with self.assertRaises((ValueError, TypeError, RuntimeError)):
                    self.handle(command)
                self.assertEqual(durable_rows(self.fixture.store), before)
                self.assertFalse(connection.in_transaction)

    def test_release_then_new_key_reclaim_does_not_reexecute_old_intents(self):
        self.handle(make_task_create_command())
        claim = claim_command()
        claimed = self.handle(claim)
        self.assertEqual((claimed.status, claimed.aggregate_revision), ("accepted", 1))
        release = make_command(command_id="cmd-release", actor_id="a-1", command_type="task.release", target_id="t-1",
                               payload={}, expected_revision=1, idempotency_key="release")
        released = self.handle(release)
        self.assertEqual((released.status, released.aggregate_revision), ("accepted", 2))
        before = durable_rows(self.fixture.store)
        self.assertEqual(self.handle(claim), claimed)
        self.assertEqual(durable_rows(self.fixture.store), before)
        state = self.fixture.store.read_projection("p-1")["task:t-1"]
        self.assertEqual((state["status"], state["owner_id"], state["revision"]), ("pending", None, 2))
        changed_old_key = replace(claim, expected_revision=2)
        self.assertEqual(self.handle(changed_old_key).error_code, "IDEMPOTENCY_CONFLICT")
        self.assertEqual(durable_rows(self.fixture.store), before)
        new_claim = claim_command(actor_id="a-2", key="new-intent", revision=2)
        reclaimed = self.handle(new_claim)
        self.assertEqual((reclaimed.status, reclaimed.aggregate_revision), ("accepted", 3))
        before = durable_rows(self.fixture.store)
        self.assertEqual(self.handle(release), released)
        self.assertEqual(durable_rows(self.fixture.store), before)
        state = self.fixture.store.read_projection("p-1")["task:t-1"]
        self.assertEqual((state["status"], state["owner_id"], state["revision"]), ("assigned", "a-2", 3))
        self.assertEqual([event.aggregate_revision for event in self.events() if event.type.startswith("task.")], [0, 1, 2, 3])
        self.assertEqual(len(self.fixture.store.read_events("p-1")), 14)
        self.assert_replay_matches()

    def assert_fault_rolls_back_then_allows_retry(self, fault):
        self.handle(make_task_create_command())
        command = claim_command(key=f"fault-{fault}")
        before = durable_rows(self.fixture.store)
        if fault == "event":
            remove = install_event_failure_fixture(self, self.fixture.store, "task.claimed")
            error_type = ValueError  # Event batch boundary wraps the SQLite error.
        else:
            remove = install_result_failure_fixture(self, self.fixture.store)
            error_type = sqlite3.IntegrityError
        with self.assertRaises(error_type):
            self.handle(command)
        self.assertEqual(durable_rows(self.fixture.store), before)
        self.assertIsNone(self.fixture.store.read_idempotency(("p-1", "a-1", command.idempotency_key)))
        self.assertFalse(self.fixture.store._ensure_open().in_transaction)
        self.assert_replay_matches()
        remove()
        accepted = self.handle(command)
        self.assertEqual((accepted.status, accepted.aggregate_revision), ("accepted", 1))
        after = durable_rows(self.fixture.store)
        self.assertEqual(self.handle(command), accepted)
        self.assertEqual(durable_rows(self.fixture.store), after)
        self.assertEqual(len(self.fixture.store.read_events("p-1")), 10)
        self.assert_replay_matches()

    def test_event_failure_rolls_back_key_then_original_command_can_retry(self):
        self.assert_fault_rolls_back_then_allows_retry("event")

    def test_result_failure_rolls_back_key_then_original_command_can_retry(self):
        self.assert_fault_rolls_back_then_allows_retry("result")


class ProcessCompetitionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = open_command_fixture(self)

    def runner(self):
        runner = getattr(support, "run_two_processes_against_same_sqlite_file", None)
        self.assertTrue(callable(runner), "M0-04 real two-process fixture is missing")
        return runner

    def claims(self):
        factory = getattr(support, "make_claim_commands", None)
        self.assertTrue(callable(factory), "M0-04 independent claim-command fixture is missing")
        return factory(task_id="t-1", expected_revision=0)

    def assert_process_observations(self, commands, observations, expected_head):
        self.assertEqual(len(observations), 2)
        pids = [observation["pid"] for observation in observations]
        self.assertEqual(len(set(pids)), 2)
        self.assertNotIn(os.getpid(), pids)
        for command, observed in zip(commands, observations):
            self.assertEqual(observed["command_id"], command.id)
            self.assertEqual(observed["idempotency_key"], command.idempotency_key)
            self.assertEqual(observed["expected_revision"], command.expected_revision)
            self.assertEqual(observed["observed_head_sequence"], expected_head)
            self.assertEqual(observed["exit_code"], 0)
            self.assertLessEqual(observed["ready_ns"], observed["gate_released_ns"])
            self.assertLessEqual(observed["gate_released_ns"], observed["handling_started_ns"])

    def assert_retries_preserve_rows(self, commands, results):
        before = durable_rows(self.fixture.store)
        for command, expected in zip(commands, results):
            self.assertEqual(self.fixture.handler.handle(command, authenticated_actor_id=command.actor_id), expected)
        self.assertEqual(durable_rows(self.fixture.store), before)
        self.assertEqual(self.fixture.store.read_projection("p-1"), Projection.rebuild(self.fixture.store.read_events("p-1")))

    def test_claim_fixture_uses_distinct_actors_ids_keys_and_same_precondition(self):
        commands = self.claims()
        self.assertEqual(len(commands), 2)
        self.assertEqual({command.actor_id for command in commands}, {"a-1", "a-2"})
        self.assertEqual(len({command.id for command in commands}), 2)
        self.assertEqual(len({command.idempotency_key for command in commands}), 2)
        self.assertEqual([(c.project_id, c.target_id, c.type, c.expected_revision) for c in commands], [("p-1", "t-1", "task.claim", 0)] * 2)

    def test_two_process_claims_have_one_winner_and_durable_version_evidence(self):
        self.fixture.handler.handle(make_task_create_command(), authenticated_actor_id="a-1")
        commands = self.claims()
        observations = []
        results = self.runner()(self.fixture.db_path, commands, observations=observations)
        self.assert_process_observations(commands, observations, expected_head=8)
        self.assertEqual(sorted(result.status for result in results), ["accepted", "rejected"])
        winner = next(i for i, result in enumerate(results) if result.status == "accepted")
        loser = 1 - winner
        self.assertEqual([result.aggregate_revision for result in results], [1, 1])
        self.assertEqual(results[loser].error_code, "REVISION_CONFLICT")
        events = self.fixture.store.read_events("p-1")
        self.assertEqual([event.sequence for event in events], list(range(1, 13)))
        raced = events[8:]
        self.assertEqual([event.type for event in raced], ["command.received", "task.claimed", "command.received", "command.rejected"])
        for command, result in zip(commands, results):
            self.assertEqual(result.event_ids, tuple(e.id for e in raced if e.causation_id == command.id))
        self.assertEqual(raced[-1].payload["error"]["context"], {
            "command_id": commands[loser].id, "target_id": "t-1", "expected_revision": 0, "current_revision": 1,
        })
        state = self.fixture.store.read_projection("p-1")["task:t-1"]
        self.assertEqual((state["status"], state["owner_id"], state["revision"]), ("assigned", commands[winner].actor_id, 1))
        self.assert_retries_preserve_rows(commands, results)

    def test_two_process_identical_retry_returns_one_original_batch(self):
        command = make_task_create_command(idempotency_key="shared")
        commands = [command, Command.from_dict(command.to_dict())]
        observations = []
        results = self.runner()(self.fixture.db_path, commands, observations=observations)
        self.assert_process_observations(commands, observations, expected_head=6)
        self.assertEqual(results[0], results[1])
        self.assertEqual((results[0].status, results[0].aggregate_revision), ("accepted", 0))
        events = self.fixture.store.read_events("p-1")
        self.assertEqual(len(events), 8)
        self.assertEqual([e.type for e in events[6:]], ["command.received", "task.created"])
        self.assertEqual(results[0].event_ids, tuple(e.id for e in events[6:]))
        self.assert_retries_preserve_rows(commands, results)

    def test_two_process_same_key_different_content_preserves_winner(self):
        first = make_task_create_command(idempotency_key="shared", title="First")
        second = replace(first, id="different-command", payload={"title": "Second"})
        commands = [first, second]
        observations = []
        results = self.runner()(self.fixture.db_path, commands, observations=observations)
        self.assert_process_observations(commands, observations, expected_head=6)
        self.assertEqual(sorted(result.status for result in results), ["accepted", "rejected"])
        winner = next(i for i, result in enumerate(results) if result.status == "accepted")
        loser = 1 - winner
        self.assertEqual(results[loser], CommandResult("rejected", commands[loser].id, (), None, "IDEMPOTENCY_CONFLICT"))
        record = self.fixture.store.read_idempotency(("p-1", "a-1", "shared"))
        self.assertEqual(record["command_id"], commands[winner].id)
        self.assertEqual(record["result"], results[winner].to_dict())
        self.assertEqual(len(self.fixture.store.read_events("p-1")), 8)
        self.assertEqual(self.fixture.store.read_projection("p-1")["task:t-1"]["title"], commands[winner].payload["title"])
        self.assert_retries_preserve_rows(commands, results)

    def test_runner_requires_two_valid_commands_shared_file_and_finite_deadline(self):
        runner = self.runner()
        command = make_task_create_command()
        for path, commands, timeout in (
            (":memory:", [command, command], 30),
            (self.fixture.db_path, [command], 30),
            (self.fixture.db_path, [command] * 3, 30),
            (self.fixture.db_path, [command, None], 30),
            (self.fixture.db_path, [command, command], 0),
            (self.fixture.db_path, [command, command], float("inf")),
            (self.fixture.db_path, [command, command], float("nan")),
        ):
            with self.subTest(path=path, count=len(commands), timeout=timeout):
                with self.assertRaises(ValueError):
                    runner(path, commands, timeout=timeout)

    def test_worker_open_failure_is_reported_and_owned_children_are_reaped(self):
        runner = self.runner()
        path = Path(self.fixture.db_path).with_name("not-a-database.sqlite")
        path.write_bytes(b"This is not a SQLite database.")
        before = {process.pid for process in multiprocessing.active_children()}
        with self.assertRaisesRegex(RuntimeError, "DatabaseError"):
            runner(str(path), [make_task_create_command()] * 2)
        self.assertFalse({p.pid for p in multiprocessing.active_children()} - before)

    def test_timeout_reaps_blocked_writers_without_altering_database(self):
        runner = self.runner()
        commands = [make_task_create_command()] * 2
        children = {process.pid for process in multiprocessing.active_children()}
        before = durable_rows(self.fixture.store)
        # A real independent writer cannot acquire SQLite's transaction while
        # this connection owns it. The fixture deadline must not leak children.
        with self.fixture.store.transaction():
            with self.assertRaises(TimeoutError):
                runner(self.fixture.db_path, commands, timeout=0.5)
        self.assertFalse({p.pid for p in multiprocessing.active_children()} - children)
        self.assertEqual(durable_rows(self.fixture.store), before)
        self.assertEqual(self.fixture.handler.handle(commands[0], authenticated_actor_id="a-1").status, "accepted")


if __name__ == "__main__":
    unittest.main()
