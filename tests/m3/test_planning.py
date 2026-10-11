"""Scope and equal-team tests catch authority leaks and history loss."""

import copy
from dataclasses import replace
from pathlib import Path
import tempfile

from aetp.collaboration.messages import Message
from aetp.collaboration.service import CollaborationService
from aetp.core.commands import CommandHandler
from aetp.core.projection import Projection
from aetp.domain.models import ModelValidationError
from tests.m3.support import PlanningCase


class PlanningConfigurationTests(PlanningCase):
    configure_scope = False

    def test_owner_configures_durable_candidate_scope(self):
        before = self.state()["project:p-1"]["revision"]
        self.configure()
        project = self.state()["project:p-1"]
        self.assertEqual(project["planning"]["mode"], "candidate_only")
        self.assertEqual(project["revision"], before + 1)
        self.assertEqual(project["status"], "planning")
        self.assertNotIn("bootstrap_verified", project)

    def test_agent_cannot_configure_even_with_owner_role_name(self):
        self.reject(self.command("project.planning.configure", "p-1", {"mode": "candidate_only"}), "PERMISSION_DENIED")

    def test_existing_legacy_task_prevents_configuration(self):
        command = self.command("task.create", "old-task", {"title": "Existing simulation task"})
        self.assertEqual(CommandHandler(self.store).handle(command, authenticated_actor_id="a-1").status, "accepted")
        self.reject(self.command("project.planning.configure", "p-1", {"mode": "candidate_only"},
                                 actor="human-owner"), "TASK_GRAPH_ALREADY_EXISTS")
        self.assertNotIn("planning", self.state()["project:p-1"])

    def test_configuration_requires_unpaused_project(self):
        self.accept(self.control("pause"))
        self.reject(self.command("project.planning.configure", "p-1", {"mode": "candidate_only"},
                                 actor="human-owner"), "PROJECT_PAUSED")

    def test_configuration_cannot_claim_bootstrap_or_disable_scope(self):
        for value in ({"mode": "active"}, {"mode": "candidate_only", "bootstrap_verified": True}):
            self.reject(self.command("project.planning.configure", "p-1", value, actor="human-owner"), "INVALID_PAYLOAD")
        self.configure()
        self.reject(self.command("project.planning.configure", "p-1", {"mode": "candidate_only"},
                                 actor="human-owner"), "PLANNING_ALREADY_CONFIGURED")

    def test_unconfigured_project_rejects_planning_proposal(self):
        self.reject(self.command("mission.propose", "mission-1", {"content": {}}), "ENFORCEMENT_UNAVAILABLE")


class PlanningScopeTests(PlanningCase):
    def test_raw_core_and_collaboration_create_cannot_omit_scope_metadata(self):
        for service in (CommandHandler(self.store), CollaborationService(self.store), self.service):
            for kind in ("task.create", "task.claim", "execution.start"):
                command = self.command(kind, "raw-task", {"title": "Bypass"} if kind == "task.create" else {})
                result = service.handle(command, authenticated_actor_id="a-1")
                self.assertEqual((result.status, result.error_code), ("rejected", "PLANNING_NOT_ACTIVE"))
        self.assertFalse(any(key.startswith("task:") for key in self.state()))

    def test_runtime_entry_also_obeys_persistent_scope(self):
        from aetp.runtime.document import DocumentRuntime
        from aetp.runtime.service import ExecutionService
        from aetp.workspace.documents import DocumentWorkspace
        root = Path(__file__).resolve().parents[2] / ".tmp"
        root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="m3-scope-", dir=root) as directory:
            runtime = DocumentRuntime(DocumentWorkspace(Path(directory) / "workspace"))
            service = ExecutionService(self.store, runtime, clock=lambda: self.clock_value)
            for kind in ("task.create", "task.claim", "execution.start"):
                command = self.command(kind, "raw-task", {"title": "Bypass"} if kind == "task.create" else {})
                result = service.handle(command, authenticated_actor_id="a-1")
                self.assertEqual(result.error_code, "PLANNING_NOT_ACTIVE")

    def test_replay_rejects_task_fact_after_candidate_configuration(self):
        from aetp.domain.models import Event
        events = self.store.read_events("p-1")
        fact = Event("forged-task", "p-1", events[-1].sequence + 1, "task.created", "task", "raw", 0,
                     "fake-command", "m3-test", {"title": "Bypass", "status": "pending"})
        with self.assertRaises(ModelValidationError):
            Projection.rebuild(events + [fact])

    def test_activation_cannot_borrow_decision_approval_or_bootstrap_flag(self):
        self.team()
        for kind, target in (("team.activate", "team-1"), ("blueprint.activate", "bp-1"),
                             ("blueprint.apply", "bp-1"), ("mission.activate", "mission-1")):
            self.reject(self.command(kind, target, {"approval_id": "approved-decision", "bootstrap_verified": True}),
                        "ENFORCEMENT_UNAVAILABLE")


class EqualTeamTests(PlanningCase):
    def test_two_agents_propose_without_manager_or_task_lease(self):
        self.mission(actor="a-2")
        team = self.team(actor="a-1")
        self.assertEqual(team["authority"], "proposal_only")
        self.assertTrue(team["untrusted_input"])
        self.assertEqual(team["version"], 1)
        self.assertEqual(team["member_models"], {"a-1": "model-1", "a-2": "model-2"})
        self.assertIsNone(self.state()["team:team-1"]["active_version"])
        self.assertFalse(any(key.startswith("task:") for key in self.state()))
        self.assertEqual(self.candidate("mission", "mission-1")["proposed_by"], "a-2")

    def test_actor_mismatch_does_not_reserve_legitimate_proposal(self):
        self.mission()
        command = self.command("team.propose", "team-1", {"content": self.team_content()})
        self.assertEqual(self.service.handle(command, authenticated_actor_id="a-2").error_code, "ACTOR_MISMATCH")
        self.accept(command)

    def test_hierarchical_structure_and_privilege_fields_are_rejected(self):
        self.mission()
        changes = [{"structure": {"mode": "hierarchical"}}, {"manager_id": "a-1"},
                   {"structure": {"mode": "adaptive", "reporting_to": "a-1"}}]
        for change in changes:
            content = self.team_content()
            content.update(change)
            self.reject(self.command("team.propose", "team-1", {"content": content}), "INVALID_PAYLOAD")

    def test_unknown_member_role_or_missing_contract_rejected(self):
        self.mission()
        for mutation in ("member", "role", "contract"):
            content = self.team_content()
            if mutation == "member":
                content["members"][0]["agent_id"] = "not-registered"
            elif mutation == "role":
                content["members"][0]["roles"] = ["not-a-role"]
            else:
                content["contracts"].pop()
            self.reject(self.command("team.propose", "team-1", {"content": content}), "INVALID_TEAM")

    def test_multiple_roles_and_cyclic_interfaces_do_not_form_hierarchy(self):
        self.mission()
        content = self.team_content()
        content["roles"].append({"id": "researcher", "name": "Researcher", "required_capabilities": ["research"],
                                 "authority": ["task.propose"]})
        content["members"][0]["roles"].append("researcher")
        contract = copy.deepcopy(content["contracts"][0])
        contract["role_id"] = "researcher"
        content["contracts"].append(contract)
        content["interfaces"].extend([{"roles": ["reviewer", "researcher"], "purpose": "Check sources"},
                                      {"roles": ["researcher", "writer"], "purpose": "Explain evidence"}])
        self.accept(self.command("team.propose", "team-1", {"content": content}))
        self.assertEqual(len(self.candidate("team", "team-1")["content"]["interfaces"]), 3)

    def test_revising_team_keeps_old_members_history_and_project_access(self):
        first = self.team()
        self.register()
        self.accept(self.revise_team(self.team_content(("a-1", "a-2", "a-3"))))
        self.accept(self.revise_team(self.team_content(("a-1", "a-3"))))
        self.assertEqual(self.candidate("team", "team-1", 1), first)
        self.assertEqual(self.candidate("team", "team-1")["version"], 3)
        self.assertEqual(self.state()["agent:a-2"]["status"], "available")
        message = Message("question", "p-1", "a-2", ("a-3",), "question", "Why change this role?")
        self.service.messages.send(message, authenticated_actor_id="a-2")
        reply = Message("reply", "p-1", "a-3", ("a-2",), "response", "The assignment is still a proposal",
                        references=("question",), target_message="question")
        self.service.messages.send(reply, authenticated_actor_id="a-3")
        self.assertEqual(len(self.service.messages.inbox("p-1", authenticated_actor_id="a-2")), 1)

    def test_named_manager_and_contract_authority_do_not_grant_human_power(self):
        self.mission()
        governance = copy.deepcopy(self.state()["project:p-1"]["governance"])
        content = self.team_content()
        content["roles"][0]["name"] = "Manager"
        content["roles"][0]["authority"] = ["project.pause", "blueprint.approve"]
        content["contracts"][0]["authority"]["can"] = ["project.pause"]
        self.accept(self.command("team.propose", "team-1", {"content": content}))
        self.assertEqual(self.state()["project:p-1"]["governance"], governance)
        self.reject(replace(self.control("pause"), actor_id="a-1"), "PERMISSION_DENIED")

    def test_old_base_and_reused_version_cannot_overwrite_team(self):
        self.team()
        command = self.revise_team(self.team_content())
        self.accept(command)
        self.reject(replace(command, id="new-command", idempotency_key="new-key"), "REVISION_CONFLICT")
        stale = self.revise_team(self.team_content(), base=self.ref("team", "team-1", 1))
        self.reject(stale, "REFERENCE_STALE")

    def test_pause_allows_candidate_material_but_keeps_execution_closed(self):
        self.team()
        self.accept(self.control("pause"))
        self.accept(self.revise_team(self.team_content()))
        self.assertEqual(self.state()["project:p-1"]["status"], "paused")
        self.reject(self.command("task.create", "t", {"title": "No dispatch"}), "PLANNING_NOT_ACTIVE")

    def test_candidate_reads_are_detached_and_do_not_grant_governance_snapshot(self):
        self.team()
        candidate = self.candidate("team", "team-1")
        candidate["content"]["members"].clear()
        self.assertEqual(len(self.candidate("team", "team-1")["content"]["members"]), 2)
        from aetp.collaboration.policy import PolicyViolation
        with self.assertRaises(PolicyViolation) as error:
            self.service.snapshot("p-1", "team", "team-1")
        self.assertEqual(error.exception.code, "ENFORCEMENT_UNAVAILABLE")
