"""Live trust, dual-CAS, shared rejection and exact retry behavior."""
import copy
from contextlib import ExitStack
from dataclasses import replace
from unittest.mock import patch
from aetp.core.commands import CommandHandler
from aetp.core.projection import Projection
from aetp.governance.trust import InputAuthority
from aetp.quality.service import TaskQualityService
from aetp.storage.sqlite_store import SQLiteStore
from tests.m3.integration_live_support import IntegrationCase, IntegrationContractService
from tests.m3.test_integration_shared_guards import configuration

class IntegrationLiveTests(IntegrationCase):
    def test_real_receipt_declaration_changes_only_project_and_has_no_execution(self):
        before, offset = self.state(), len(self.store.read_events("p-1"))
        command = self.declaration()
        guards = ("aetp.runtime.document.DocumentRuntime.lookup", "aetp.runtime.document.DocumentRuntime.register",
                  "aetp.runtime.service.ExecutionService.validation_context", "aetp.runtime.service.ExecutionService.dispatch",
                  "aetp.acceptance.runner.FixedJsonRunner.run", "subprocess.Popen", "socket.socket")
        with ExitStack() as stack:
            calls = [stack.enter_context(patch(name, side_effect=AssertionError(name))) for name in guards]
            with patch.object(self.input_authority, "verify", wraps=self.input_authority.verify) as verify:
                original = self.service._evaluate
                def evaluate(actual, actor):
                    self.assertTrue(self.store.in_transaction)
                    return original(actual, actor)
                with patch.object(self.service, "_evaluate", side_effect=evaluate):
                    result = self.submit(command)
                verify.assert_called_once()
            for call in calls: call.assert_not_called()
        self.assertEqual(result.status, "accepted", result.to_dict())
        after = self.state()
        self.assertEqual({k:v for k,v in before.items() if k != "project:p-1"},
                         {k:v for k,v in after.items() if k != "project:p-1"})
        self.assertEqual(after["project:p-1"]["revision"], before["project:p-1"]["revision"] + 1)
        version = after["project:p-1"]["integration_contract"]["tasks"]["t-1"]["versions"]["1"]
        self.assertEqual(version["source"]["command_digest"], command.digest())
        self.assertEqual(version["declared_by"], "human-owner")
        self.assertEqual([e.type for e in self.store.read_events("p-1")[offset:]],
                         ["command.received", "project.integration_declared"])
        self.assertEqual(Projection.pending_command_ids(self.store.read_events("p-1"), self.commands()), [])

    def test_supersession_preserves_prior_version_and_task(self):
        self.declare()
        before = self.state()
        self.declare(version=2, reason="Reconfirm target")
        history = self.state()["project:p-1"]["integration_contract"]["tasks"]["t-1"]
        self.assertEqual(history["current_version"], 2)
        self.assertEqual(history["versions"]["1"], before["project:p-1"]["integration_contract"]["tasks"]["t-1"]["versions"]["1"])
        self.assertEqual(self.task(), before["task:t-1"])

    def test_missing_copied_wrong_authority_and_wrong_command_receipts_reject(self):
        for mode in ("missing", "dict", "copy", "foreign", "other-command", "untrusted", "unknown", "marked"):
            with self.subTest(mode=mode):
                command = self.declaration()
                proof = self.input_authority.issue(command, exposure="internal")
                if mode == "missing": proof = None
                elif mode == "dict": proof = {"receipt_id": proof.id}
                elif mode == "copy": proof = replace(proof)
                elif mode == "foreign": proof = InputAuthority(self.input_authority.source_id).issue(command, exposure="internal")
                elif mode == "other-command": proof = self.input_authority.issue(self.declaration(), exposure="internal")
                elif mode in {"untrusted", "unknown"}: proof = self.input_authority.issue(command, exposure=mode)
                elif mode == "marked": proof = self.input_authority.issue(command, exposure="internal", sources=[{"source_id":"external","exposure":"untrusted"}])
                before = self.state()
                result = self.service.handle(command, authenticated_actor_id=command.actor_id, input_receipt=proof)
                self.assertEqual(result.status, "rejected")
                self.assertIn(result.error_code, {"INPUT_CONTEXT_INVALID", "SOURCE_UNVERIFIED"})
                self.assertEqual(self.state(), before)
        self.assertEqual(Projection.pending_command_ids(self.store.read_events("p-1"), self.commands()), [])

    def test_current_human_owner_required_and_actor_mismatch_not_persisted(self):
        for actor in ("a-1", "human-peer", "bootstrap"):
            self.assertEqual(self.submit(self.declaration(actor=actor)).error_code, "PERMISSION_DENIED")
        command = self.declaration()
        before = self.store.read_events("p-1")
        self.assertEqual(self.service.handle(command, authenticated_actor_id="human-peer").error_code, "ACTOR_MISMATCH")
        self.assertEqual(self.store.read_events("p-1"), before)

    def test_project_and_task_revisions_checked_in_writer(self):
        command = self.declaration()
        for changed in (replace(command, expected_revision=command.expected_revision - 1),
                        self.declaration(expected_task_revision=self.task()["revision"] - 1)):
            self.assertEqual(self.submit(changed).error_code, "REVISION_CONFLICT")
        original = self.service._state
        def current(project_id):
            self.assertTrue(self.store.in_transaction)
            return original(project_id)
        with patch.object(self.service, "_state", side_effect=current): self.declare()

    def test_exemption_blocks_declaration_and_required_blocks_legacy_configuration(self):
        self.configure_task_quality(version="explicit-again", exempt=True)
        self.assertEqual(self.submit(self.declaration()).error_code, "INTEGRATION_SCOPE_CONFLICT")
        self.configure_task_quality(version="remove-again", exempt=False)
        self.declare()
        before = self.state()
        for service in (CommandHandler(self.store), TaskQualityService(self.store), self.service):
            for kind in ("task.complete", "task.quality.complete"):
                self.assertEqual(service.handle(self.command(kind,"t-1"), authenticated_actor_id="a-1").error_code, "INTEGRATION_REQUIRED")
            request = self.command("project.task_quality.configure", "p-1", configuration("t-1"), actor="human-owner")
            self.assertEqual(service.handle(request, authenticated_actor_id="human-owner").error_code, "INTEGRATION_SCOPE_CONFLICT")
        self.assertEqual(self.state(), before)

    def test_declaring_does_not_require_author_execution_session(self):
        service = IntegrationContractService(self.store, input_authority=self.input_authority, clock=lambda:self.clock_value)
        self.assertEqual(self.submit(self.declaration(), service=service).status, "accepted")

    def test_paused_project_rejects_declaration(self):
        self.accept(self.command("project.pause","p-1",{"intervention_id":"pause-integration","reason":"pause","impact":"project"},actor="human-owner"))
        self.assertEqual(self.submit(self.declaration()).error_code, "PROJECT_PAUSED")

    def test_original_retry_and_reopened_connection_skip_authority_clock_and_evaluator(self):
        command, result = self.declare()
        events = self.store.read_events("p-1")
        with SQLiteStore.open(self.fixture.db_path) as store:
            service = IntegrationContractService(store, clock=lambda:(_ for _ in ()).throw(AssertionError("clock")))
            with patch.object(service, "_evaluate", side_effect=AssertionError("evaluate")):
                self.assertEqual(service.handle(command, authenticated_actor_id=command.actor_id), result)
                self.assertEqual(service.handle(replace(command,payload={}),authenticated_actor_id=command.actor_id).error_code,"IDEMPOTENCY_CONFLICT")
        self.assertEqual(self.store.read_events("p-1"), events)

    def test_rejected_retry_keeps_original_result_even_after_valid_proof(self):
        command = self.declaration()
        result = self.service.handle(command,authenticated_actor_id=command.actor_id)
        self.assertEqual(result.status,"rejected")
        self.assertEqual(self.submit(command),result)
        self.assertNotIn("integration_contract",self.state()["project:p-1"])

    def test_gate_must_be_entered_before_writer(self):
        command=self.declaration()
        with self.store.transaction():
            with self.assertRaises(RuntimeError): self.submit(command)

    def test_old_handler_refuses_declaration_with_replayable_project_audits(self):
        command=self.declaration()
        result=CommandHandler(self.store).handle(command,authenticated_actor_id=command.actor_id)
        self.assertEqual(result.status,"rejected")
        self.assertEqual([(e.aggregate_type,e.aggregate_id) for e in self.store.read_events("p-1")[-2:]],[("project","p-1")]*2)
        self.assertEqual(Projection.pending_command_ids(self.store.read_events("p-1"),self.commands()),[])

    def test_merge_never_executes_and_distinguishes_missing_stale_and_unavailable(self):
        command=self.merge()
        self.assertEqual(self.service.handle(command,authenticated_actor_id="a-1").error_code,"INTEGRATION_DECLARATION_REQUIRED")
        self.declare()
        for changes, code in (({},"ENFORCEMENT_UNAVAILABLE"),({"declaration_version":2},"INTEGRATION_DECLARATION_STALE"),
                              ({"declaration_digest":"sha256:"+"f"*64},"INTEGRATION_DECLARATION_STALE"),
                              ({"result":"merged"},"INVALID_PAYLOAD")):
            with self.subTest(changes=changes):
                before=self.state(); command=self.merge(**changes)
                with patch.object(self.execution,"dispatch",side_effect=AssertionError("no dispatch")):
                    self.assertEqual(self.service.handle(command,authenticated_actor_id="a-1").error_code,code)
                self.assertEqual(self.state(),before)
        self.assertEqual(Projection.pending_command_ids(self.store.read_events("p-1"),self.commands()),[])

    def test_merge_checks_owner_revision_and_base_legacy_handler_too(self):
        self.declare()
        command=self.merge()
        self.assertEqual(self.service.handle(replace(command,actor_id="a-2"),authenticated_actor_id="a-2").error_code,"PERMISSION_DENIED")
        stale=replace(self.merge(),expected_revision=self.task()["revision"]-1)
        self.assertEqual(self.service.handle(stale,authenticated_actor_id="a-1").error_code,"REVISION_CONFLICT")
        self.assertEqual(CommandHandler(self.store).handle(self.merge(),authenticated_actor_id="a-1").error_code,"ENFORCEMENT_UNAVAILABLE")
    def test_missing_and_foreign_targets_remain_typed_rejections_and_replayable(self):
        for kind in ("project.integration.declare", "git.merge"):
            for target in (None, "nonexistent"):
                with self.subTest(kind=kind, target=target):
                    command = self.declaration() if kind.startswith("project.") else self.merge()
                    command = replace(command, target_id=target)
                    before = self.state()
                    result = self.submit(command)
                    self.assertEqual(result.status, "rejected", result.to_dict())
                    self.assertIn(result.error_code, {"INVALID_PAYLOAD", "INVALID_TARGET"})
                    self.assertEqual(self.state(), before)
        self.assertEqual(Projection.pending_command_ids(self.store.read_events("p-1"), self.commands()), [])

    def test_receipt_does_not_survive_authority_replacement_or_changed_governance_revision(self):
        command = self.declaration()
        receipt = self.input_authority.issue(command, exposure="internal")
        replacement = IntegrationContractService(self.store,
            input_authority=InputAuthority(self.input_authority.source_id), clock=lambda: self.clock_value)
        self.assertEqual(replacement.handle(command, authenticated_actor_id=command.actor_id,
            input_receipt=receipt).error_code, "INPUT_CONTEXT_INVALID")
        # A new intent minted before reconfiguration is checked against writer facts.
        command = self.declaration()
        receipt = self.input_authority.issue(command, exposure="internal")
        from tests.m3.quality_support import quality_governance
        self.configure(quality_governance(version="after-receipt"))
        self.assertEqual(self.service.handle(command, authenticated_actor_id=command.actor_id,
            input_receipt=receipt).error_code, "REVISION_CONFLICT")
        self.assertNotIn("integration_contract", self.state()["project:p-1"])
