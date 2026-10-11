"""Independent-review findings and receipt/report integrity regressions."""

import copy
from dataclasses import replace

from aetp.acceptance.contracts import report_id
from aetp.acceptance.records import evaluate
from aetp.collaboration.policy import PolicyViolation
from aetp.core.projection import Projection
from aetp.domain.models import Command, ModelValidationError
from tests.m3.verification_support import VerificationCase


class VerificationIntegrityTests(VerificationCase):
    def test_reserved_report_id_cannot_be_claimed_before_request(self):
        identifier = report_id("p-1", "v-1")
        self.reject(self.command("artifact.submit", identifier, {"task_id": "t-1", "type": "document", "content": "collision"}),
                    "ARTIFACT_ID_RESERVED")

    def test_report_id_cannot_be_stolen_after_grant(self):
        self.capture()
        self.request_verification()
        identifier = report_id("p-1", "v-1")
        self.reject(self.command("artifact.submit", identifier, {"task_id": "t-1", "type": "document", "content": "collision"}),
                    "ARTIFACT_ID_RESERVED")
        result = self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.assertEqual(result["result"], "PASSED")

    def test_null_target_digest_cannot_mean_use_latest(self):
        self.capture()
        command = self.verification_command(artifact_digest=None)
        proof = self.input_authority.issue(command, exposure="internal")
        result = self.service.handle(command, authenticated_actor_id="a-2", session=self.qa_session, input_receipt=proof)
        self.assertEqual(result.error_code, "INVALID_PAYLOAD")
        self.assertNotIn("verification:v-1", self.state())

    def test_legacy_source_flag_cannot_create_auto_verification_authority(self):
        self.accept(self.command("artifact.submit", "doc-1", {"task_id": "t-1", "type": "document",
            "content": '{"scope":"local","recovery":true}'}))
        events = self.store.read_events("p-1")
        original = events[-1]
        payload = copy.deepcopy(original.payload)
        payload["source"]["untrusted_input"] = False
        payload["source"]["kind"] = "runtime_document_capture"
        events[-1] = replace(original, payload=payload)
        # Preserve legacy Replay semantics; only the new auto boundary is hardened.
        state = Projection.rebuild(events)
        command = self.verification_command()
        proof = self.input_authority.issue(command, exposure="internal")
        context = {"channel": "agent", "input_proof": self.input_authority.verify(command, proof),
                   "runner": self.service._runner.descriptor,
                   "live": self.execution.validation_context("p-1", self.qa_session)}
        with self.assertRaises(PolicyViolation) as failure:
            evaluate(command, state, self.clock_value, context)
        self.assertEqual(failure.exception.code, "SOURCE_UNVERIFIED")

    def test_legacy_fact_cannot_smuggle_capture_creation_proof(self):
        artifact = self.capture()
        self.assertIn("capture_origin", artifact)
        original = self.store.read_events("p-1")[-1]
        events = self.store.read_events("p-1")[:-2]
        # A source mapping is extensible in the old schema, but top-level
        # creator proof must not be accepted by that old Artifact model.
        forged = replace(original, type="artifact.created", sequence=len(events) + 1, payload=artifact)
        with self.assertRaises(ModelValidationError):
            Projection.rebuild([*events, forged])

    def test_report_and_terminal_share_one_context_and_one_receipt(self):
        self.capture()
        self.request_verification()
        self.service.dispatch("p-1", "v-1", session=self.qa_session)
        events = self.store.read_events("p-1")
        report = events[-2]
        terminal = events[-1]
        self.assertEqual(report.type, "artifact.verification_reported")
        self.assertEqual(terminal.type, "verification.finished")
        payload = copy.deepcopy(terminal.payload)
        payload["context"]["channel"] = "recovery"
        with self.assertRaises(ModelValidationError):
            Projection.rebuild([*events[:-1], replace(terminal, payload=payload)])

    def test_resealed_host_actor_cannot_become_agent_report(self):
        self.capture()
        self.request_verification()
        self.service.dispatch("p-1", "v-1", session=self.qa_session)
        events = self.store.read_events("p-1")
        command = Command.from_dict(events[-1].payload["command"])
        forged = replace(command, actor_id="a-2")
        for index in (-2, -1):
            payload = copy.deepcopy(events[index].payload)
            payload["command"] = forged.to_dict()
            events[index] = replace(events[index], payload=payload)
        events[-3] = replace(events[-3], payload={"command_type": forged.type, "request_digest": forged.digest()})
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(events)

    def test_report_bytes_cannot_be_replaced_with_self_certified_pass(self):
        self.capture('{"scope":"public","recovery":true}')
        self.request_verification()
        self.service.dispatch("p-1", "v-1", session=self.qa_session)
        events = self.store.read_events("p-1")
        payload = copy.deepcopy(events[-2].payload)
        from aetp.collaboration.policy import digest_text
        payload["record"]["content"] = '{"result":"PASSED"}'
        payload["record"]["content_digest"] = digest_text(payload["record"]["content"])
        with self.assertRaises(ModelValidationError):
            Projection.rebuild([*events[:-2], replace(events[-2], payload=payload), events[-1]])

    def test_incomplete_report_stays_pending_and_blocks_unrelated_next_fact(self):
        self.capture()
        self.request_verification()
        self.service.dispatch("p-1", "v-1", session=self.qa_session)
        events, commands = self.store.read_events("p-1"), self.commands()
        prefix = events[:-1]
        self.assertEqual(Projection.pending_command_ids(prefix, commands), [events[-1].causation_id])
        projection = Projection()
        for event in prefix:
            projection.apply(event)
        self.assertIsNone(projection.state["verification:v-1"]["result"])
        before, sequence = projection.state, projection.last_sequence
        unrelated = replace(events[-3], id="unrelated-receipt", causation_id="unrelated", sequence=sequence + 1)
        with self.assertRaises(ModelValidationError):
            projection.apply(unrelated)
        self.assertEqual((projection.state, projection.last_sequence), (before, sequence))
        projection.apply(events[-1])
        self.assertEqual(projection.state["verification:v-1"]["result"], "PASSED")

    def test_missing_receipt_and_duplicate_terminal_cannot_advance(self):
        self.capture()
        self.request_verification()
        self.service.dispatch("p-1", "v-1", session=self.qa_session)
        events = self.store.read_events("p-1")
        no_receipt = [*events[:-3], *events[-2:]]
        no_receipt = [replace(event, sequence=index) for index, event in enumerate(no_receipt, 1)]
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(no_receipt)
        duplicate = replace(events[-1], id="duplicate-terminal", sequence=len(events) + 1)
        with self.assertRaises(ModelValidationError):
            Projection.rebuild([*events, duplicate])

    def test_persisted_case_command_cannot_disagree_with_resealed_event(self):
        self.capture()
        self.request_verification()
        events, commands = self.store.read_events("p-1"), self.commands()
        command = Command.from_dict(events[-1].payload["command"])
        payload = copy.deepcopy(command.payload)
        payload["cases"][0]["equals"] = "public"
        forged = replace(command, payload=payload)
        commands = [forged if item.id == command.id else item for item in commands]
        with self.assertRaises(ModelValidationError):
            Projection.pending_command_ids(events, commands)
