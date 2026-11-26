"""Decision content versions survive governance state changes and retain source."""


from tests.m2.governance_support import GovernanceCase


class GovernedDecisionTests(GovernanceCase):
    def test_lifecycle_keeps_proposal_digest_and_uses_separate_state_cas(self):
        original = self.ready_decision()
        target = self.service.snapshot("p-1", "decision", "decision-1")
        self.assertEqual((target["revision_kind"], target["revision"]), ("proposal", 0))
        self.assertEqual(target["content_digest"], original["content_digest"])
        approved = self.approve_decision()
        self.assertEqual(approved["status"], "approved")
        self.assertGreater(approved["revision"], target["revision"])
        self.accept(self.command("decision.activate", "decision-1", {"approval_id": "decision-ap", "arguments": {"choice": "A"}}))
        active = self.state()["decision:decision-1"]
        self.assertEqual(active["status"], "active")
        for field in ("content_digest", "source", "choice", "alternatives", "reasoning", "minority_opinions"):
            self.assertEqual(active[field], original[field])

    def test_self_review_and_skipped_stages_do_not_establish_authority(self):
        self.propose()
        self.reject(self.command("decision.review", "decision-1", {"feedback": "Self checked"}), "SELF_REVIEW")
        self.reject(self.command("decision.submit", "decision-1"), "INVALID_TRANSITION")
        self.reject(self.command("decision.activate", "decision-1", {"approval_id": "missing", "arguments": {"choice": "A"}}), "INVALID_TRANSITION")

    def test_activation_rechecks_arguments_executor_and_current_state_revision(self):
        self.ready_decision()
        self.approve_decision()
        body = {"approval_id": "decision-ap", "arguments": {"choice": "A"}}
        self.reject(self.command("decision.activate", "decision-1", {**body, "arguments": {"choice": "B"}}), "APPROVAL_STALE")
        self.reject(self.command("decision.activate", "decision-1", body, actor="a-2"), "PERMISSION_DENIED")
        self.reject(self.command("decision.activate", "decision-1", body, revision=0), "REVISION_CONFLICT")
        self.accept(self.command("decision.activate", "decision-1", body))

    def test_new_superseding_proposal_cannot_use_original_approval(self):
        original = self.ready_decision()
        self.approve_decision()
        self.ready_decision("replacement", supersedes={"id": "decision-1", "digest": original["content_digest"]})
        self.reject(self.command("decision.approve", "replacement", {"approval_id": "decision-ap", "arguments": {"choice": "A"}}), "APPROVAL_STALE")

    def test_proposer_cannot_launder_self_approval_through_another_requester(self):
        self.ready_decision()
        self.request_approval("ap", target=self.service.snapshot("p-1", "decision", "decision-1"),
                              action="decision.activate", arguments={"choice": "A"}, actor="a-2")
        self.reject(self.grant("ap", actor="a-1"), "SELF_APPROVAL")
        self.accept(self.grant("ap", actor="human-owner"))

    def test_trusted_ingress_does_not_clear_untrusted_peer_proposal(self):
        self.ready_decision()
        row = self.request_approval("ap", target=self.service.snapshot("p-1", "decision", "decision-1"),
                                    action="decision.activate", arguments={"choice": "A"}, trusted=True)
        self.assertTrue(row["source"]["untrusted_input"])
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["source"]["target_source"]["id"], "decision-1")

    def test_compact_and_retry_keep_dissent_after_decision_is_active(self):
        self.open_discussion()
        entry = self.contribution("d", actor="a-2", category="disagreement", position="B", content="Keep this risk")
        receipt = self.meter.issue(entry, call_id="dissent-call", tokens=2)
        original = self.service.post(entry, authenticated_actor_id="a-2", receipt=receipt)
        self.synthesize("d")
        self.propose("d")
        self.accept(self.command("decision.review", "decision-1", {"feedback": "Independent check"}, actor="a-2"))
        self.accept(self.command("decision.submit", "decision-1"))
        self.approve_decision()
        self.accept(self.command("decision.activate", "decision-1", {"approval_id": "decision-ap", "arguments": {"choice": "A"}}))
        self.accept(self.command("discussion.close", "d", {"decision_id": "decision-1"}))
        self.service.compact("p-1", "discussion", "d", authenticated_actor_id="a-1")
        before = len(self.store.read_events("p-1"))
        repeated = self.service.post(entry, authenticated_actor_id="a-2", receipt=None)
        self.assertEqual(repeated, original)
        self.assertEqual(len(self.store.read_events("p-1")), before)
        self.assertEqual(self.state()["decision:decision-1"]["minority_opinions"][0]["content"], "Keep this risk")

    def test_activation_checks_expiry_even_before_host_tick(self):
        self.ready_decision()
        self.approve_decision()
        self.clock_value = 2000
        self.reject(self.command("decision.activate", "decision-1", {"approval_id": "decision-ap", "arguments": {"choice": "A"}}), "APPROVAL_EXPIRED")

    def test_denial_records_rejected_decision_without_rewriting_proposal(self):
        original = self.ready_decision()
        self.request_approval("ap", target=self.service.snapshot("p-1", "decision", "decision-1"),
                              action="decision.activate", arguments={"choice": "A"})
        self.accept(self.command("approval.deny", "ap", {"reason": "Use another option"}, actor="a-2"))
        self.assertEqual(self.state()["decision:decision-1"]["status"], "rejected")
        self.assertEqual(self.state()["decision:decision-1"]["content_digest"], original["content_digest"])
