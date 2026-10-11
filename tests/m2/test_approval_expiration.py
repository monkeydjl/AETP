"""Expiry is a durable routed outcome; revocation preserves past facts."""

from tests.m2.governance_support import GovernanceCase, policy


class ApprovalExpirationTests(GovernanceCase):
    def tick(self):
        self.assertTrue(callable(getattr(self.service, "tick", None)), "host expiry tick is not implemented")
        return self.service.tick("p-1")

    def test_expiration_escalates_once_and_duplicate_ticks_are_noops(self):
        self.request_approval()
        self.clock_value = 2000
        self.tick()
        row = self.approval()
        self.assertEqual(row["status"], "expired")
        self.assertEqual(row["escalation"]["route"]["type"], "human")
        self.assertEqual(row["escalation"]["notification_level"], "urgent")
        self.assertIn("approval.expired", self.event_types())
        self.assertIn("approval.escalated", self.event_types())
        before = len(self.store.read_events("p-1"))
        self.tick()
        self.assertEqual(len(self.store.read_events("p-1")), before)

    def test_high_expiration_keeps_human_route_and_blocks_related_task(self):
        self.request_approval(risk_level="high")
        self.clock_value = 2000
        self.tick()
        self.assertEqual(self.task()["status"], "blocked")
        self.assertEqual(self.task()["blocked_reason"], "approval_expired")
        self.assertEqual(self.approval()["escalation"]["route"]["required_role"], "human_owner")

    def test_reject_expiration_returns_unactivated_decision_to_review(self):
        self.ready_decision()
        self.request_approval("ap", target=self.service.snapshot("p-1", "decision", "decision-1"),
                              action="decision.activate", arguments={"choice": "A"}, on_expire="reject")
        self.clock_value = 2000
        self.tick()
        self.assertEqual(self.approval("ap")["status"], "expired")
        self.assertEqual(self.approval("ap")["expiration_resolution"]["kind"], "reject")
        self.assertEqual(self.state()["decision:decision-1"]["status"], "reviewing")

    def test_renewal_creates_new_ids_and_stops_at_policy_limit(self):
        original = self.request_approval(on_expire="renew", renew_limit=2)
        identifier = "ap-1"
        for count in (1, 2):
            self.clock_value += 1000
            self.tick()
            expired = self.approval(identifier)
            self.assertEqual(expired["status"], "expired")
            identifier = expired["expiration_resolution"]["next_approval_id"]
            new = self.approval(identifier)
            self.assertEqual(new["renewal_count"], count)
            for field in ("target", "scope", "arguments", "requested_by", "executor", "policy_version"):
                self.assertEqual(new[field], original[field])
        self.clock_value += 1000
        self.tick()
        final = self.approval(identifier)
        self.assertEqual(final["expiration_resolution"]["kind"], "escalate")
        self.assertEqual(final["expiration_resolution"]["reason"], "renewal_limit")
        self.assertEqual(sum(key.startswith("approval:") for key in self.state()), 3)

    def test_stale_target_turns_renew_into_visible_escalation(self):
        self.request_approval(on_expire="renew")
        self.eaccept(self.command("execution.report", "t-1", {**self.fence(), "summary": "Changed Task revision"}), session=self.session)
        self.clock_value = 2000
        self.tick()
        self.assertEqual(self.approval()["expiration_resolution"]["kind"], "escalate")
        self.assertEqual(sum(key.startswith("approval:") for key in self.state()), 1)

    def test_approved_but_unused_authorization_also_expires(self):
        self.request_approval()
        self.accept(self.grant())
        self.clock_value = 2000
        self.tick()
        self.assertEqual(self.approval()["status"], "expired")

    def test_windowed_veto_preserves_granted_history_and_records_impact(self):
        self.configure(policy("gov-2", approval="delegated", delegate="a-2", revocable_within_ms=100))
        self.request_approval()
        self.accept(self.grant())
        granted = next(event.to_json() for event in self.store.read_events("p-1") if event.type == "approval.granted")
        self.clock_value = 1099
        self.accept(self.command("approval.revoke", "ap-1", {"reason": "Human found a missing constraint", "mode": "veto"}, actor="human-owner"))
        row = self.approval()
        self.assertEqual(row["status"], "revoked")
        self.assertFalse(row["impact"]["external_effects_undone"])
        self.assertIn("approval.escalated", self.event_types())
        self.assertIn(granted, [event.to_json() for event in self.store.read_events("p-1")])

    def test_delegated_veto_has_a_real_deadline_and_normal_safety_revoke_is_explicit(self):
        self.configure(policy("gov-2", approval="delegated", delegate="a-2", revocable_within_ms=100))
        self.request_approval()
        self.accept(self.grant())
        self.clock_value = 1100
        self.reject(self.command("approval.revoke", "ap-1", {"reason": "Too late for veto", "mode": "veto"}, actor="human-owner"), "VETO_WINDOW_CLOSED")
        self.accept(self.command("approval.revoke", "ap-1", {"reason": "Explicit later safety revocation", "mode": "safety"}, actor="human-owner"))
        self.assertEqual(self.approval()["status"], "revoked")

    def test_agent_cannot_issue_internal_expiry_or_human_revoke(self):
        self.request_approval()
        self.reject(self.command("approval.expire", "ap-1"), "PERMISSION_DENIED")
        self.accept(self.grant())
        self.reject(self.command("approval.revoke", "ap-1", {"reason": "Agent claims owner", "mode": "safety"}), "PERMISSION_DENIED")

    def test_revocation_invalidates_active_authority_without_undoing_decision_history(self):
        self.ready_decision()
        self.approve_decision()
        self.accept(self.command("decision.activate", "decision-1", {"approval_id": "decision-ap", "arguments": {"choice": "A"}}))
        self.accept(self.command("approval.revoke", "decision-ap", {"reason": "New contradictory evidence", "mode": "safety"}, actor="human-owner"))
        decision = self.state()["decision:decision-1"]
        self.assertEqual(decision["status"], "active")
        self.assertEqual(decision["authorization_status"], "revoked")
        self.assertTrue(self.approval("decision-ap")["impact"]["replanning_required"])
