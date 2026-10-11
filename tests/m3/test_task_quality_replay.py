"""Pure replay, compound causality and failure atomicity of the quality cursor."""

import copy
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from aetp.core.projection import Projection
from aetp.core.runtime import RuntimeRecovery
from aetp.domain.models import Command, Event, ModelValidationError
from aetp.quality.contracts import COMMAND_AGGREGATES
from tests.m3.quality_support import QualityCase


GUARDS = (
    "aetp.acceptance.runner.FixedJsonRunner.run", "aetp.acceptance.runner.FixedJsonRunner.__init__",
    "aetp.quality.service.TaskQualityService.handle", "aetp.acceptance.service.AcceptanceService.dispatch",
    "aetp.runtime.document.DocumentRuntime.register", "aetp.runtime.document.DocumentRuntime.lookup",
    "aetp.runtime.service.ExecutionService.validation_context", "aetp.runtime.service.ExecutionService.recover",
    "aetp.runtime.service.ExecutionService.dispatch", "aetp.governance.trust.InputAuthority.issue",
    "aetp.governance.trust.InputAuthority.verify", "aetp.workspace.documents.DocumentWorkspace.write",
    "aetp.workspace.documents.DocumentWorkspace.query", "pathlib.Path.read_bytes", "pathlib.Path.read_text",
    "time.time_ns", "subprocess.Popen", "socket.socket",
)


class QualityReplayTests(QualityCase):
    def setUp(self):
        super().setUp()
        self.verified_quality()
        self.quality_complete()
        self.qcall("task.quality.complete", actor="a-2")  # Retain a real quality rejection audit.
        self.events, self.persisted = self.store.read_events("p-1"), self.commands()

    def atomic_rejection(self, index, altered):
        projection = Projection()
        for event in self.events[:index]:
            projection.apply(event)
        before, cursor = projection.state, projection._quality_cursor
        with self.assertRaises(ModelValidationError):
            projection.apply(altered)
        self.assertEqual(projection.state, before)
        self.assertEqual(projection.last_sequence, index)
        self.assertIs(projection._quality_cursor, cursor)
        for event in self.events[index:]:
            projection.apply(event)
        self.assertEqual(projection.state, self.state())

    def index(self, kind):
        return next(index for index, event in enumerate(self.events) if event.type == kind)

    def test_every_prefix_and_recovery_are_pure_with_zero_external_calls(self):
        expected = self.state()
        recovery = RuntimeRecovery.open(self.fixture.db_path)
        self.addCleanup(recovery.close)
        with ExitStack() as stack:
            guards = [stack.enter_context(patch(target, side_effect=AssertionError(target))) for target in GUARDS]
            cursor = Projection()
            for count, event in enumerate(self.events, 1):
                cursor.apply(event)
                self.assertEqual(Projection.rebuild(self.events[:count]), cursor.state)
                known = {row.causation_id for row in self.events[:count] if row.type == "command.received"}
                Projection.pending_command_ids(self.events[:count], [cmd for cmd in self.persisted if cmd.id in known])
            self.assertEqual(cursor.state, expected)
            self.assertEqual(recovery.rebuild_project("p-1"), expected)
            self.assertEqual(recovery.reconcile_pending("p-1"), [])
            self.assertTrue(all(guard.call_count == 0 for guard in guards))

    def test_receipt_revision_is_validated_before_cursor_publication(self):
        for index, event in enumerate(self.events):
            if event.type == "command.received" and event.payload["command_type"] in COMMAND_AGGREGATES:
                with self.subTest(command=event.payload["command_type"]):
                    self.atomic_rejection(index, replace(event, aggregate_revision=event.aggregate_revision + 1))

    def test_receipt_digest_must_be_a_real_canonical_digest(self):
        index = self.index("task.quality_enrolled") - 1
        receipt = self.events[index]
        for value in ("", None, "g" * 64, "sha256:wrong"):
            with self.subTest(value=value):
                self.atomic_rejection(index, replace(receipt, payload={**receipt.payload, "request_digest": value}))

    def test_quality_rejection_requires_a_typed_error(self):
        index = len(self.events) - 1
        for value in ({}, {"error": None}, {"error": {"code": ""}}):
            with self.subTest(payload=value):
                self.atomic_rejection(index, replace(self.events[index], payload=value))

    def test_missing_quality_receipt_cannot_be_hidden_by_renumbering(self):
        index = self.index("task.ready_for_review") - 1
        altered = [replace(event, sequence=count) for count, event in enumerate(
            [*self.events[:index], *self.events[index + 1:]], 1)]
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(altered)

    def test_effect_index_count_address_and_record_are_recomputed(self):
        index = self.index("task.ready_for_review")
        event = self.events[index]
        record = copy.deepcopy(event.payload["record"])
        record["status"] = "completed"
        altered = [replace(event, aggregate_id="qa-task"),
                   replace(event, payload={**event.payload, "effect_index": True}),
                   replace(event, payload={**event.payload, "effect_count": 2}),
                   replace(event, payload={**event.payload, "record": record})]
        for item in altered:
            with self.subTest(event=item.to_json()[:100]):
                self.atomic_rejection(index, item)

    def test_resealed_command_cannot_change_receipt_intent(self):
        index = self.index("task.ready_for_review")
        event = self.events[index]
        command = Command.from_dict(event.payload["command"])
        changed = replace(command, payload={**command.payload, "summary": "Different submitted intent"})
        context = copy.deepcopy(event.payload["context"])
        context["input_proof"]["command_digest"] = changed.digest()
        from aetp.quality.records import evaluate
        state = Projection.rebuild(self.events[:index])
        record = evaluate(changed, state, event.payload["observed_at_ms"], context)[0][3]
        self.atomic_rejection(index, replace(event, payload={**event.payload,
            "command": changed.to_dict(), "context": context, "record": record}))

    def test_review_child_facts_cannot_be_omitted_or_replaced(self):
        index = self.index("review.quality_requested")
        event = self.events[index]
        self.atomic_rejection(index, replace(event, aggregate_id="foreign-review"))
        altered = [replace(row, sequence=count) for count, row in enumerate(
            [*self.events[:index], *self.events[index + 1:]], 1)]
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(altered)

    def test_intermediate_completion_cannot_trust_a_resealed_terminal_copy(self):
        index = self.index("task.integration_exempted")
        event = self.events[index]
        record = copy.deepcopy(event.payload["record"])
        record["completion_pending"]["terminal_record"]["lease"]["revoked"] = False
        from aetp.collaboration.policy import digest_value
        record["completion_pending"]["terminal_digest"] = digest_value(record["completion_pending"]["terminal_record"])
        self.atomic_rejection(index, replace(event, payload={**event.payload, "record": record}))

    def test_terminal_requires_exact_prevalidated_context_and_next_revision(self):
        index = self.index("task.completed")
        event = self.events[index]
        context = copy.deepcopy(event.payload["context"])
        context["runner"]["environment"]["python_version"] = "unrelated"
        for altered in (replace(event, payload={**event.payload, "context": context}),
                        replace(event, aggregate_revision=event.aggregate_revision - 1),
                        replace(event, payload={**event.payload, "old_task": self.events[index - 1].payload["record"]})):
            self.atomic_rejection(index, altered)

    def test_no_interleaving_is_allowed_between_exemption_and_terminal(self):
        index = self.index("task.completed")
        receipt = Event("interleaved-receipt", "p-1", self.events[index].sequence, "command.received", "task", "other",
            0, "interleaved-command", "interleaved", {"command_type": "task.create", "request_digest": "a" * 64})
        self.atomic_rejection(index, receipt)

    def test_duplicate_terminal_and_conflicting_redelivery_are_rejected(self):
        projection = Projection()
        for event in self.events:
            projection.apply(event)
            projection.apply(event)
        final = self.events[self.index("task.completed")]
        before = projection.state
        with self.assertRaises(ModelValidationError):
            projection.apply(replace(final, id="second-terminal", sequence=projection.last_sequence + 1))
        with self.assertRaises(ModelValidationError):
            projection.apply(replace(final, aggregate_revision=final.aggregate_revision + 1))
        self.assertEqual(projection.state, before)

