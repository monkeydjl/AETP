"""Approval authority and exact snapshots; each denial exercises the real writer."""

from dataclasses import replace

from aetp.collaboration.policy import PolicyViolation
from aetp.core.commands import CommandHandler
from aetp.core.projection import Projection
from aetp.domain.models import ModelValidationError
from aetp.governance.contracts import system_actor
from aetp.governance.policy import principal
from tests.m2.governance_support import GovernanceCase, GovernanceService, policy


class ApprovalTests(GovernanceCase):
    def test_manual_mode_requires_human_even_if_a_rule_names_an_agent_delegate(self):
        value = policy("gov-manual", approval="delegated", delegate="a-2", revocable_within_ms=100)
        value["mode"] = "manual"
        self.configure(value)
        row = self.request_approval(trusted=True)
        self.assertEqual(row["routing"]["mode"], "human")
        self.assertIsNone(row["delegated_to"])
        self.reject(self.grant(), "PERMISSION_DENIED")
        self.accept(self.grant(actor="human-peer"))

    def test_late_agent_registration_cannot_reuse_human_or_system_identity(self):
        for actor in ("human-owner", "human-peer", system_actor("p-1")):
            with self.subTest(actor=actor):
                command = self.command("agent.register", actor, {"model_id": "late-model"}, actor="bootstrap")
                result = CommandHandler(self.store).handle(command, authenticated_actor_id="bootstrap")
                self.assertEqual((result.status, result.error_code), ("rejected", "IDENTITY_CONFLICT"))
                self.assertNotIn(f"agent:{actor}", self.state())
        ordinary = self.command("agent.register", "ordinary-agent", {"model_id": "model-3"}, actor="bootstrap")
        self.assertEqual(CommandHandler(self.store).handle(ordinary, authenticated_actor_id="bootstrap").status, "accepted")

    def test_human_identity_remains_reserved_after_policy_removes_its_current_role(self):
        value = policy("gov-2")
        del value["subjects"]["human-peer"]
        self.configure(value)
        command = self.command("agent.register", "human-peer", {"model_id": "late-model"}, actor="bootstrap")
        result = CommandHandler(self.store).handle(command, authenticated_actor_id="bootstrap")
        self.assertEqual((result.status, result.error_code), ("rejected", "IDENTITY_CONFLICT"))

    def test_principal_fails_closed_on_contradictory_human_agent_state(self):
        state = self.state()
        state["agent:human-owner"] = {**state["agent:a-1"], "id": "human-owner"}
        with self.assertRaisesRegex(PolicyViolation, "PERMISSION_DENIED"):
            principal(state, "p-1", "human-owner")

    def test_replay_rejects_late_agent_creation_with_reserved_human_identity(self):
        command = self.command("agent.register", "ordinary-agent", {"model_id": "model-3"}, actor="bootstrap")
        self.assertEqual(CommandHandler(self.store).handle(command, authenticated_actor_id="bootstrap").status, "accepted")
        events = [replace(event, aggregate_id="human-owner") if event.type == "agent.created"
                  and event.aggregate_id == "ordinary-agent" else event for event in self.store.read_events("p-1")]
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(events)

    def test_unknown_input_requires_independent_peer_and_keeps_attribution(self):
        row = self.request_approval()
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["risk_level"], "medium")
        self.assertTrue(row["source"]["untrusted_input"])
        self.reject(self.grant(actor="a-1"), "SELF_APPROVAL")
        self.accept(self.grant())
        row = self.approval()
        self.assertEqual(row["status"], "approved")
        self.assertEqual(row["requested_by"], {"type": "agent", "id": "a-1"})
        self.assertEqual(row["approved_by"], {"type": "agent", "id": "a-2"})

    def test_forged_authenticated_actor_cannot_reserve_request(self):
        command = self.request_command()
        before = len(self.store.read_events("p-1"))
        result = self.service.handle(command, authenticated_actor_id="a-2")
        self.assertEqual(result.error_code, "ACTOR_MISMATCH")
        self.assertEqual(len(self.store.read_events("p-1")), before)
        self.accept(command)

    def test_snapshot_digest_version_and_kind_are_validated_at_request(self):
        target = self.service.snapshot("p-1", "task", "t-1")
        self.assertEqual(target["revision_kind"], "aggregate")
        self.assertRegex(target["content_digest"], r"^sha256:[0-9a-f]{64}$")
        for index, change in enumerate(({"revision": target["revision"] + 1}, {"content_digest": "sha256:" + "0" * 64},
                                        {"revision_kind": "proposal"})):
            with self.subTest(change=change):
                self.reject(self.request_command(f"bad-{index}", target={**target, **change}), "APPROVAL_STALE")

    def test_current_target_is_rechecked_when_granting(self):
        self.request_approval()
        self.eaccept(self.command("execution.report", "t-1", {**self.fence(), "summary": "New observation"}), session=self.session)
        self.reject(self.grant(), "APPROVAL_STALE")

    def test_request_cannot_borrow_another_executors_task(self):
        self.reject(self.request_command(actor="a-2"), "PERMISSION_DENIED")

    def test_high_and_critical_approvals_require_human_authority(self):
        self.request_approval("high", risk_level="high")
        self.reject(self.grant("high"), "PERMISSION_DENIED")
        self.accept(self.grant("high", actor="human-peer"))
        self.request_approval("critical", risk_level="critical")
        self.reject(self.grant("critical", actor="human-peer"), "PERMISSION_DENIED")
        self.accept(self.grant("critical", actor="human-owner"))

    def test_critical_auto_and_delegated_policies_are_rejected_before_use(self):
        for mode in ("auto", "delegated", "decision_based"):
            value = policy("invalid-" + mode)
            value["rules"].append({"action": "database.drop", "risk_level": "critical", "approval": mode,
                                    **({"delegate": "a-2", "revocable_within_ms": 100} if mode == "delegated" else {})})
            self.reject(self.command("project.governance.configure", "p-1", {"policy": value}, actor="human-owner"), "INVALID_POLICY")
        self.assertEqual(self.state()["project:p-1"]["governance"]["current_version"], "gov-1")

    def test_delegation_records_actual_approver_and_cannot_remove_separation(self):
        self.configure(policy("gov-2", approval="delegated", delegate="a-2", revocable_within_ms=100))
        row = self.request_approval()
        self.assertEqual(row["delegated_to"], {"type": "agent", "id": "a-2"})
        self.assertIn("approval.delegated", self.event_types())
        self.reject(self.grant(actor="a-1"), "SELF_APPROVAL")
        self.reject(self.grant(actor="human-peer"), "PERMISSION_DENIED")
        self.accept(self.grant())
        self.assertEqual(self.approval()["revocable_until"], 1100)

    def test_delegating_to_requester_does_not_self_approve(self):
        self.configure(policy("gov-2", approval="delegated", delegate="a-1", revocable_within_ms=100))
        self.reject(self.request_command(), "SELF_APPROVAL")
        self.assertNotIn("approval:ap-1", self.state())

    def test_unknown_target_types_and_unimplemented_mission_reject(self):
        for kind, code in (("anything", "INVALID_TARGET_TYPE"), ("mission", "ENFORCEMENT_UNAVAILABLE"),
                           ("deployment", "ENFORCEMENT_UNAVAILABLE")):
            with self.subTest(kind=kind):
                target = {"type": kind, "id": "x", "revision": 0, "content_digest": "sha256:" + "0" * 64,
                          "revision_kind": "aggregate"}
                self.reject(self.request_command("ap-" + kind, target=target), code)

    def test_policy_admin_cannot_be_inferred_from_actor_name_or_payload(self):
        value = policy("gov-2")
        self.reject(self.command("project.governance.configure", "p-1", {"policy": value}, actor="a-1"), "PERMISSION_DENIED")
        value["subjects"]["a-1"] = {"type": "human", "roles": ["human_owner"]}
        self.reject(self.command("project.governance.configure", "p-1", {"policy": value}, actor="human-owner"), "INVALID_POLICY")

    def test_policy_version_cannot_be_rebound_to_new_content(self):
        changed = policy()
        changed["max_ttl_ms"] = 10000
        self.reject(self.command("project.governance.configure", "p-1", {"policy": changed}, actor="human-owner"), "POLICY_VERSION_CONFLICT")

    def test_policy_change_invalidates_prior_authorization_with_a_new_fact(self):
        self.request_approval()
        self.accept(self.grant())
        previous = [event.to_json() for event in self.store.read_events("p-1")]
        self.configure(policy("gov-2"))
        self.assertEqual(self.approval()["status"], "approved")
        self.assertEqual(self.approval()["validity"], "invalidated")
        self.assertIn("approval.invalidated", self.event_types())
        self.assertEqual([event.to_json() for event in self.store.read_events("p-1")][:len(previous)], previous)

    def test_rejected_approval_is_final_and_retries_do_not_duplicate_facts(self):
        self.request_approval()
        command = self.command("approval.deny", "ap-1", {"reason": "Scope is unsuitable"}, actor="a-2")
        result = self.accept(command)
        count = len(self.store.read_events("p-1"))
        self.assertEqual(self.accept(command), result)
        self.assertEqual(len(self.store.read_events("p-1")), count)
        self.reject(self.grant(), "APPROVAL_FINAL")

    def test_self_reported_roles_and_policy_flags_are_not_authority(self):
        self.reject(self.request_command(untrusted_input=False), "INVALID_PAYLOAD")
        self.request_approval()
        command = self.command("approval.grant", "ap-1", {"reason": "Claim owner", "role": "human_owner"}, actor="a-1")
        self.reject(command, "INVALID_PAYLOAD")

    def test_no_owner_capability_can_bootstrap_an_unconfigured_project(self):
        # A different project reuses authenticated fixtures but has no governance root.
        from aetp.core.commands import CommandHandler
        create = self.command("project.create", None, {"status": "planning"}, actor="bootstrap")
        create = replace(create, project_id="p-2")
        self.assertEqual(CommandHandler(self.store).handle(create, authenticated_actor_id="bootstrap").status, "accepted")
        service = GovernanceService(self.store, clock=lambda: self.clock_value)
        command = replace(self.command("project.governance.configure", "p-2", {"policy": policy()}, actor="human-owner"), project_id="p-2")
        self.assertEqual(service.handle(command, authenticated_actor_id="human-owner").error_code, "ENFORCEMENT_UNAVAILABLE")
