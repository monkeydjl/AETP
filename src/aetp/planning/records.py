"""Pure bounded proposal transitions. Nothing here assigns work or grants power."""

import copy
import math

from aetp.collaboration.messages import participant
from aetp.collaboration.policy import PolicyViolation, digest_value, strings, text
from aetp.governance.policy import current, fields, has_role, principal, revision
from aetp.meetings.policy import natural
from aetp.meetings.records import require_member
from aetp.planning.contracts import COMMAND_AGGREGATES, FORMAL_COMMANDS, SCHEMA
from aetp.planning.guards import candidate_scope
from aetp.planning.references import decisions, reference, resolve
from aetp.runtime.policy import observed_time


def amount(value):
    fields(value, {"amount", "unit"}, {"amount", "unit"})
    if (type(value["amount"]) not in (int, float) or not 0 <= value["amount"] <= 2**63 - 1
            or not math.isfinite(value["amount"])):
        raise PolicyViolation("INVALID_PAYLOAD")
    text(value["unit"], identifier=True, limit=64)
    return copy.deepcopy(value)


def risk(value):
    if not isinstance(value, str) or value not in {"low", "medium", "high", "critical"}:
        raise PolicyViolation("INVALID_PAYLOAD")
    return value


def configure(command, state, at):
    governance, policy = current(state, command.project_id)
    subject = principal(state, command.project_id, command.actor_id)
    if subject["type"] != "human" or not has_role(policy, command.actor_id, "human_owner"):
        raise PolicyViolation("PERMISSION_DENIED")
    if command.target_id != command.project_id:
        raise PolicyViolation("INVALID_TARGET")
    previous = state[f"project:{command.project_id}"]
    revision(command, previous)
    if previous["status"] == "paused":
        raise PolicyViolation("PROJECT_PAUSED")
    if previous["status"] not in {"planning", "active"}:
        raise PolicyViolation("PROJECT_INACTIVE")
    fields(command.payload, {"mode"}, {"mode"})
    if command.payload["mode"] != "candidate_only":
        raise PolicyViolation("INVALID_PAYLOAD")
    if "planning" in previous:
        raise PolicyViolation("PLANNING_ALREADY_CONFIGURED")
    if any(key.startswith("task:") for key in state):
        raise PolicyViolation("TASK_GRAPH_ALREADY_EXISTS")
    record = copy.deepcopy(previous)
    record.update(revision=previous["revision"] + 1, observed_at_ms=at)
    record["planning"] = {"schema": SCHEMA, "mode": "candidate_only", "configured_by": command.actor_id,
                          "origin_command_id": command.id, "policy_version": governance["current_version"]}
    return record


def mission_content(value):
    fields(value, {"title", "objective", "constraints", "success_criteria"},
           {"title", "objective", "constraints", "success_criteria"})
    text(value["title"], limit=512)
    text(value["objective"])
    strings(value["constraints"])
    strings(value["success_criteria"], required=True)
    return copy.deepcopy(value)


def team_content(value, state, project_id):
    required = {"mission", "purpose", "structure", "roles", "members", "contracts", "interfaces",
                "estimated_cost", "estimated_duration_ms", "risk_level"}
    fields(value, required, required)
    resolve(value["mission"], state, project_id, "mission")
    text(value["purpose"])
    fields(value["structure"], {"mode"}, {"mode"})
    if not isinstance(value["structure"]["mode"], str) or value["structure"]["mode"] not in {"flat", "network", "adaptive"}:
        raise PolicyViolation("INVALID_PAYLOAD")
    for field, limit in (("roles", 32), ("members", 32), ("contracts", 128), ("interfaces", 128)):
        if not isinstance(value[field], list) or len(value[field]) > limit or (field != "interfaces" and not value[field]):
            raise PolicyViolation("INVALID_TEAM")
    roles = set()
    for role in value["roles"]:
        fields(role, {"id", "name", "required_capabilities", "authority"}, {"id", "name", "required_capabilities", "authority"})
        identifier = text(role["id"], identifier=True, limit=512)
        text(role["name"], limit=512)
        strings(role["required_capabilities"], required=True)
        strings(role["authority"])
        if identifier in roles:
            raise PolicyViolation("INVALID_TEAM")
        roles.add(identifier)
    pairs, members, models = set(), set(), {}
    for member in value["members"]:
        fields(member, {"agent_id", "roles", "confidence"}, {"agent_id", "roles", "confidence"})
        actor = text(member["agent_id"], identifier=True, limit=512)
        assigned = strings(member["roles"], required=True)
        confidence = member["confidence"]
        if (actor in members or not participant(state, actor) or not set(assigned) <= roles
                or type(confidence) not in (int, float) or not 0 <= confidence <= 1 or not math.isfinite(confidence)):
            raise PolicyViolation("INVALID_TEAM")
        members.add(actor)
        models[actor] = state[f"agent:{actor}"]["model_id"]
        pairs.update((actor, role) for role in assigned)
    contracts = set()
    for contract in value["contracts"]:
        required = {"agent_id", "role_id", "responsibilities", "authority", "deliverables", "acceptance"}
        fields(contract, required, required)
        pair = (text(contract["agent_id"], identifier=True), text(contract["role_id"], identifier=True))
        if pair in contracts or pair not in pairs:
            raise PolicyViolation("INVALID_TEAM")
        contracts.add(pair)
        strings(contract["responsibilities"], required=True)
        strings(contract["deliverables"], required=True)
        fields(contract["authority"], {"can", "cannot"}, {"can", "cannot"})
        can, cannot = strings(contract["authority"]["can"]), strings(contract["authority"]["cannot"])
        if set(can) & set(cannot):
            raise PolicyViolation("INVALID_TEAM")
        fields(contract["acceptance"], {"reviewer_required"}, {"reviewer_required"})
        if contract["acceptance"]["reviewer_required"] is not True:
            raise PolicyViolation("INVALID_TEAM")
    if contracts != pairs or {role for _, role in pairs} != roles:
        raise PolicyViolation("INVALID_TEAM")
    edges = set()
    for interface in value["interfaces"]:
        fields(interface, {"roles", "purpose"}, {"roles", "purpose"})
        ends = strings(interface["roles"], required=True)
        text(interface["purpose"], limit=4096)
        if len(ends) != 2 or not set(ends) <= roles or tuple(sorted(ends)) in edges:
            raise PolicyViolation("INVALID_TEAM")
        edges.add(tuple(sorted(ends)))
    amount(value["estimated_cost"])
    natural(value["estimated_duration_ms"])
    risk(value["risk_level"])
    return copy.deepcopy(value), models


def append_version(command, previous, content, at, *, sources, details=None, reason=None):
    kind = COMMAND_AGGREGATES[command.type]
    version = previous["latest_proposal_version"] + 1 if previous else 1
    if version > 64:
        raise PolicyViolation("PROPOSAL_LIMIT_REACHED")
    old = previous["versions"][str(version - 1)] if previous else None
    candidate = {"schema_version": "0.1", "type": kind, "id": command.target_id, "project_id": command.project_id,
                 "version": version, "status": "proposed", "authority": "proposal_only", "untrusted_input": True,
                 "proposed_by": command.actor_id, "origin_command_id": command.id, "observed_at_ms": at,
                 "content": content, "source_decisions": sources, "reason": reason,
                 "supersedes": reference(old) if old else None}
    candidate.update(details or {})
    candidate["content_digest"] = digest_value(candidate)
    record = copy.deepcopy(previous) if previous else {
        "schema_version": "0.1", "id": command.target_id, "project_id": command.project_id,
        "kind": kind, "status": "forming" if kind == "team" else "proposed", "active_version": None,
        "versions": {}, "authority": "proposal_only"}
    record.update(revision=previous["revision"] + 1 if previous else 0, latest_proposal_version=version,
                  observed_at_ms=at, last_command_id=command.id)
    record["versions"][str(version)] = candidate
    return record


def evaluate(command, state, at):
    observed_time(state, at)
    if command.target_id is None:
        raise PolicyViolation("INVALID_TARGET")
    # Creation and subsequent version references share one byte contract.
    text(command.target_id, identifier=True, limit=512)
    if command.type == "project.planning.configure":
        return "project.planning_configured", configure(command, state, at)
    if command.type == "project.bootstrap.finalize":
        from aetp.bootstrap.records import evaluate_bootstrap_finalize
        return evaluate_bootstrap_finalize(command, state, at)
    if command.type in {
        "mission.activate",
        "mission.acceptance_start",
        "mission.verify",
        "mission.complete",
    }:
        previous = state.get(f"mission:{command.target_id}")
        revision(command, previous)
        if command.type == "mission.activate":
            from aetp.acceptance.mission import validate_mission_activate
            return validate_mission_activate(command, previous, state, at)
        if command.type == "mission.acceptance_start":
            from aetp.acceptance.mission import validate_mission_acceptance_start
            return validate_mission_acceptance_start(command, previous, state, at)
        if command.type == "mission.verify":
            require_member(state, command.project_id, command.actor_id)
            from aetp.acceptance.mission import validate_mission_verify
            return validate_mission_verify(command, previous, state, at)
        if command.type == "mission.complete":
            from aetp.acceptance.mission import evaluate_mission_delivery
            return evaluate_mission_delivery(command, previous, state, at)
    require_member(state, command.project_id, command.actor_id)
    if not candidate_scope(state, command.project_id):
        raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
    if command.type in FORMAL_COMMANDS:
        raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
    kind = COMMAND_AGGREGATES[command.type]
    previous = state.get(f"{kind}:{command.target_id}")
    revision(command, previous)
    if kind == "blueprint":
        from aetp.planning.blueprints import transition
        return transition(command, previous, state, at)
    if command.type in {"mission.propose", "team.propose"}:
        if previous is not None:
            raise PolicyViolation("REVISION_CONFLICT")
        fields(command.payload, {"content", "source_decisions"}, {"content"})
        source = decisions(command.payload.get("source_decisions", []), state, command.project_id)
        if kind == "mission":
            content, details = mission_content(command.payload["content"]), {}
        else:
            content, models = team_content(command.payload["content"], state, command.project_id)
            details = {"member_models": models, "qualification": "not_evaluated"}
        return f"{kind}.proposed", append_version(command, previous, content, at, sources=source, details=details)
    if command.type == "team.revise":
        if previous is None:
            raise PolicyViolation("INVALID_TARGET")
        fields(command.payload, {"base", "content", "reason", "source_decisions"}, {"base", "content", "reason"})
        old = resolve(command.payload["base"], state, command.project_id, "team")
        if old["id"] != command.target_id:
            raise PolicyViolation("INVALID_REFERENCE")
        content, models = team_content(command.payload["content"], state, command.project_id)
        if content["mission"] != old["content"]["mission"]:
            raise PolicyViolation("INVALID_REFERENCE")
        reason = text(command.payload["reason"])
        source = copy.deepcopy(old["source_decisions"])
        for entry in decisions(command.payload.get("source_decisions", []), state, command.project_id):
            if entry not in source:
                source.append(entry)
        before = {member["agent_id"] for member in old["content"]["members"]}
        after = set(models)
        details = {"member_models": models, "qualification": "not_evaluated",
                   "impact": {"added_members": sorted(after - before), "removed_members": sorted(before - after),
                              "scope": "candidate_team_only"}}
        return "team.proposal_revised", append_version(command, previous, content, at, sources=source,
                                                        details=details, reason=reason)
    raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
