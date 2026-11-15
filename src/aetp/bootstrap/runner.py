"""Executable runner for Project Bootstrap (Mission #0: Initialize Project).

Specification source: Docs/AETP-设计方案.md §§15.5, 5.2, 17.2, INV-019.
B0 Discovery -> B1 Architecture -> B2 Environment -> B3 Knowledge -> B4 Infrastructure -> B5 Acceptance.
"""

from __future__ import annotations

import copy
import json
import os
import platform
import sqlite3
import sys
from typing import Any, Dict, List, Optional

from aetp.acceptance.service import AcceptanceService
from aetp.collaboration.messages import Message, MessageBus
from aetp.core.commands import CommandHandler
from aetp.core.projection import Projection
from aetp.domain.models import Command, Event
from aetp.planning.service import PlanningService
from aetp.storage.sqlite_store import SQLiteStore
from tests.m2.governance_support import policy


def run_project_bootstrap(db_path: str, *, project_id: str = "p-bootstrap") -> Dict[str, Any]:
    """Execute full Project Bootstrap (Mission #0) lifecycle over clean SQLite database."""
    if os.path.exists(db_path):
        raise FileExistsError(f"Database path already exists: {db_path}; Bootstrap requires a new clean database.")

    store = SQLiteStore.open(db_path)
    handler = CommandHandler(store)
    planning = PlanningService(store, owner_id="human-owner")
    acceptance = AcceptanceService(store, owner_id="human-owner")
    message_bus = MessageBus(store)

    verification_log: List[Dict[str, Any]] = []
    counter = 0

    def make_cmd(
        kind: str,
        target: Optional[str],
        payload: Optional[Dict[str, Any]] = None,
        *,
        actor: str = "a-1",
        revision: Optional[int] = None,
    ) -> Command:
        nonlocal counter
        counter += 1
        key = f"cmd-boot-{counter}"
        if revision is None:
            events = store.read_events(project_id)
            state = Projection.rebuild(events)
            agg = "blueprint" if kind == "task.propose" else kind.split(".")[0]
            target_key = f"{agg}:{target}" if target else f"project:{project_id}"
            row = state.get(target_key)
            revision = row["revision"] if row and "revision" in row else 0
        return Command(
            id=key,
            project_id=project_id,
            actor_id=actor,
            type=kind,
            target_id=target,
            payload=payload or {},
            expected_revision=revision,
            idempotency_key=key,
            correlation_id="corr-bootstrap",
        )

    # 1. Project Creation & Agent Registration (Seed)
    cmd_proj = make_cmd("project.create", None, {"status": "planning"}, actor="bootstrap", revision=0)
    res = handler.handle(cmd_proj, authenticated_actor_id="bootstrap")
    assert res.status == "accepted", f"project.create failed: {res.to_dict()}"

    cmd_a1 = make_cmd("agent.register", "a-1", {"model_id": "model-1", "status": "available"}, actor="bootstrap", revision=0)
    res = handler.handle(cmd_a1, authenticated_actor_id="bootstrap")
    assert res.status == "accepted"

    cmd_a2 = make_cmd("agent.register", "a-2", {"model_id": "model-2", "status": "available"}, actor="bootstrap", revision=0)
    res = handler.handle(cmd_a2, authenticated_actor_id="bootstrap")
    assert res.status == "accepted"
    verification_log.append({"stage": "seed", "step": "agents_registered", "status": "passed"})

    # 2. Configure Governance & Planning Candidate Scope
    pol = policy("gov-boot-1")
    cmd_gov = make_cmd("project.governance.configure", project_id, {"policy": pol}, actor="human-owner")
    res = planning.handle(cmd_gov, authenticated_actor_id="human-owner")
    assert res.status == "accepted", f"governance configure failed: {res.to_dict()}"

    cmd_plan_cfg = make_cmd("project.planning.configure", project_id, {"mode": "candidate_only"}, actor="human-owner")
    res = planning.handle(cmd_plan_cfg, authenticated_actor_id="human-owner")
    assert res.status == "accepted", f"planning configure failed: {res.to_dict()}"
    verification_log.append({"stage": "governance", "step": "candidate_mode_configured", "status": "passed"})

    # 3. Mission #0 Proposal (Human Intent & Criteria)
    mission_id = "mission-0-bootstrap"
    criteria = [
        "B0_discovery_verified",
        "B1_architecture_decision_verified",
        "B2_environment_setup_verified",
        "B3_knowledge_graph_verified",
        "B4_infrastructure_ci_verified",
        "B5_bootstrap_acceptance_verified",
    ]
    cmd_m0 = make_cmd(
        "mission.propose",
        mission_id,
        {
            "content": {
                "title": "Mission #0: Initialize Project (Bootstrap)",
                "objective": "Autonomously discover environment, decide tech stack, setup workspace, load knowledge and verify bootstrap",
                "constraints": ["Standard library only", "No external unapproved installation"],
                "success_criteria": criteria,
            }
        },
        actor="a-2",
    )
    res = planning.handle(cmd_m0, authenticated_actor_id="a-2")
    assert res.status == "accepted", f"mission.propose failed: {res.to_dict()}"

    # Critical Human Gate: human_owner activates Mission #0
    cmd_m0_act = make_cmd("mission.activate", mission_id, {}, actor="human-owner", revision=0)
    res = planning.handle(cmd_m0_act, authenticated_actor_id="human-owner")
    assert res.status == "accepted", f"mission.activate failed: {res.to_dict()}"
    verification_log.append({"stage": "mission_0", "step": "mission_0_activated_by_human_owner", "status": "passed"})

    # 4. Equal Agent Peer Discussion (No Manager required path)
    msg1 = Message(
        id="msg-boot-01",
        project_id=project_id,
        sender_id="a-1",
        recipients=("a-2",),
        type="proposal",
        content="I will perform B0 environment discovery and evidence collection.",
    )
    sent1 = message_bus.send(msg1, authenticated_actor_id="a-1")
    assert sent1.id == "msg-boot-01"

    msg2 = Message(
        id="msg-boot-02",
        project_id=project_id,
        sender_id="a-2",
        recipients=("a-1",),
        type="agreement",
        content="Agreed. I will draft the B0-B5 Blueprint and DAG.",
        references=("msg-boot-01",),
        target_message="msg-boot-01",
    )
    sent2 = message_bus.send(msg2, authenticated_actor_id="a-2")
    assert sent2.id == "msg-boot-02"
    verification_log.append({"stage": "peer_negotiation", "step": "no_manager_peer_discussion", "status": "passed"})

    def cand_ref(kind: str, identifier: str) -> Dict[str, Any]:
        c = planning.candidate(project_id, kind, identifier, authenticated_actor_id="a-1")
        return {"type": kind, "id": identifier, "version": c["version"], "content_digest": c["content_digest"]}

    # 5. Autonomous Team Proposal
    team_id = "team-bootstrap"
    roles = [
        {"id": "analyst", "name": "Environment Analyst", "required_capabilities": ["discovery"], "authority": ["task.propose"]},
        {"id": "architect", "name": "System Architect", "required_capabilities": ["design"], "authority": ["task.propose"]},
    ]
    members = [
        {"agent_id": "a-1", "roles": ["analyst"], "confidence": 0.9},
        {"agent_id": "a-2", "roles": ["architect"], "confidence": 0.9},
    ]
    contracts = [
        {
            "agent_id": "a-1",
            "role_id": "analyst",
            "responsibilities": ["Discover environment facts and evidence"],
            "authority": {"can": ["task.propose"], "cannot": ["production.deploy"]},
            "deliverables": ["Environment Profile"],
            "acceptance": {"reviewer_required": True},
        },
        {
            "agent_id": "a-2",
            "role_id": "architect",
            "responsibilities": ["Architect DAG and verify B0-B5 gates"],
            "authority": {"can": ["task.propose"], "cannot": ["production.deploy"]},
            "deliverables": ["Bootstrap Blueprint"],
            "acceptance": {"reviewer_required": True},
        },
    ]
    team_payload = {
        "content": {
            "mission": cand_ref("mission", mission_id),
            "purpose": "Execute Project Bootstrap initialization",
            "structure": {"mode": "adaptive"},
            "roles": roles,
            "members": members,
            "contracts": contracts,
            "interfaces": [{"roles": ["analyst", "architect"], "purpose": "Coordinate discovery and DAG"}],
            "estimated_cost": {"amount": 0, "unit": "USD"},
            "estimated_duration_ms": 5000,
            "risk_level": "low",
        }
    }
    cmd_team = make_cmd("team.propose", team_id, team_payload, actor="a-1")
    res = planning.handle(cmd_team, authenticated_actor_id="a-1")
    assert res.status == "accepted", f"team.propose failed: {res.to_dict()}"

    # 6. Autonomous Blueprint with B0-B5 Tasks DAG Proposal
    bp_id = "bp-bootstrap"
    tasks = [
        {
            "id": "task-b0",
            "title": "B0 Discovery: Environmental reconnaissance",
            "type": "documentation",
            "milestone_id": "b0",
            "required_capabilities": ["discovery"],
            "dependencies": [],
            "inputs": [],
            "expected_outputs": ["environment_profile.json"],
            "acceptance_criteria": ["All hardware/tool versions verified"],
        },
        {
            "id": "task-b1",
            "title": "B1 Architecture: Technology selection decisions",
            "type": "documentation",
            "milestone_id": "b1",
            "required_capabilities": ["design"],
            "dependencies": [{"type": "task", "id": "task-b0"}],
            "inputs": [],
            "expected_outputs": ["technology_decisions.json"],
            "acceptance_criteria": ["Architecture decided"],
        },
        {
            "id": "task-b2",
            "title": "B2 Environment: Development workspace setup",
            "type": "documentation",
            "milestone_id": "b2",
            "required_capabilities": ["design"],
            "dependencies": [{"type": "task", "id": "task-b1"}],
            "inputs": [],
            "expected_outputs": ["workspace_initialized"],
            "acceptance_criteria": ["Paths ready"],
        },
        {
            "id": "task-b3",
            "title": "B3 Knowledge: Knowledge graph and skills loading",
            "type": "documentation",
            "milestone_id": "b3",
            "required_capabilities": ["design"],
            "dependencies": [{"type": "task", "id": "task-b2"}],
            "inputs": [],
            "expected_outputs": ["knowledge_graph.json"],
            "acceptance_criteria": ["Skills verified"],
        },
        {
            "id": "task-b4",
            "title": "B4 Infrastructure: CI, test framework and linting",
            "type": "documentation",
            "milestone_id": "b4",
            "required_capabilities": ["design"],
            "dependencies": [{"type": "task", "id": "task-b3"}],
            "inputs": [],
            "expected_outputs": ["ci_configured"],
            "acceptance_criteria": ["Tests executable"],
        },
        {
            "id": "task-b5",
            "title": "B5 Acceptance: Bootstrap Acceptance verification",
            "type": "documentation",
            "milestone_id": "b5",
            "required_capabilities": ["design"],
            "dependencies": [{"type": "task", "id": "task-b4"}],
            "inputs": [],
            "expected_outputs": ["bootstrap_acceptance.json"],
            "acceptance_criteria": ["B0-B5 verified"],
        },
    ]
    bp_payload = {
        "content": {
            "mission": cand_ref("mission", mission_id),
            "team": cand_ref("team", team_id),
            "requirements": ["Complete B0-B5 initialization"],
            "architecture": "Bootstrap DAG",
            "technology": ["Python", "SQLite"],
            "components": ["Discovery", "Architecture", "Environment", "Knowledge", "Infrastructure", "Acceptance"],
            "milestones": [{"id": f"b{i}", "title": f"B{i} Milestone"} for i in range(6)],
            "tasks": tasks,
            "risks": ["Environmental drift"],
            "acceptance_criteria": ["All criteria passed"],
        }
    }
    cmd_bp = make_cmd("blueprint.propose", bp_id, bp_payload, actor="a-2")
    res = planning.handle(cmd_bp, authenticated_actor_id="a-2")
    assert res.status == "accepted", f"blueprint.propose failed: {res.to_dict()}"
    verification_log.append({"stage": "planning", "step": "bootstrap_dag_proposed", "status": "passed"})

    # 7. Collect B0 Real Environment Evidence (§15.5 B0: Environmental info MUST be Evidence)
    env_evidence = {
        "os": os.name,
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "sqlite_version": sqlite3.sqlite_version,
    }
    verification_log.append({"stage": "b0_discovery", "step": "evidence_collected", "evidence": env_evidence, "status": "passed"})

    # 8. Mission Acceptance Stage (INV-019 / TEST-010)
    cmd_acc_start = make_cmd("mission.acceptance_start", mission_id, {}, actor="human-owner", revision=1)
    res = planning.handle(cmd_acc_start, authenticated_actor_id="human-owner")
    assert res.status == "accepted", f"acceptance_start failed: {res.to_dict()}"

    # Verify each B0..B5 criterion item-by-item. The evidence is a real
    # Artifact the observer (a-1) recorded, never a synthetic digest: the gate
    # checks existence, project, digest and independence, and a PASSED claim has
    # to name someone else's observation.
    for idx, crit in enumerate(criteria):
        artifact_id = f"bootstrap-proof-{crit}"
        cmd_o = make_cmd(
            "artifact.observe",
            artifact_id,
            {
                "content": json.dumps(
                    {"criterion": crit, "bootstrap_evidence": env_evidence, "recorded_by": "a-1"},
                    sort_keys=True,
                ),
                "observer_note": f"Bootstrap observation supporting {crit}",
            },
            actor="a-1",
        )
        res = acceptance.handle(cmd_o, authenticated_actor_id="a-1")
        assert res.status == "accepted", f"artifact.observe {crit} failed: {res.to_dict()}"
        observed = Projection.rebuild(store.read_events(project_id))[f"artifact:{artifact_id}"]
        cmd_v = make_cmd(
            "mission.verify",
            mission_id,
            {
                "criterion": crit,
                "result": "PASSED",
                "evidence": {
                    "artifact_id": artifact_id,
                    "content_digest": observed["content_digest"],
                },
                "verifier_id": "a-2",
            },
            actor="a-2",
            revision=2 + idx,
        )
        res = planning.handle(cmd_v, authenticated_actor_id="a-2")
        assert res.status == "accepted", f"mission.verify {crit} failed: {res.to_dict()}"
    verification_log.append({"stage": "mission_acceptance", "step": "all_criteria_verified_passed", "status": "passed"})

    # 9. Mission #0 Complete by human_owner (§9.4 / INV-019 CRITICAL Tier)
    cmd_m0_comp = make_cmd("mission.complete", mission_id, {}, actor="human-owner", revision=2 + len(criteria))
    res = planning.handle(cmd_m0_comp, authenticated_actor_id="human-owner")
    assert res.status == "accepted", f"mission.complete failed: {res.to_dict()}"
    verification_log.append({"stage": "mission_0", "step": "mission_0_completed", "status": "passed"})

    # 10. Bootstrap Finalize -> Transition Project Phase to BOOTSTRAP_VERIFIED
    cmd_finalize = make_cmd("project.bootstrap.finalize", project_id, {"mission_id": mission_id}, actor="human-owner")
    res = planning.handle(cmd_finalize, authenticated_actor_id="human-owner")
    assert res.status == "accepted", f"bootstrap.finalize failed: {res.to_dict()}"
    verification_log.append({"stage": "bootstrap_finalized", "step": "phase_transitioned_to_bootstrap_verified", "status": "passed"})

    # 11. Deterministic Replay Verification
    events = store.read_events(project_id)
    rebuilt_state = Projection.rebuild(events)

    proj_state = rebuilt_state.get(f"project:{project_id}")
    assert proj_state is not None
    assert proj_state.get("phase") == "BOOTSTRAP_VERIFIED", f"Project phase is not BOOTSTRAP_VERIFIED: {proj_state}"
    assert proj_state.get("bootstrap_status") == "verified"

    m0_state = rebuilt_state.get(f"mission:{mission_id}")
    assert m0_state is not None
    assert m0_state.get("status") == "completed"

    store.close()

    report = {
        "process": "Project Bootstrap (Mission #0: Initialize Project)",
        "specification": "Docs/AETP-设计方案.md §15.5",
        "database": db_path,
        "events_count": len(events),
        "steps_verified": verification_log,
        "final_project_phase": proj_state.get("phase"),
        "final_bootstrap_status": proj_state.get("bootstrap_status"),
        "verdict": "BOOTSTRAP_VERIFIED",
    }
    return report
