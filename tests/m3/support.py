"""Real Command/Event fixtures for candidate planning."""

import copy

from aetp.domain.models import Command
from tests.m2.governance_support import policy
from tests.m2.support import MeetingCase

try:
    from aetp.planning.service import PlanningService
except ModuleNotFoundError as exc:
    if not exc.name.startswith("aetp.planning"):
        raise
    PlanningService = None


class PlanningCase(MeetingCase):
    configure_scope = True

    def setUp(self):
        self.assertIsNotNone(PlanningService, "M3-01 PlanningService is not implemented")
        super().setUp()
        self.service = PlanningService(self.store, owner_id="human-owner", meter=self.meter,
                                       clock=lambda: self.clock_value)
        self.accept(self.command("project.governance.configure", "p-1", {"policy": policy()}, actor="human-owner"))
        if self.configure_scope:
            self.configure()

    def configure(self, **kwargs):
        return self.accept(self.command("project.planning.configure", "p-1", {"mode": "candidate_only"},
                                        actor="human-owner", **kwargs))

    def command(self, kind, target, payload=None, *, actor="a-1", revision=None, key=None):
        self.counter += 1
        key = key or f"planning-command-{self.counter}"
        if revision is None:
            aggregate = "blueprint" if kind == "task.propose" else kind.split(".")[0]
            row = self.state().get(f"{aggregate}:{target}")
            revision = row["revision"] if row else 0
        return Command(key, "p-1", actor, kind, target, payload or {}, revision, key, "m3-test")

    def candidate(self, kind, identifier, version=None):
        return self.service.candidate("p-1", kind, identifier, version=version, authenticated_actor_id="a-1")

    def ref(self, kind, identifier, version=None):
        candidate = self.candidate(kind, identifier, version)
        return {"type": kind, "id": identifier, "version": candidate["version"],
                "content_digest": candidate["content_digest"]}

    def mission(self, identifier="mission-1", actor="a-1"):
        self.accept(self.command("mission.propose", identifier, {"content": {
            "title": "Explain resilient collaboration", "objective": "Deliver a short practical guide",
            "constraints": ["Local document only"], "success_criteria": ["Roles remain equal", "Recovery is explained"]}}, actor=actor))
        return self.candidate("mission", identifier)

    def team_content(self, members=("a-1", "a-2")):
        roles = [{"id": "writer", "name": "Writer", "required_capabilities": ["writing"], "authority": ["task.propose"]},
                 {"id": "reviewer", "name": "Reviewer", "required_capabilities": ["review"], "authority": ["task.propose"]}]
        assignments, contracts = [], []
        for index, actor in enumerate(members):
            role_id = roles[index % 2]["id"]
            assignments.append({"agent_id": actor, "roles": [role_id], "confidence": 0.8})
            contracts.append({"agent_id": actor, "role_id": role_id, "responsibilities": ["Draft or review guide"],
                              "authority": {"can": ["task.propose"], "cannot": ["production.deploy"]},
                              "deliverables": ["Guide feedback"], "acceptance": {"reviewer_required": True}})
        return {"mission": self.ref("mission", "mission-1"), "purpose": "Produce the guide",
                "structure": {"mode": "adaptive"}, "roles": roles, "members": assignments, "contracts": contracts,
                "interfaces": [{"roles": ["writer", "reviewer"], "purpose": "Discuss and revise"}],
                "estimated_cost": {"amount": 10, "unit": "USD"}, "estimated_duration_ms": 10000,
                "risk_level": "low"}

    def team(self, identifier="team-1", actor="a-1"):
        if "mission:mission-1" not in self.state():
            self.mission()
        self.accept(self.command("team.propose", identifier, {"content": self.team_content()}, actor=actor))
        return self.candidate("team", identifier)

    def register(self, actor="a-3"):
        self.accept(self.command("agent.register", actor, {"model_id": "model-3", "status": "available"}, actor="bootstrap"))

    def revise_team(self, content, *, actor="a-2", **changes):
        body = {"base": self.ref("team", "team-1"), "content": content,
                "reason": "Cover the missing review capacity"}
        body.update(changes)
        return self.command("team.revise", "team-1", body, actor=actor)

    def task_content(self, identifier="write", dependencies=()):
        return {"id": identifier, "title": f"Prepare {identifier}", "type": "documentation", "milestone_id": "draft",
                "required_capabilities": ["writing"], "dependencies": copy.deepcopy(list(dependencies)), "inputs": [],
                "expected_outputs": ["Guide section"], "acceptance_criteria": ["Readable and sourced"]}

    def blueprint_content(self):
        return {"mission": self.ref("mission", "mission-1"), "team": self.ref("team", "team-1"),
                "requirements": ["Explain roles and recovery"], "architecture": "A single document with independent feedback",
                "technology": ["Markdown"], "components": ["Overview", "Recovery"],
                "milestones": [{"id": "draft", "title": "Draft guide"}],
                "tasks": [self.task_content("write"), self.task_content("review", [{"type": "task", "id": "write"}])],
                "risks": ["Unclear recovery wording"], "acceptance_criteria": ["Both topics covered"]}

    def blueprint(self, identifier="bp-1", content=None, **extra):
        if "team:team-1" not in self.state():
            self.team()
        body = {"content": content or self.blueprint_content()}
        body.update(extra)
        self.accept(self.command("blueprint.propose", identifier, body))
        return self.candidate("blueprint", identifier)

    def change(self, content, *, actor="a-2", **extra):
        body = {"change_id": f"change-{self.counter + 1}", "base": self.ref("blueprint", "bp-1"),
                "content": content, "reason": "Include a missing section", "risk_level": "medium",
                "estimated_cost": {"amount": 2, "unit": "USD"}, "estimated_delay_ms": 5000}
        body.update(extra)
        return self.command("blueprint.change.request", "bp-1", body, actor=actor)

    def control(self, action):
        return self.command(f"project.{action}", "p-1", {"intervention_id": f"int-{self.counter + 1}",
            "reason": "Human controls scheduling", "impact": "project"}, actor="human-owner")
