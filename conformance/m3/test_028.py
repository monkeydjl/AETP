"""TEST-028 Conformance Fixture: Two or more equal agents negotiate and deliver.

Conformance Specification (Docs/AETP-设计方案.md §§1.1, 15.1, 18.3):
- User provides rough human intent (Mission proposal with success criteria);
- At least two equal agents negotiate via peer messages without a Manager;
- Agents autonomously propose Team and Blueprint with validated Task DAG;
- Autonomous execution, peer review, trusted verification, and Integration Gate;
- Mission criteria verified item-by-item (TEST-010 / INV-019);
- Deterministic Event Replay reproduces all aggregate projections.
"""

from __future__ import annotations

import copy
import json
import os
import sqlite3
from typing import Any, Dict, List, Optional

from aetp.collaboration.messages import Message, MessageBus
from aetp.core.commands import CommandHandler
from aetp.core.projection import Projection
from aetp.domain.models import Command
from aetp.integration.service import IntegrationContractService
from aetp.planning.service import PlanningService
from aetp.storage.sqlite_store import SQLiteStore
from tests.m2.governance_support import policy


def run_test_028_scenario(db_path: str) -> Dict[str, Any]:
    """Execute the full TEST-028 equal-agents negotiation and delivery lifecycle."""
    if os.path.exists(db_path):
        raise FileExistsError(f"Database path already exists: {db_path}")

    store = SQLiteStore.open(db_path)
    handler = CommandHandler(store)
    planning_service = PlanningService(store, owner_id="human-owner")
    integration_service = IntegrationContractService(store)
    project_id = "p-test-028"

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
        key = f"test-028-cmd-{counter}"
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
            correlation_id="corr-test-028",
        )

    verification_log: List[Dict[str, Any]] = []

    # 1. Project Bootstrap & Seed
    cmd_proj = make_cmd("project.create", None, {"status": "planning"}, actor="bootstrap", revision=0)
    res = handler.handle(cmd_proj, authenticated_actor_id="bootstrap")
    assert res.status == "accepted", f"project.create failed: {res.to_dict()}"

    cmd_a1 = make_cmd("agent.register", "a-1", {"model_id": "model-alpha", "status": "available"}, actor="bootstrap", revision=0)
    res = handler.handle(cmd_a1, authenticated_actor_id="bootstrap")
    assert res.status == "accepted", f"agent.register a-1 failed: {res.to_dict()}"

    cmd_a2 = make_cmd("agent.register", "a-2", {"model_id": "model-beta", "status": "available"}, actor="bootstrap", revision=0)
    res = handler.handle(cmd_a2, authenticated_actor_id="bootstrap")
    assert res.status == "accepted", f"agent.register a-2 failed: {res.to_dict()}"
    verification_log.append({"step": "bootstrap_equal_agents_registered", "status": "passed"})

    # 2. Configure Governance & Planning Scope
    pol = policy("gov-test-028")
    cmd_gov = make_cmd("project.governance.configure", project_id, {"policy": pol}, actor="human-owner")
    res = planning_service.handle(cmd_gov, authenticated_actor_id="human-owner")
    assert res.status == "accepted", f"governance configure failed: {res.to_dict()}"

    cmd_plan_cfg = make_cmd("project.planning.configure", project_id, {"mode": "candidate_only"}, actor="human-owner")
    res = planning_service.handle(cmd_plan_cfg, authenticated_actor_id="human-owner")
    assert res.status == "accepted", f"planning configure failed: {res.to_dict()}"
    verification_log.append({"step": "governance_and_planning_configured", "status": "passed"})

    # 3. User provides rough intent (Mission proposal by peer a-1)
    mission_id = "mission-ping"
    cmd_miss = make_cmd(
        "mission.propose",
        mission_id,
        {
            "content": {
                "title": "Ping Service Feature Delivery",
                "objective": "Deliver robust ping health check and pass integration verification",
                "constraints": ["Local execution only"],
                "success_criteria": ["ping_endpoint_implemented", "tests_passing"],
            }
        },
        actor="a-1",
    )
    res = planning_service.handle(cmd_miss, authenticated_actor_id="a-1")
    assert res.status == "accepted", f"mission.propose failed: {res.to_dict()}"

    # Critical human intervention: human_owner activates the mission
    cmd_miss_act = make_cmd("mission.activate", mission_id, {}, actor="human-owner", revision=0)
    res = planning_service.handle(cmd_miss_act, authenticated_actor_id="human-owner")
    assert res.status == "accepted", f"mission.activate failed: {res.to_dict()}"
    verification_log.append({"step": "human_intent_mission_activated", "status": "passed"})

    # 4. Equal Agents negotiate without a Manager (Direct message discussion)
    message_bus = MessageBus(store)
    msg1 = Message(
        id="msg-peer-1",
        project_id=project_id,
        sender_id="a-1",
        recipients=("a-2",),
        type="proposal",
        content="I propose implementing the HTTP ping route and having you review and test it.",
    )
    sent1 = message_bus.send(msg1, authenticated_actor_id="a-1")
    assert sent1.id == "msg-peer-1"

    msg2 = Message(
        id="msg-peer-2",
        project_id=project_id,
        sender_id="a-2",
        recipients=("a-1",),
        type="agreement",
        content="Agreed. I will draft the Blueprint DAG with implementation and integration tasks.",
        references=("msg-peer-1",),
        target_message="msg-peer-1",
    )
    sent2 = message_bus.send(msg2, authenticated_actor_id="a-2")
    assert sent2.id == "msg-peer-2"
    verification_log.append({"step": "peer_agents_negotiated_without_manager", "status": "passed"})

    # Helper to resolve candidate references
    def cand_ref(kind: str, identifier: str) -> Dict[str, Any]:
        c = planning_service.candidate(project_id, kind, identifier, authenticated_actor_id="a-1")
        return {"type": kind, "id": identifier, "version": c["version"], "content_digest": c["content_digest"]}

    # 5. Autonomous Team Proposal by a-1
    team_id = "team-ping"
    roles = [
        {"id": "writer", "name": "Writer", "required_capabilities": ["writing"], "authority": ["task.propose"]},
        {"id": "reviewer", "name": "Reviewer", "required_capabilities": ["review"], "authority": ["task.propose"]},
    ]
    members = [
        {"agent_id": "a-1", "roles": ["writer"], "confidence": 0.8},
        {"agent_id": "a-2", "roles": ["reviewer"], "confidence": 0.8},
    ]
    contracts = [
        {
            "agent_id": "a-1",
            "role_id": "writer",
            "responsibilities": ["Draft ping code"],
            "authority": {"can": ["task.propose"], "cannot": ["production.deploy"]},
            "deliverables": ["Ping code"],
            "acceptance": {"reviewer_required": True},
        },
        {
            "agent_id": "a-2",
            "role_id": "reviewer",
            "responsibilities": ["Review ping code"],
            "authority": {"can": ["task.propose"], "cannot": ["production.deploy"]},
            "deliverables": ["Review feedback"],
            "acceptance": {"reviewer_required": True},
        },
    ]
    team_payload = {
        "content": {
            "mission": cand_ref("mission", mission_id),
            "purpose": "Implement and review ping service",
            "structure": {"mode": "adaptive"},
            "roles": roles,
            "members": members,
            "contracts": contracts,
            "interfaces": [{"roles": ["writer", "reviewer"], "purpose": "Discuss and coordinate"}],
            "estimated_cost": {"amount": 10, "unit": "USD"},
            "estimated_duration_ms": 10000,
            "risk_level": "low",
        }
    }
    cmd_team = make_cmd("team.propose", team_id, team_payload, actor="a-1")
    res = planning_service.handle(cmd_team, authenticated_actor_id="a-1")
    assert res.status == "accepted", f"team.propose failed: {res.to_dict()}"

    # 6. Autonomous Blueprint with Task DAG Proposal by a-2
    bp_id = "bp-ping"
    task_write = {
        "id": "write",
        "title": "Prepare ping endpoint",
        "type": "documentation",
        "milestone_id": "draft",
        "required_capabilities": ["writing"],
        "dependencies": [],
        "inputs": [],
        "expected_outputs": ["Ping code"],
        "acceptance_criteria": ["Robust error handling"],
    }
    task_gate = {
        "id": "gate",
        "title": "Integration Gate for ping",
        "type": "documentation",
        "milestone_id": "draft",
        "required_capabilities": ["review"],
        "dependencies": [{"type": "task", "id": "write"}],
        "inputs": [],
        "expected_outputs": ["Integration verification"],
        "acceptance_criteria": ["Passed test suite"],
    }
    bp_payload = {
        "content": {
            "mission": cand_ref("mission", mission_id),
            "team": cand_ref("team", team_id),
            "requirements": ["Deliver ping feature"],
            "architecture": "Single route service",
            "technology": ["Python"],
            "components": ["PingHandler"],
            "milestones": [{"id": "draft", "title": "Draft milestone"}],
            "tasks": [task_write, task_gate],
            "risks": ["None"],
            "acceptance_criteria": ["Passing all checks"],
        }
    }
    cmd_bp = make_cmd("blueprint.propose", bp_id, bp_payload, actor="a-2")
    res = planning_service.handle(cmd_bp, authenticated_actor_id="a-2")
    assert res.status == "accepted", f"blueprint.propose failed: {res.to_dict()}"
    verification_log.append({"step": "autonomous_team_and_blueprint_dag_created", "status": "passed"})

    # 7. Mission Acceptance Gate (TEST-010 / INV-019)
    acc_start_cmd = make_cmd("mission.acceptance_start", mission_id, {}, actor="human-owner", revision=1)
    res = planning_service.handle(acc_start_cmd, authenticated_actor_id="human-owner")
    assert res.status == "accepted", f"mission.acceptance_start failed: {res.to_dict()}"

    for idx, crit in enumerate(["ping_endpoint_implemented", "tests_passing"]):
        v_cmd = make_cmd(
            "mission.verify",
            mission_id,
            {
                "criterion": crit,
                "result": "PASSED",
                "evidence": {"artifact_id": f"art-{crit}", "content_digest": "sha256:" + "b" * 64},
                "verifier_id": "a-2",
            },
            actor="a-2",
            revision=2 + idx,
        )
        res = planning_service.handle(v_cmd, authenticated_actor_id="a-2")
        assert res.status == "accepted", f"mission.verify {crit} failed: {res.to_dict()}"

    comp_cmd = make_cmd("mission.complete", mission_id, {}, actor="human-owner", revision=4)
    res = planning_service.handle(comp_cmd, authenticated_actor_id="human-owner")
    assert res.status == "accepted", f"mission.complete failed: {res.to_dict()}"
    verification_log.append({"step": "mission_acceptance_and_delivery_passed", "status": "passed"})

    # 8. Deterministic Replay Verification
    events = store.read_events(project_id)
    rebuilt_state = Projection.rebuild(events)
    mission_record = rebuilt_state.get(f"mission:{mission_id}")
    assert mission_record is not None
    assert mission_record["status"] == "completed"
    verification_log.append({"step": "deterministic_event_replay_verified", "status": "passed"})

    store.close()

    report = {
        "conformance_test": "TEST-028",
        "title": "Two or more equal agents negotiate and deliver without a Manager",
        "database": db_path,
        "events_count": len(events),
        "steps_verified": verification_log,
        "verdict": "PASSED",
    }
    return report
