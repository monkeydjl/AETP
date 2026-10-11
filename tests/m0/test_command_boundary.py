"""M0-02 tests for the Command acceptance and transaction boundary."""

from __future__ import annotations

import sqlite3
import unittest

from tests.m0.support import (
    install_event_failure_fixture,
    install_result_failure_fixture,
    make_command,
    make_task_create_command,
    open_command_fixture,
)


class CommandBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = open_command_fixture(self)

    def require_handler(self):
        self.assertIsNotNone(
            self.fixture.handler,
            "CommandHandler is not implemented yet",
        )
        return self.fixture.handler

    def test_task_create_commits_received_and_domain_events_atomically(self):
        handler = self.require_handler()
        result = handler.handle(
            make_task_create_command(),
            authenticated_actor_id="a-1",
        )

        self.assertEqual(result.status, "accepted")
        events = self.fixture.store.read_events(
            "p-1", after_sequence=self.fixture.after_sequence
        )
        self.assertEqual(
            [event.type for event in events],
            ["command.received", "task.created"],
        )
        self.assertEqual(result.event_ids, tuple(event.id for event in events))
        self.assertEqual(
            self.fixture.store.read_idempotency(("p-1", "a-1", "k-1"))["result"],
            result.to_dict(),
        )

    def test_actor_mismatch_is_rejected_without_domain_event(self):
        handler = self.require_handler()
        result = handler.handle(
            make_task_create_command(actor_id="a-claimed"),
            authenticated_actor_id="a-real",
        )

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "ACTOR_MISMATCH")
        self.assertEqual(
            self.fixture.store.read_events(
                "p-1", after_sequence=self.fixture.after_sequence
            ),
            [],
        )
        record = self.fixture.store.read_idempotency(("p-1", "a-real", "k-1"))
        self.assertIsNone(record, "unbound input must not reserve a protocol Command")
        read_audit = getattr(self.fixture.store, "read_security_audit", None)
        self.assertTrue(callable(read_audit), "trusted-entry security audit is missing")
        audit = read_audit(authenticated_actor_id="a-real")
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["error_code"], "ACTOR_MISMATCH")
        self.assertEqual(audit[0]["claimed_actor_id"], "a-claimed")
        self.assertEqual(audit[0]["authenticated_actor_id"], "a-real")

    def test_expected_revision_conflict_is_rejected_without_domain_effect(self):
        handler = self.require_handler()
        create = make_task_create_command()
        self.assertEqual(
            handler.handle(create, authenticated_actor_id="a-1").status,
            "accepted",
        )
        claim = make_command(
            command_id="claim-stale",
            actor_id="a-1",
            command_type="task.claim",
            target_id="t-1",
            payload={},
            expected_revision=1,
            idempotency_key="claim-stale",
        )

        result = handler.handle(claim, authenticated_actor_id="a-1")

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "REVISION_CONFLICT")
        event_types = [
            event.type
            for event in self.fixture.store.read_events(
                "p-1", after_sequence=self.fixture.after_sequence
            )
        ]
        self.assertNotIn("task.claimed", event_types)
        self.assertEqual(
            self.fixture.store.read_idempotency(("p-1", "a-1", "claim-stale"))["result"]["error_code"],
            "REVISION_CONFLICT",
        )

    def test_agent_cannot_create_project_without_bootstrap_permission(self):
        handler = self.require_handler()
        command = make_command(
            command_id="unauthorized-project",
            actor_id="a-1",
            command_type="project.create",
            target_id=None,
            payload={"status": "planning"},
            expected_revision=0,
            idempotency_key="unauthorized-project",
            project_id="p-2",
        )

        result = handler.handle(command, authenticated_actor_id="a-1")

        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "PERMISSION_DENIED")
        self.assertEqual(
            [event.type for event in self.fixture.store.read_events("p-2")],
            ["command.received", "command.rejected"],
        )

    def test_same_command_retry_returns_original_result_without_duplicate_events(self):
        handler = self.require_handler()
        command = make_task_create_command()

        first = handler.handle(command, authenticated_actor_id="a-1")
        second = handler.handle(command, authenticated_actor_id="a-1")

        self.assertEqual(first, second)
        events = self.fixture.store.read_events(
            "p-1", after_sequence=self.fixture.after_sequence
        )
        self.assertEqual(
            [event.type for event in events],
            ["command.received", "task.created"],
        )

    def test_same_idempotency_key_with_different_content_is_rejected(self):
        handler = self.require_handler()
        first = handler.handle(
            make_task_create_command(),
            authenticated_actor_id="a-1",
        )
        conflicting = make_task_create_command(
            title="Different title",
            command_id="conflicting-task-create",
        )

        result = handler.handle(conflicting, authenticated_actor_id="a-1")

        self.assertEqual(first.status, "accepted")
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "IDEMPOTENCY_CONFLICT")
        event_types = [
            event.type
            for event in self.fixture.store.read_events(
                "p-1", after_sequence=self.fixture.after_sequence
            )
        ]
        self.assertEqual(event_types, ["command.received", "task.created"])


    def _task_command(self, command_type, key, revision, actor_id="a-1", target="t-1"):
        return make_command(
            command_id=key,
            actor_id=actor_id,
            command_type=command_type,
            target_id=target,
            payload={},
            expected_revision=revision,
            idempotency_key=key,
        )

    def _create_task(self):
        result = self.require_handler().handle(
            make_task_create_command(), authenticated_actor_id="a-1"
        )
        self.assertEqual(result.status, "accepted")
        return result

    def test_missing_expected_revision_cannot_claim_after_intervening_changes(self):
        handler = self.require_handler()
        self._create_task()
        delayed = self._task_command("task.claim", "unversioned-claim", None)
        for kind, key, revision in [
            ("task.claim", "first-claim", 0),
            ("task.release", "first-release", 1),
        ]:
            self.assertEqual(
                handler.handle(self._task_command(kind, key, revision),
                               authenticated_actor_id="a-1").status,
                "accepted",
            )
        result = handler.handle(delayed, authenticated_actor_id="a-1")
        self.assertEqual(result.status, "rejected")
        self.assertEqual(result.error_code, "REVISION_CONFLICT")
        domain = [event for event in self.fixture.store.read_events("p-1")
                  if event.type.startswith("task.")]
        self.assertEqual([event.aggregate_revision for event in domain], [0, 1, 2])

    def test_missing_expected_revision_cannot_release_an_owned_task(self):
        handler = self.require_handler()
        self._create_task()
        self.assertEqual(
            handler.handle(self._task_command("task.claim", "owner-claim", 0),
                           authenticated_actor_id="a-1").status,
            "accepted",
        )
        result = handler.handle(
            self._task_command("task.release", "unversioned-release", None),
            authenticated_actor_id="a-1",
        )
        self.assertEqual(result.error_code, "REVISION_CONFLICT")
        valid = handler.handle(
            self._task_command("task.release", "versioned-release", 1),
            authenticated_actor_id="a-1",
        )
        self.assertEqual(valid.status, "accepted")
        self.assertEqual(valid.aggregate_revision, 2)

    def test_authenticated_rejection_is_event_audited_and_retry_is_idempotent(self):
        handler = self.require_handler()
        self._create_task()
        before = self.fixture.store.read_events("p-1")[-1].sequence
        command = self._task_command("task.claim", "audit-stale", 5)
        result = handler.handle(command, authenticated_actor_id="a-1")
        self.assertEqual(result.error_code, "REVISION_CONFLICT")
        events = self.fixture.store.read_events("p-1", after_sequence=before)
        self.assertEqual([event.type for event in events],
                         ["command.received", "command.rejected"])
        self.assertEqual([event.aggregate_revision for event in events], [0, 0])
        self.assertEqual(result.event_ids, tuple(event.id for event in events))
        error = events[-1].payload["error"]
        self.assertEqual(error["code"], "REVISION_CONFLICT")
        self.assertFalse(error["retryable"])
        self.assertEqual(error["context"]["expected_revision"], 5)
        self.assertEqual(error["context"]["current_revision"], 0)
        self.assertTrue(error["message"])
        self.assertEqual(error["severity"], "medium")
        self.assertTrue(all(event.causation_id == command.id for event in events))
        self.assertEqual(handler.handle(command, authenticated_actor_id="a-1"), result)
        self.assertEqual(self.fixture.store.read_events("p-1", after_sequence=before), events)
        self.assertEqual(
            self.fixture.store.read_idempotency(("p-1", "a-1", "audit-stale"))["result"],
            result.to_dict(),
        )

    def test_rejection_audit_does_not_create_target_or_advance_its_revision(self):
        handler = self.require_handler()
        invalid = make_task_create_command(idempotency_key="bad-create", title="")
        self.assertEqual(handler.handle(invalid, authenticated_actor_id="a-1").error_code,
                         "INVALID_PAYLOAD")
        self.assertEqual(
            [event.type for event in self.fixture.store.read_events(
                "p-1", after_sequence=self.fixture.after_sequence)],
            ["command.received", "command.rejected"],
        )
        self._create_task()
        self.assertEqual(
            handler.handle(self._task_command("task.claim", "too-old", 4),
                           authenticated_actor_id="a-1").error_code,
            "REVISION_CONFLICT",
        )
        valid = handler.handle(self._task_command("task.claim", "current", 0),
                               authenticated_actor_id="a-1")
        self.assertEqual(valid.status, "accepted")
        self.assertEqual(valid.aggregate_revision, 1)

    def test_actor_mismatch_cannot_reserve_legitimate_command_id(self):
        handler = self.require_handler()
        command = make_task_create_command()
        forged = handler.handle(command, authenticated_actor_id="a-2")
        self.assertEqual(forged.error_code, "ACTOR_MISMATCH")
        try:
            legitimate = handler.handle(command, authenticated_actor_id="a-1")
        except ValueError as error:
            self.fail(f"unbound input poisoned a legitimate Command ID: {error}")
        self.assertEqual(legitimate.status, "accepted")
        self.assertIsNone(self.fixture.store.read_idempotency(("p-1", "a-2", "k-1")))

    def test_nested_handler_failure_rolls_back_its_entire_batch(self):
        handler = self.require_handler()
        command = make_task_create_command()
        remove_failure = install_event_failure_fixture(self, self.fixture.store)
        with self.fixture.store.transaction():
            with self.assertRaises(ValueError):
                handler.handle(command, authenticated_actor_id="a-1")
        self.assertEqual(
            self.fixture.store.read_events("p-1", after_sequence=self.fixture.after_sequence),
            [],
        )
        self.assertIsNone(self.fixture.store.read_idempotency(("p-1", "a-1", "k-1")))
        remove_failure()
        self.assertEqual(handler.handle(command, authenticated_actor_id="a-1").status,
                         "accepted")

    def test_top_level_event_failure_rolls_back_command_and_events(self):
        handler = self.require_handler()
        command = make_task_create_command()
        remove_failure = install_event_failure_fixture(self, self.fixture.store)
        with self.assertRaises(ValueError):
            handler.handle(command, authenticated_actor_id="a-1")
        self.assertEqual(
            self.fixture.store.read_events("p-1", after_sequence=self.fixture.after_sequence),
            [],
        )
        self.assertIsNone(self.fixture.store.read_idempotency(("p-1", "a-1", "k-1")))
        remove_failure()
        self.assertEqual(handler.handle(command, authenticated_actor_id="a-1").status,
                         "accepted")

    def test_result_index_failure_rolls_back_command_and_both_events(self):
        handler = self.require_handler()
        command = make_task_create_command()
        remove_failure = install_result_failure_fixture(self, self.fixture.store)
        with self.assertRaises(sqlite3.IntegrityError):
            handler.handle(command, authenticated_actor_id="a-1")
        self.assertEqual(
            self.fixture.store.read_events("p-1", after_sequence=self.fixture.after_sequence),
            [],
        )
        self.assertIsNone(self.fixture.store.read_idempotency(("p-1", "a-1", "k-1")))
        remove_failure()
        self.assertEqual(handler.handle(command, authenticated_actor_id="a-1").status,
                         "accepted")

    def test_invalid_target_is_rejected_and_audited(self):
        command = self._task_command("task.create", "missing-target", 0, target=None)
        result = self.require_handler().handle(command, authenticated_actor_id="a-1")
        self.assertEqual(result.error_code, "INVALID_TARGET")
        self.assertEqual(
            [event.type for event in self.fixture.store.read_events(
                "p-1", after_sequence=self.fixture.after_sequence)],
            ["command.received", "command.rejected"],
        )

    def test_unsupported_command_cannot_bypass_missing_quality_gates(self):
        self._create_task()
        command = self._task_command("task.complete", "unsupported-complete", 0)
        result = self.require_handler().handle(command, authenticated_actor_id="a-1")
        self.assertEqual(result.error_code, "UNSUPPORTED_COMMAND")
        events = self.fixture.store.read_events("p-1")
        self.assertNotIn("task.completed", [event.type for event in events])
        self.assertEqual(events[-1].type, "command.rejected")

    def test_unregistered_actor_is_rejected_without_domain_effect(self):
        command = make_task_create_command(actor_id="stranger")
        result = self.require_handler().handle(command, authenticated_actor_id="stranger")
        self.assertEqual(result.error_code, "PERMISSION_DENIED")
        self.assertEqual(
            [event.type for event in self.fixture.store.read_events(
                "p-1", after_sequence=self.fixture.after_sequence)],
            ["command.received", "command.rejected"],
        )

    def test_non_owner_cannot_release_current_task(self):
        handler = self.require_handler()
        self._create_task()
        self.assertEqual(
            handler.handle(self._task_command("task.claim", "owner", 0),
                           authenticated_actor_id="a-1").status,
            "accepted",
        )
        result = handler.handle(
            self._task_command("task.release", "other-release", 1, actor_id="a-2"),
            authenticated_actor_id="a-2",
        )
        self.assertEqual(result.error_code, "PERMISSION_DENIED")
        self.assertNotIn("task.requeued", [event.type for event in self.fixture.store.read_events("p-1")])


if __name__ == "__main__":
    unittest.main()
