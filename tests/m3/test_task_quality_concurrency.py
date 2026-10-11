"""Actual SQLite rollback and separate connections at the quality boundary."""

from concurrent.futures import ThreadPoolExecutor
import sqlite3
import threading
from unittest.mock import patch

from aetp.core.projection import Projection
from aetp.quality.service import TaskQualityService
from aetp.runtime.service import ExecutionService
from aetp.storage.sqlite_store import SQLiteStore
from tests.m0.support import install_event_failure_fixture, install_result_failure_fixture
from tests.m3.quality_support import QualityCase


class QualityAtomicityTests(QualityCase):
    def test_last_completion_effect_failure_rolls_back_every_fact_and_retry_succeeds(self):
        self.verified_quality()
        before, state = self.store.read_events("p-1"), self.state()
        command = self.command("task.quality.complete", "t-1", actor="a-2")
        proof = self.input_authority.issue(command, exposure="internal")
        remove = install_event_failure_fixture(self, self.store, "task.completed")
        with self.assertRaises(ValueError) as error:
            self.service.handle(command, authenticated_actor_id="a-2", input_receipt=proof)
        self.assertIsInstance(error.exception.__cause__, sqlite3.IntegrityError)
        remove()
        self.assertEqual(self.store.read_events("p-1"), before)
        self.assertEqual(self.state(), state)
        self.assertNotIn(command.id, [row.id for row in self.commands()])
        result = self.service.handle(command, authenticated_actor_id="a-2", input_receipt=proof)
        self.assertEqual(result.status, "accepted", result.to_dict())
        self.assertEqual(self.event_types().count("task.completed"), 1)
        self.assertEqual(self.event_types().count("task.integration_exempted"), 1)

    def test_review_terminal_failure_rolls_back_all_child_reviews(self):
        self.enroll_quality()
        self.capture(identifier="doc-1")
        self.capture(identifier="doc-2")
        self.quality_submit(["doc-1", "doc-2"])
        before = self.store.read_events("p-1")
        remove = install_event_failure_fixture(self, self.store, "task.in_review")
        with self.assertRaises(ValueError):
            self.quality_review()
        remove()
        self.assertEqual(self.store.read_events("p-1"), before)
        self.assertFalse(any(key.startswith("review:") for key in self.state()))
        self.assertEqual(self.task()["status"], "ready_for_review")
        self.quality_review()
        self.assertEqual(len(self.task()["quality_cycle"]["reviews"]), 2)

    def test_idempotency_result_write_failure_rolls_back_completion(self):
        self.verified_quality()
        before = self.store.read_events("p-1")
        remove = install_result_failure_fixture(self, self.store)
        with self.assertRaises(sqlite3.IntegrityError):
            self.quality_complete()
        remove()
        self.assertEqual(self.store.read_events("p-1"), before)
        self.assertEqual(self.task()["status"], "verified")
        self.quality_complete()
        self.assertEqual(self.task()["status"], "completed")

    def test_lost_response_retries_the_saved_result_without_re_evaluation(self):
        self.verified_quality()
        command = self.command("task.quality.complete", "t-1", actor="a-2")
        proof = self.input_authority.issue(command, exposure="internal")
        saved = []

        def transport():
            saved.append(self.service.handle(command, authenticated_actor_id="a-2", input_receipt=proof))
            raise ConnectionError("response was lost after commit")

        with self.assertRaises(ConnectionError):
            transport()
        before = self.store.read_events("p-1")
        self.clock_value = self.session.expires_at_wall_ms + 1
        with patch.object(self.service, "_evaluate", side_effect=AssertionError("retry evaluated again")):
            retried = self.service.handle(command, authenticated_actor_id="a-2")
        self.assertEqual(retried, saved[0])
        self.assertEqual(self.store.read_events("p-1"), before)
        self.assertEqual(self.task()["status"], "completed")

    def race(self, kind, payload):
        barrier = threading.Barrier(2)
        commands = [self.command(kind, "t-1", payload, actor=actor) for actor in ("a-1", "a-2")]
        proofs = [self.input_authority.issue(command, exposure="internal") for command in commands]
        at = self.clock_value

        def worker(index):
            with SQLiteStore.open(self.fixture.db_path) as store:
                execution = ExecutionService(store, self.runtime, clock=lambda: at)
                self.assertEqual(execution.recover("p-1")["barrier"], "open")
                service = TaskQualityService(store, owner_id="human-owner", execution=execution,
                    input_authority=self.input_authority, meter=self.meter, clock=lambda: at)
                barrier.wait(timeout=15)
                return service.handle(commands[index], authenticated_actor_id=commands[index].actor_id,
                                      input_receipt=proofs[index])

        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(worker, (0, 1)))
        self.assertEqual(sorted(row.status for row in results), ["accepted", "rejected"])
        self.assertEqual(next(row.error_code for row in results if row.status == "rejected"), "REVISION_CONFLICT")
        self.assertEqual(Projection.pending_command_ids(self.store.read_events("p-1"), self.commands()), [])

    def test_separate_connections_racing_review_request_create_one_review_set(self):
        self.ready_quality()
        self.race("task.quality.request_review", {"reviewers": {"doc-1": "a-2"}})
        self.assertEqual(self.event_types().count("task.in_review"), 1)
        self.assertEqual(self.event_types().count("review.quality_requested"), 1)

    def test_separate_connections_racing_completion_commit_one_terminal(self):
        self.verified_quality()
        self.race("task.quality.complete", {})
        self.assertEqual(self.event_types().count("task.completed"), 1)
        self.assertEqual(self.event_types().count("task.integration_exempted"), 1)
