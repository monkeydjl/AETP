"""Pure Replay guards and atomic receipt validation for Verification history."""

from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from aetp.acceptance.runner import FixedJsonRunner
from aetp.acceptance.service import AcceptanceService
from aetp.core.projection import Projection
from aetp.core.runtime import RuntimeRecovery
from aetp.domain.models import ModelValidationError
from aetp.governance.trust import InputAuthority
from aetp.runtime.document import DocumentRuntime
from aetp.runtime.service import ExecutionService
from aetp.workspace.documents import DocumentWorkspace
from tests.m3.verification_support import VerificationCase


class VerificationReplayTests(VerificationCase):
    def setUp(self):
        super().setUp()
        self.capture()
        self.request_verification()
        self.service.dispatch("p-1", "v-1", session=self.qa_session)

    def test_events_and_command_recovery_never_run_or_read_external_content(self):
        events, commands, expected = self.store.read_events("p-1"), self.commands(), self.state()
        recovery = RuntimeRecovery.open(self.fixture.db_path)
        self.addCleanup(recovery.close)
        guards = [(FixedJsonRunner, "run"), (FixedJsonRunner, "__init__"), (DocumentRuntime, "register"),
                  (DocumentWorkspace, "write"), (DocumentWorkspace, "query"), (InputAuthority, "issue"),
                  (AcceptanceService, "dispatch"), (AcceptanceService, "recover_verifications"),
                  (ExecutionService, "dispatch"), (ExecutionService, "recover"), (Path, "read_bytes")]
        with ExitStack() as stack:
            for target, method in guards:
                stack.enter_context(patch.object(target, method, side_effect=AssertionError(f"Replay called {method}")))
            self.assertEqual(Projection.rebuild(events), expected)
            self.assertEqual(Projection.pending_command_ids(events, commands), [])
            self.assertEqual(recovery.rebuild_project("p-1"), expected)
            self.assertEqual(recovery.reconcile_pending("p-1"), [])

    def test_receipt_revision_is_checked_before_any_effect(self):
        events = self.store.read_events("p-1")
        for index, event in enumerate(events):
            if event.type != "command.received" or event.payload["command_type"] not in {
                    "artifact.capture", "verification.request", "verification.dispatch", "verification.record"}:
                continue
            with self.subTest(command_type=event.payload["command_type"]):
                forged = replace(event, aggregate_revision=event.aggregate_revision + 1)
                projection = Projection()
                for prefix in events[:index]:
                    projection.apply(prefix)
                before = projection.state
                with self.assertRaises(ModelValidationError):
                    projection.apply(forged)
                self.assertEqual(projection.state, before)
                self.assertEqual(projection.last_sequence, event.sequence - 1)
                projection.apply(event)
                for later in events[index + 1:]:
                    projection.apply(later)
                self.assertEqual(projection.state, self.state())

    def test_exact_redelivery_does_not_consume_a_second_grant(self):
        events = self.store.read_events("p-1")
        projection = Projection()
        for event in events:
            projection.apply(event)
            projection.apply(event)
        self.assertEqual(projection.state, self.state())
        self.assertEqual(projection.state["verification:v-1"]["action"]["dispatch_count"], 1)
