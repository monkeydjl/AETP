"""Real precheck evidence cannot replace unavailable execution authorization."""

import hashlib
from contextlib import closing
import json
import multiprocessing
from pathlib import Path
import sqlite3
from unittest.mock import patch

from aetp.core.projection import Projection
from aetp.core.runtime import RuntimeRecovery
from tests.m1.support import CollaborationCase, review_worker


class VerificationTests(CollaborationCase):
    def verify_command(self, identifier="v-1", *, artifact_id="art-1", **extra):
        artifact = self.state()[f"artifact:{artifact_id}"]
        return self.command("verification.run", identifier, {
            "artifact_id": artifact_id, "artifact_digest": artifact["content_digest"], **extra}, actor="a-2")

    def test_actual_passing_precheck_is_evidence_but_formal_result_is_inconclusive(self):
        self.artifact()
        self.request_review()
        self.accept(self.submit_review_command())
        task = self.state()["task:t-1"]
        result = self.accept(self.verify_command())
        verification = self.state()["verification:v-1"]
        evidence = self.state()[f'artifact:{verification["evidence_id"]}']
        report = json.loads(evidence["content"])
        self.assertEqual(verification["result"], "INCONCLUSIVE")
        self.assertEqual(verification["reason"], "ENFORCEMENT_UNAVAILABLE")
        self.assertEqual(report["observed_result"], "PASSED")
        self.assertEqual(report["checks"], [{"criterion": "Overview", "matched": True},
                                           {"criterion": "Failure case", "matched": True}])
        self.assertEqual(report["artifact_digest"], self.state()["artifact:art-1"]["content_digest"])
        self.assertEqual(verification["evidence_digest"], "sha256:" + hashlib.sha256(evidence["content"].encode()).hexdigest())
        self.assertEqual(verification["criteria_digest"], task["criteria_digest"])
        self.assertEqual(verification["task_revision"], task["revision"])
        self.assertEqual(verification["inputs"]["environment_digest"], report["environment_digest"])
        from aetp.collaboration import checks
        self.assertEqual(report["test_suite_digest"], "sha256:" + hashlib.sha256(Path(checks.__file__).read_bytes()).hexdigest())
        self.assertEqual(report["command"], "aetp.document.contains_all/v1")
        self.assertEqual(verification["execution"]["authorization"], "unavailable")
        self.assertIsNone(verification["execution"]["action_id"])
        self.assertEqual(self.state()["task:t-1"], task)
        batch = [event for event in self.store.read_events("p-1") if event.causation_id == result.command_id]
        self.assertEqual([event.type for event in batch], ["command.received", "artifact.created", "verification.completed"])

    def test_failed_content_check_is_preserved_without_claiming_a_formal_pass(self):
        self.artifact(content="Overview only")
        self.accept(self.verify_command())
        verification = self.state()["verification:v-1"]
        report = json.loads(self.state()[f'artifact:{verification["evidence_id"]}']["content"])
        self.assertEqual(report["observed_result"], "FAILED")
        self.assertEqual(report["checks"][1], {"criterion": "Failure case", "matched": False})
        self.assertEqual(verification["result"], "INCONCLUSIVE")
        self.assertEqual(self.state()["task:t-1"]["status"], "assigned")

    def test_review_alone_precheck_alone_and_inconclusive_cannot_pass_task_gates(self):
        self.artifact()
        original = self.state()["task:t-1"]
        for kind in ("task.verify", "task.complete"):
            self.reject(self.command(kind, "t-1", {"artifact_id": "art-1"}, revision=1), "QUALITY_GATE_NOT_MET")
        self.request_review()
        self.accept(self.submit_review_command())
        self.reject(self.command("task.verify", "t-1", {"artifact_id": "art-1", "review_id": "rev-1"}, revision=1), "QUALITY_GATE_NOT_MET")
        self.accept(self.verify_command())
        for kind in ("task.verify", "task.complete"):
            self.reject(self.command(kind, "t-1", {"artifact_id": "art-1", "review_id": "rev-1",
                                                   "verification_id": "v-1"}, revision=1), "QUALITY_GATE_NOT_MET")
        self.assertEqual(self.state()["task:t-1"], original)

    def test_client_cannot_submit_passed_or_inject_runner_result_or_authorization(self):
        self.artifact()
        self.reject(self.command("verification.submit", "forged", {
            "result": "PASSED", "evidence": "pretend tests passed", "action_id": "made-up"}, actor="a-2"),
                    "ENFORCEMENT_UNAVAILABLE")
        for extra in ({"result": "PASSED"}, {"runner_id": "trusted"}, {"binding_id": "made-up"},
                      {"report": "all passed"}, {"method": "shell"}):
            self.reject(self.verify_command(**extra), "INVALID_PAYLOAD")
        self.assertNotIn("verification:v-1", self.state())

    def test_retry_returns_original_batch_without_reexecuting_precheck(self):
        self.artifact()
        command = self.verify_command()
        result = self.accept(command)
        before = self.store.read_events("p-1")
        with patch("aetp.collaboration.checks.run_precheck", side_effect=AssertionError("precheck reran on retry")):
            self.assertEqual(self.accept(command), result)
        self.assertEqual(self.store.read_events("p-1"), before)

    def test_verification_and_report_rollback_together_on_real_sqlite_failure(self):
        self.artifact()
        command = self.verify_command()
        before = self.store.read_events("p-1")
        with closing(sqlite3.connect(self.fixture.db_path)) as connection, connection:
            connection.execute("CREATE TRIGGER fail_m1_verification BEFORE INSERT ON events "
                               "WHEN NEW.type = 'verification.completed' BEGIN SELECT RAISE(ABORT, 'fault'); END")
        with self.assertRaises(ValueError):
            self.service.handle(command, authenticated_actor_id="a-2")
        self.assertEqual(self.store.read_events("p-1"), before)
        self.assertNotIn("artifact:v-1:evidence", self.state())
        self.assertIsNone(self.store.read_idempotency(("p-1", "a-2", command.idempotency_key)))
        with closing(sqlite3.connect(self.fixture.db_path)) as connection, connection:
            connection.execute("DROP TRIGGER fail_m1_verification")
        self.accept(command)

    def test_precheck_uses_current_task_facts_and_rejects_stale_artifact(self):
        self.artifact()
        command = self.verify_command()
        self.accept(self.command("task.release", "t-1", {}, revision=1))
        self.reject(command, "EVIDENCE_STALE")
        self.assertNotIn("verification:v-1", self.state())

    def test_evidence_identifier_collision_is_rejected_without_replacing_existing_content(self):
        self.artifact()
        original, _ = self.artifact("v-1:evidence", content="Existing document")
        self.reject(self.verify_command(), "REVISION_CONFLICT")
        self.assertEqual(self.state()["artifact:v-1:evidence"], original)

    def test_pure_readonly_recovery_rebuilds_mixed_history_without_checker_or_cache(self):
        self.artifact()
        self.request_review()
        self.accept(self.submit_review_command())
        self.accept(self.verify_command())
        self.reject(self.command("task.verify", "t-1", {}, revision=1), "QUALITY_GATE_NOT_MET")
        expected = self.state()
        with closing(sqlite3.connect(self.fixture.db_path)) as connection, connection:
            connection.execute("DELETE FROM projections")
            connection.execute("DELETE FROM projection_meta")
            connection.execute("DELETE FROM idempotency")
        before = Path(self.fixture.db_path).read_bytes()
        recovery = RuntimeRecovery.open(self.fixture.db_path)
        self.addCleanup(recovery.close)
        with patch("aetp.collaboration.checks.run_precheck", side_effect=AssertionError("precheck called during Replay")):
            self.assertEqual(recovery.rebuild_project("p-1"), expected)
            self.assertEqual(recovery.reconcile_pending("p-1"), [])
        self.assertEqual(Path(self.fixture.db_path).read_bytes(), before)
        self.assertEqual(recovery.runtime_invocation_count, 0)

    def test_two_processes_cannot_both_finalize_the_same_review_revision(self):
        self.artifact()
        self.request_review()
        commands = [self.submit_review_command(status="approved"),
                    self.submit_review_command(status="rejected")]
        context = multiprocessing.get_context("spawn")
        gate = context.Barrier(2)
        output = context.Queue()
        children = [context.Process(target=review_worker, args=(self.fixture.db_path, command.to_dict(), gate, output))
                    for command in commands]
        try:
            for child in children:
                child.start()
            results = [output.get(timeout=20) for _ in children]
            for child in children:
                child.join(20)
                self.assertFalse(child.is_alive(), "owned review worker did not exit")
                self.assertEqual(child.exitcode, 0)
            self.assertTrue(all("result" in item for item in results), results)
            self.assertEqual(sorted(item["result"]["status"] for item in results), ["accepted", "rejected"])
            self.assertEqual([item["result"]["error_code"] for item in results if item["result"]["status"] == "rejected"], ["REVISION_CONFLICT"])
            terminal = [event for event in self.store.read_events("p-1") if event.type in {"review.approved", "review.rejected"}]
            self.assertEqual(len(terminal), 1)
        finally:
            for child in children:
                if child.pid is not None:
                    if child.is_alive():
                        child.terminate()
                    child.join(5)
                    if child.is_alive():
                        child.kill()
                        child.join(5)
                    child.close()
            output.close()
            output.join_thread()

    def test_non_string_classification_and_review_status_are_typed_rejections(self):
        for value in ([], {}, True):
            command = self.command("artifact.submit", f"bad-{self.counter}", {
                "task_id": "t-1", "type": "document", "content": "Text", "data_classification": value})
            try:
                self.reject(command, "POLICY_DENIED")
            except TypeError as exc:
                self.fail(f"malformed classification escaped the Command rejection boundary: {exc}")
        self.artifact()
        self.request_review()
        for value in ([], {}, True):
            try:
                self.reject(self.submit_review_command(status=value), "INVALID_PAYLOAD")
            except TypeError as exc:
                self.fail(f"malformed Review status escaped the Command rejection boundary: {exc}")

    def test_unclassified_inline_content_cannot_be_labelled_trusted(self):
        artifact, _ = self.artifact()
        self.assertTrue(artifact["source"]["untrusted_input"])
        child, _ = self.artifact("art-2", derived_from=["art-1"])
        self.assertTrue(child["source"]["untrusted_input"])

    def test_base_handler_rejection_of_m1_command_has_recoverable_causal_address(self):
        command = self.command("artifact.submit", "unsupported-candidate", {
            "task_id": "t-1", "type": "document", "content": "No M1 handler"})
        result = self.fixture.handler.handle(command, authenticated_actor_id="a-1")
        self.assertEqual(result.error_code, "UNSUPPORTED_COMMAND")
        recovery = RuntimeRecovery.open(self.fixture.db_path)
        self.addCleanup(recovery.close)
        self.assertEqual(recovery.reconcile_pending("p-1"), [])
