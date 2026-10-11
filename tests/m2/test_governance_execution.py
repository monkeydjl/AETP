"""Approve actual fixed document calls, then recheck at the final write boundary."""

from unittest.mock import patch

from tests.m2.governance_support import GovernanceCase, policy


class GovernedExecutionTests(GovernanceCase):
    def approve(self, **kwargs):
        self.request_approval(**kwargs)
        self.accept(self.grant(actor="human-owner" if kwargs.get("risk_level") == "critical" else "a-2"))

    def test_configured_governance_requires_approval_at_tool_request(self):
        self.ereject(self.command("tool.request", "t-1", {**self.fence(), "operation": "document.write",
                     "arguments": {"content": "Unapproved body"}}), "APPROVAL_REQUIRED", session=self.session)
        self.assertFalse(any(key.startswith("action:") for key in self.state()))

    def test_approved_document_executes_once_and_keeps_source_and_scope(self):
        self.approve()
        action = self.request_document()
        self.assertEqual(action["authorization"]["approval_id"], "ap-1")
        self.assertTrue(action["authorization"]["source"]["untrusted_input"])
        result = self.execution.dispatch("p-1", action["id"], session=self.session)
        self.assertEqual((result["status"], result["dispatch_count"]), ("completed", 1))
        self.assertEqual(self.workspace.query(result)["status"], "confirmed")
        before = len(self.store.read_events("p-1"))
        self.assertEqual(self.execution.dispatch("p-1", action["id"], session=self.session), result)
        self.assertEqual(len(self.store.read_events("p-1")), before)

    def test_approval_does_not_authorize_changed_document_arguments(self):
        self.approve()
        self.ereject(self.command("tool.request", "t-1", {**self.fence(), "operation": "document.write",
            "arguments": {"content": "Different body"}, "approval_id": "ap-1"}), "APPROVAL_STALE", session=self.session)

    def test_task_revision_changed_since_approval_is_rejected(self):
        self.approve()
        self.eaccept(self.command("execution.report", "t-1", {**self.fence(), "summary": "A new Task observation"}), session=self.session)
        self.ereject(self.command("tool.request", "t-1", {**self.fence(), "operation": "document.write",
            "arguments": {"content": "Scope and Recovery"}, "approval_id": "ap-1"}), "APPROVAL_STALE", session=self.session)

    def test_client_cannot_reuse_lower_risk_approval_for_a_critical_flag(self):
        self.approve()
        self.ereject(self.command("tool.request", "t-1", {**self.fence(), "operation": "document.write",
            "arguments": {"content": "Scope and Recovery"}, "approval_id": "ap-1", "risk_level": "critical"}),
            "APPROVAL_REQUIRED", session=self.session)

    def test_owner_approved_critical_label_still_has_only_fixed_document_capability(self):
        self.approve(risk_level="critical")
        result = self.eaccept(self.command("tool.request", "t-1", {**self.fence(), "operation": "document.write",
            "arguments": {"content": "Scope and Recovery"}, "approval_id": "ap-1", "risk_level": "critical"}), session=self.session)
        self.assertEqual(result.status, "accepted")
        self.ereject(self.command("tool.request", "t-1", {**self.fence(), "operation": "shell.run",
            "arguments": {"content": "Scope and Recovery"}, "approval_id": "ap-1", "risk_level": "critical"}),
            "APPROVAL_REQUIRED", session=self.session)

    def test_revocation_after_queue_prevents_provider_write(self):
        self.approve()
        action = self.request_document()
        self.accept(self.command("approval.revoke", "ap-1", {"reason": "Cancel authorization", "mode": "safety"}, actor="human-owner"))
        with self.assertRaisesRegex(Exception, "APPROVAL_REQUIRED"):
            self.execution.dispatch("p-1", action["id"], session=self.session)
        self.assertEqual(self.state()[f"action:{action['id']}"]["dispatch_count"], 0)
        self.assertEqual(list(self.workspace.root.rglob("*.json")), [])

    def test_policy_change_after_queue_prevents_provider_write(self):
        self.approve()
        action = self.request_document()
        self.configure(policy("gov-2"))
        with self.assertRaisesRegex(Exception, "APPROVAL_STALE"):
            self.execution.dispatch("p-1", action["id"], session=self.session)
        self.assertEqual(self.state()[f"action:{action['id']}"]["dispatch_count"], 0)

    def test_expired_approval_cannot_dispatch_even_without_a_tick(self):
        self.approve()
        action = self.request_document()
        self.clock_value = 2000
        with self.assertRaisesRegex(Exception, "APPROVAL_EXPIRED"):
            self.execution.dispatch("p-1", action["id"], session=self.session)
        self.assertEqual(self.state()[f"action:{action['id']}"]["dispatch_count"], 0)

    def test_write_callback_rechecks_a_revocation_after_in_flight_is_recorded(self):
        self.approve()
        action = self.request_document()
        real_write = self.workspace.write
        def revoke_then_write(record, authorize):
            self.assertFalse(self.store.in_transaction)
            self.accept(self.command("approval.revoke", "ap-1", {"reason": "Revoke at call boundary", "mode": "safety"}, actor="human-owner"))
            return real_write(record, authorize)
        with patch.object(self.workspace, "write", side_effect=revoke_then_write):
            result = self.execution.dispatch("p-1", action["id"], session=self.session)
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["dispatch_count"], 1)
        self.assertEqual(list(self.workspace.root.rglob("*.json")), [])
        self.assertEqual(self.approval()["impact"]["actions"][0]["status"], "in_flight")

    def test_completed_external_result_survives_later_revocation(self):
        self.approve()
        action = self.request_document()
        completed = self.execution.dispatch("p-1", action["id"], session=self.session)
        self.accept(self.command("approval.revoke", "ap-1", {"reason": "Only future actions are stopped", "mode": "safety"}, actor="human-owner"))
        self.assertEqual(self.state()[f"action:{action['id']}"]["result"], completed["result"])
        self.assertEqual(self.workspace.query(completed)["status"], "confirmed")
        self.assertFalse(self.approval()["impact"]["external_effects_undone"])

    def test_denied_or_other_actors_approval_is_not_a_session_capability(self):
        self.request_approval()
        self.accept(self.command("approval.deny", "ap-1", {"reason": "No"}, actor="a-2"))
        self.ereject(self.command("tool.request", "t-1", {**self.fence(), "operation": "document.write",
            "arguments": {"content": "Scope and Recovery"}, "approval_id": "ap-1"}), "APPROVAL_REQUIRED", session=self.session)
