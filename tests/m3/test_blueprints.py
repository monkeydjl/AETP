"""Candidate DAGs cannot create execution rights or lose their historical basis."""

import copy
from dataclasses import replace

from aetp.collaboration.policy import PolicyViolation, digest_value
from aetp.domain.models import Command
from tests.m2.governance_support import policy
from tests.m3.support import PlanningCase


class BlueprintTests(PlanningCase):
    def preview(self, version=None):
        return self.service.preview("p-1", "bp-1", version=version, authenticated_actor_id="a-2")

    def decision_ref(self, identifier="decision-1"):
        decision = self.state()[f"decision:{identifier}"]
        return {"type": "decision", "id": identifier, "revision": decision.get("proposal_revision", 0),
                "content_digest": decision["content_digest"]}

    def activate_decision(self):
        self.accept(self.command("decision.review", "decision-1", {"feedback": "Compared options"}, actor="a-2"))
        self.accept(self.command("decision.submit", "decision-1"))
        self.accept(self.command("approval.request", "ap-1", {
            "target": self.service.snapshot("p-1", "decision", "decision-1"), "action": "decision.activate",
            "arguments": {"choice": "A"}, "ttl_ms": 1000}))
        self.accept(self.command("approval.grant", "ap-1", {"reason": "Independent review"}, actor="a-2"))
        args = {"approval_id": "ap-1", "arguments": {"choice": "A"}}
        self.accept(self.command("decision.approve", "decision-1", args))
        self.accept(self.command("decision.activate", "decision-1", args))

    def task_proposal(self, task, **extra):
        body = {"proposal_id": f"proposal-{self.counter + 1}", "base": self.ref("blueprint", "bp-1"),
                "task": task, "reason": "The guide needs another section", "risk_level": "low",
                "estimated_cost": {"amount": 1, "unit": "USD"}, "estimated_delay_ms": 1000}
        body.update(extra)
        return self.command("task.propose", "bp-1", body, actor="a-2")

    def test_dag_has_deterministic_parallel_layers_but_no_claimable_tasks(self):
        self.team()
        content = self.blueprint_content()
        content["tasks"] = [self.task_content("write"), self.task_content("research"),
                            self.task_content("review", [{"type": "task", "id": "write"}, {"type": "task", "id": "research"}])]
        candidate = self.blueprint(content=content)
        self.assertEqual(candidate["dag"]["layers"], [["research", "write"], ["review"]])
        self.assertEqual(candidate["dag"]["topological_order"], ["research", "write", "review"])
        self.assertEqual(candidate["dag"]["version"], 1)
        self.assertEqual(self.preview()["claimable_task_ids"], [])
        self.assertEqual(self.preview()["execution_readiness"], "unavailable")
        self.assertFalse(any(key.startswith("task:") for key in self.state()))

    def test_self_two_node_and_indirect_cycles_are_rejected(self):
        self.team()
        graphs = [[self.task_content("a", [{"type": "task", "id": "a"}])],
                  [self.task_content("a", [{"type": "task", "id": "b"}]), self.task_content("b", [{"type": "task", "id": "a"}])],
                  [self.task_content("a", [{"type": "task", "id": "c"}]), self.task_content("b", [{"type": "task", "id": "a"}]),
                   self.task_content("c", [{"type": "task", "id": "b"}])]]
        for tasks in graphs:
            content = self.blueprint_content()
            content["tasks"] = tasks
            self.reject(self.command("blueprint.propose", "bp-1", {"content": content}), "DAG_CYCLE")
        self.assertNotIn("blueprint:bp-1", self.state())

    def test_unknown_dependency_and_cross_blueprint_edges_are_rejected(self):
        self.blueprint()
        content = self.blueprint_content()
        content["tasks"] = [self.task_content("other", [{"type": "task", "id": "write"}])]
        self.reject(self.command("blueprint.propose", "bp-2", {"content": content}), "INVALID_DEPENDENCY")

    def test_duplicate_nodes_edges_and_milestones_are_rejected(self):
        self.team()
        for mutation in ("task", "edge", "milestone", "unknown_milestone"):
            content = self.blueprint_content()
            if mutation == "task":
                content["tasks"].append(copy.deepcopy(content["tasks"][0]))
            elif mutation == "edge":
                content["tasks"][1]["dependencies"] *= 2
            elif mutation == "milestone":
                content["milestones"] *= 2
            else:
                content["tasks"][0]["milestone_id"] = "absent"
            self.reject(self.command("blueprint.propose", "bp-1", {"content": content}), "INVALID_DAG")

    def test_missing_artifact_input_is_not_an_accepted_snapshot(self):
        self.team()
        content = self.blueprint_content()
        content["tasks"][0]["inputs"] = [{"type": "artifact", "id": "not-real", "content_digest": "sha256:" + "0" * 64}]
        self.reject(self.command("blueprint.propose", "bp-1", {"content": content}), "INVALID_REFERENCE")

    def test_wrong_mission_team_type_and_reference_digest_rejected(self):
        self.team()
        self.mission("mission-2")
        for mutation in ("mission", "type", "digest"):
            content = self.blueprint_content()
            if mutation == "mission":
                content["mission"] = self.ref("mission", "mission-2")
            elif mutation == "type":
                content["team"]["type"] = "mission"
            else:
                content["team"]["content_digest"] = "sha256:" + "0" * 64
            self.reject(self.command("blueprint.propose", "bp-1", {"content": content}),
                        "REFERENCE_STALE" if mutation == "digest" else "INVALID_REFERENCE")

    def test_cross_project_reference_cannot_be_smuggled_into_candidate(self):
        self.team()
        command = Command("other-project", "p-2", "bootstrap", "project.create", None,
                          {"status": "planning"}, 0, "other-project", "test")
        self.accept(command)
        content = self.blueprint_content()
        content["mission"]["id"] = "mission-from-p-2"
        self.reject(self.command("blueprint.propose", "bp-1", {"content": content}), "INVALID_REFERENCE")

    def test_old_team_snapshot_is_rejected_at_final_proposal(self):
        self.team()
        content = self.blueprint_content()
        self.accept(self.revise_team(self.team_content()))
        self.reject(self.command("blueprint.propose", "bp-1", {"content": content}), "REFERENCE_STALE")

    def test_decision_dependency_is_fixed_and_not_satisfied_by_proposal(self):
        self.team()
        self.propose()
        content = self.blueprint_content()
        content["tasks"][0]["dependencies"] = [self.decision_ref()]
        self.blueprint(content=content)
        self.assertEqual(self.preview()["decision_dependencies"][0]["reason"], "DECISION_NOT_ACTIVE")
        content["tasks"][0]["dependencies"][0]["revision"] = 1
        self.reject(self.command("blueprint.propose", "bp-2", {"content": content}), "REFERENCE_STALE")

    def test_active_decision_is_rechecked_for_expiry_without_tick(self):
        self.team()
        self.propose()
        content = self.blueprint_content()
        content["tasks"][0]["dependencies"] = [self.decision_ref()]
        self.blueprint(content=content)
        self.activate_decision()
        self.assertTrue(self.preview()["decision_dependencies"][0]["satisfied"])
        self.clock_value += 1001
        preview = self.preview()
        self.assertFalse(preview["decision_dependencies"][0]["satisfied"])
        self.assertEqual(preview["decision_dependencies"][0]["reason"], "APPROVAL_EXPIRED")
        self.assertEqual(self.state()["decision:decision-1"]["status"], "active")

    def test_active_history_with_policy_invalidation_is_not_current_dependency(self):
        self.team()
        self.propose()
        self.activate_decision()
        content = self.blueprint_content()
        content["tasks"][0]["dependencies"] = [self.decision_ref()]
        self.blueprint(content=content)
        self.accept(self.command("project.governance.configure", "p-1", {"policy": policy("gov-2")}, actor="human-owner"))
        self.assertEqual(self.state()["decision:decision-1"]["status"], "active")
        self.assertFalse(self.preview()["decision_dependencies"][0]["satisfied"])

    def test_newer_team_is_visible_as_a_stale_preview_dependency(self):
        self.blueprint()
        self.accept(self.revise_team(self.team_content()))
        self.assertIn("TEAM_REFERENCE_STALE", self.preview()["blockers"])
        self.assertEqual(self.candidate("blueprint", "bp-1")["content"]["team"]["version"], 1)

    def test_task_proposal_by_peer_creates_only_change_request_candidate(self):
        before = self.blueprint()
        command = self.task_proposal(self.task_content("recovery", [{"type": "task", "id": "write"}]))
        self.accept(command)
        new = self.candidate("blueprint", "bp-1")
        self.assertEqual(new["version"], 2)
        self.assertEqual(new["dag"]["version"], 2)
        self.assertEqual(new["change_request"]["route"], "discussion_decision_approval")
        self.assertEqual(new["change_request"]["status"], "proposed")
        self.assertEqual(new["proposed_by"], "a-2")
        self.assertEqual(new["supersedes"]["content_digest"], before["content_digest"])
        self.assertEqual(self.candidate("blueprint", "bp-1", 1), before)
        self.assertIsNone(self.state()["blueprint:bp-1"]["active_version"])
        self.assertFalse(any(key.startswith("task:") for key in self.state()))
        self.reject(self.command("task.claim", "recovery"), "PLANNING_NOT_ACTIVE")

    def test_task_proposal_cannot_select_a_non_blueprint_fast_path(self):
        self.blueprint()
        self.reject(self.task_proposal(self.task_content("new"), affects_blueprint=False), "INVALID_PAYLOAD")
        self.reject(self.task_proposal(self.task_content("write")), "INVALID_DAG")

    def test_changed_task_impact_includes_downstream_tasks_and_team_members(self):
        first = self.blueprint()
        content = self.blueprint_content()
        content["tasks"][0]["acceptance_criteria"].append("Include recovery example")
        self.accept(self.change(content))
        new = self.candidate("blueprint", "bp-1")
        impact = new["change_request"]["impact"]
        self.assertEqual(impact["affected_tasks"], ["review", "write"])
        self.assertEqual(impact["affected_team_members"], ["a-1", "a-2"])
        self.assertEqual(impact["estimated_delay_ms"], 5000)
        self.assertEqual(impact["risk_level"], "medium")
        self.assertNotEqual(new["dag"]["content_digest"], first["dag"]["content_digest"])
        self.assertEqual(self.candidate("blueprint", "bp-1", 1), first)

    def test_removed_tasks_remain_in_previous_candidate(self):
        first = self.blueprint()
        content = self.blueprint_content()
        content["tasks"].pop()
        self.accept(self.change(content))
        self.assertEqual(len(self.candidate("blueprint", "bp-1", 1)["content"]["tasks"]), 2)
        self.assertEqual(self.candidate("blueprint", "bp-1", 1), first)
        self.assertIn("review", self.candidate("blueprint", "bp-1")["change_request"]["impact"]["affected_tasks"])

    def test_change_request_revalidates_entire_graph(self):
        first = self.blueprint()
        content = self.blueprint_content()
        content["tasks"][0]["dependencies"] = [{"type": "task", "id": "review"}]
        self.reject(self.change(content), "DAG_CYCLE")
        self.assertEqual(self.candidate("blueprint", "bp-1"), first)

    def test_change_request_requires_latest_base_and_unique_id(self):
        self.blueprint()
        command = self.change(self.blueprint_content(), change_id="cr-1")
        self.accept(command)
        self.reject(replace(command, id="other", idempotency_key="other"), "REVISION_CONFLICT")
        self.reject(self.change(self.blueprint_content(), base=self.ref("blueprint", "bp-1", 1)), "REFERENCE_STALE")
        self.reject(self.change(self.blueprint_content(), change_id="cr-1"), "PROPOSAL_ID_CONFLICT")

    def test_source_decision_provenance_survives_revision_without_authority_upgrade(self):
        self.team()
        self.propose()
        self.activate_decision()
        first = self.blueprint(source_decisions=[self.decision_ref()])
        self.accept(self.change(self.blueprint_content()))
        new = self.candidate("blueprint", "bp-1")
        self.assertEqual(new["source_decisions"], first["source_decisions"])
        self.assertTrue(new["untrusted_input"])
        self.assertEqual(new["authority"], "proposal_only")
        self.assertEqual(new["source_decisions"][0]["reference"], self.decision_ref())
        self.reject(self.command("blueprint.activate", "bp-1", {"approval_id": "ap-1"}), "ENFORCEMENT_UNAVAILABLE")

    def test_unknown_trust_status_and_approval_fields_cannot_change_candidate(self):
        self.team()
        for extra in ({"untrusted_input": False}, {"authority": "approved"}, {"approved_by": "human-owner"}):
            self.reject(self.command("blueprint.propose", "bp-1", {"content": self.blueprint_content(), **extra}), "INVALID_PAYLOAD")

    def test_paused_revision_and_preview_preserve_unavailable_execution(self):
        self.blueprint()
        self.accept(self.control("pause"))
        self.accept(self.change(self.blueprint_content()))
        self.assertEqual(self.preview()["claimable_task_ids"], [])
        self.assertIn("PROJECT_PAUSED", self.preview()["blockers"])

    def test_candidate_digest_covers_full_graph_and_sources(self):
        candidate = self.blueprint()
        fixed = copy.deepcopy(candidate)
        digest = fixed.pop("content_digest")
        self.assertEqual(digest_value(fixed), digest)
        fixed["content"]["tasks"][1]["dependencies"] = []
        self.assertNotEqual(digest_value(fixed), digest)

    def test_preview_refuses_nonparticipant_and_invalid_versions(self):
        self.blueprint()
        for actor, version in (("unknown", None), ("a-2", 99), ("a-2", True)):
            with self.assertRaises(PolicyViolation):
                self.service.preview("p-1", "bp-1", version=version, authenticated_actor_id=actor)
