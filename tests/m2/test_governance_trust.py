"""Ingress capabilities and retained provenance cannot be replaced by Agent claims."""

from dataclasses import replace

from tests.m2.governance_support import GovernanceCase, InputAuthority


class GovernanceTrustTests(GovernanceCase):
    def completed_source(self, *, trusted=False):
        self.request_approval(trusted=trusted)
        if not trusted:
            self.accept(self.grant())
        action = self.request_document()
        return self.execution.dispatch("p-1", action["id"], session=self.session)

    def restore_request(self, *, trusted_source=False):
        action = self.completed_source(trusted=trusted_source)
        result = self.eaccept(self.command("checkpoint.create", "t-1", {**self.fence(),
            "context_snapshot": "Source document may contain external material",
            "remaining_work": ["Restore the document"]}), session=self.session)
        effect = next(event for event in self.store.read_events("p-1") if event.id == result.event_ids[-1])
        checkpoint = self.state()[f"checkpoint:{effect.aggregate_id}"]
        self.eaccept(self.command("lease.revoke", "t-1", {**self.fence(), "reason": "handoff"}))
        self.execution.recover("p-1")
        self.eaccept(self.command("task.requeue", "t-1"))
        self.session = None
        self.eaccept(self.command("task.claim", "t-1"))
        result, self.session = self.execution.start_session(
            self.command("execution.start", "t-1", self.fence()), authenticated_actor_id="a-1")
        self.assertEqual(result.status, "accepted", result.to_dict())
        row = self.request_approval("restore-ap", trusted=True, action="document.restore",
            arguments={**self.fence(), "document": {"checkpoint_id": checkpoint["id"]}})
        return row, action, checkpoint

    def test_trusted_append_receipt_preserves_untrusted_source_action(self):
        action = self.completed_source()
        row = self.request_approval("append-ap", trusted=True, action="document.append",
            arguments={**self.fence(), "document": {"source_action_id": action["id"], "text": "Appendix"}})
        self.assertEqual((row["status"], row["risk_level"]), ("pending", "medium"))
        self.assertTrue(row["source"]["untrusted_input"])
        inherited = row["source"]["derived_sources"][0]
        self.assertEqual((inherited["type"], inherited["id"]), ("action", action["id"]))
        self.assertEqual(inherited["source"], action["authorization"]["source"])

    def test_trusted_append_of_trusted_document_can_still_use_auto_approval(self):
        action = self.completed_source(trusted=True)
        row = self.request_approval("append-ap", trusted=True, action="document.append",
            arguments={**self.fence(), "document": {"source_action_id": action["id"], "text": "Appendix"}})
        self.assertEqual((row["status"], row["risk_level"]), ("approved", "low"))
        self.assertFalse(row["source"]["untrusted_input"])

    def test_restore_preserves_source_action_and_checkpoint_context_provenance(self):
        row, action, checkpoint = self.restore_request()
        self.assertEqual((row["status"], row["risk_level"]), ("pending", "medium"))
        derived = row["source"]["derived_sources"]
        self.assertEqual([(entry["type"], entry["id"]) for entry in derived],
                         [("action", action["id"]), ("checkpoint", checkpoint["id"])])
        self.assertTrue(all(entry["untrusted_input"] for entry in derived))
        self.assertEqual(derived[1]["source"], checkpoint["snapshot"]["context_snapshot"]["source"])

    def test_restore_with_trusted_document_still_inherits_untrusted_checkpoint_context(self):
        row, _, _ = self.restore_request(trusted_source=True)
        self.assertEqual((row["status"], row["risk_level"]), ("pending", "medium"))
        self.assertEqual([entry["untrusted_input"] for entry in row["source"]["derived_sources"]], [False, True])

    def test_trusted_low_risk_uses_a_recorded_deterministic_system_approval(self):
        row = self.request_approval(trusted=True)
        self.assertEqual(row["status"], "approved")
        self.assertEqual(row["approved_by"]["type"], "system")
        self.assertNotEqual(row["approved_by"]["id"], "a-1")
        self.assertEqual(row["policy_version"], "gov-1")
        self.assertEqual(row["scope"]["action"], "document.write")
        self.assertFalse(row["source"]["untrusted_input"])
        self.assertIn("approval.granted", self.event_types())

    def test_receipt_copy_wrong_authority_and_different_command_are_rejected(self):
        command = self.request_command()
        receipt = self.input_authority.issue(command, exposure="trusted")
        wrong = InputAuthority("fixture-input-gateway").issue(command, exposure="trusted")
        for given in (replace(receipt), wrong):
            with self.subTest(receipt=type(given).__name__):
                result = self.service.handle(command, authenticated_actor_id="a-1", input_receipt=given)
                self.assertEqual(result.error_code, "INPUT_CONTEXT_INVALID")
                # Typed rejection is idempotent; a new business request is needed.
                command = self.request_command("next-" + str(self.counter))
        result = self.service.handle(command, authenticated_actor_id="a-1", input_receipt=receipt)
        self.assertEqual(result.error_code, "INPUT_CONTEXT_INVALID")

    def test_attested_untrusted_source_cannot_be_cleared_by_top_level_trusted_label(self):
        command = self.request_command()
        receipt = self.input_authority.issue(command, exposure="trusted", sources=(
            {"source_id": "web-evidence", "exposure": "untrusted"},))
        result = self.service.handle(command, authenticated_actor_id="a-1", input_receipt=receipt)
        self.assertEqual(result.status, "accepted", result.to_dict())
        row = self.approval()
        self.assertTrue(row["source"]["untrusted_input"])
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["source"]["sources"][0]["source_id"], "web-evidence")

    def test_medium_untrusted_input_escalates_to_human_and_review_keeps_source(self):
        before = self.request_approval(risk_level="medium")["source"]
        self.assertEqual(self.approval()["risk_level"], "high")
        self.reject(self.grant(), "PERMISSION_DENIED")
        self.accept(self.grant(actor="human-owner"))
        self.assertEqual(self.approval()["source"], before)

    def test_successful_request_retry_does_not_require_new_receipt_or_read_new_clock(self):
        command = self.request_command()
        receipt = self.input_authority.issue(command, exposure="internal")
        result = self.service.handle(command, authenticated_actor_id="a-1", input_receipt=receipt)
        self.assertEqual(result.status, "accepted", result.to_dict())
        before = len(self.store.read_events("p-1"))
        def no_clock():
            raise AssertionError("idempotent retry must not create a new approval intent")
        self.service.clock = no_clock
        self.assertEqual(self.service.handle(command, authenticated_actor_id="a-1"), result)
        self.assertEqual(len(self.store.read_events("p-1")), before)


class LegacyDocumentSourceTests(GovernanceCase):
    def configure(self, value=None):
        # Deliberately create the first document before governance exists.
        pass

    def test_append_of_legacy_document_without_source_is_conservatively_untrusted(self):
        result = self.eaccept(self.command("tool.request", "t-1", {**self.fence(),
            "operation": "document.write", "arguments": {"content": "Legacy document"}}), session=self.session)
        effect = next(event for event in self.store.read_events("p-1") if event.id == result.event_ids[-1])
        action = self.execution.dispatch("p-1", effect.aggregate_id, session=self.session)
        self.assertNotIn("authorization", action)
        super().configure()
        row = self.request_approval("legacy-append", trusted=True, action="document.append",
            arguments={**self.fence(), "document": {"source_action_id": action["id"], "text": "Addition"}})
        self.assertEqual((row["status"], row["risk_level"]), ("pending", "medium"))
        self.assertTrue(row["source"]["derived_sources"][0]["untrusted_input"])
