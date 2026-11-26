"""Pure safety control facts; live recovery evidence is provided by the host."""

import copy

from aetp.collaboration.messages import participant
from aetp.collaboration.policy import PolicyViolation, canonical_json, text
from aetp.governance.causality import command_id
from aetp.governance.policy import current, fields, revision
from aetp.runtime.contracts import POLICY_VERSION, RUNTIME_ID
from aetp.runtime.policy import governance


def recovery_assessment(state, project_id, at, observations):
    """Pure prerequisites from facts and trusted live-session observations."""
    fields(observations, {"live_sessions", "pending_commands", "workspace_provider_id"},
           {"live_sessions", "pending_commands", "workspace_provider_id"})
    project = state[f"project:{project_id}"]
    sessions = observations["live_sessions"]
    if not isinstance(sessions, dict) or not isinstance(observations["pending_commands"], list):
        raise PolicyViolation("RECOVERY_REQUIRED")
    missing, expired, membership = [], [], []
    configured = "execution_policy_version" in project
    if configured and (project["execution_policy_version"] != POLICY_VERSION
            or observations["workspace_provider_id"] != project["workspace_provider_id"]):
        raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
    for key, task in state.items():
        if not key.startswith("task:") or not task.get("current_binding_id") or task.get("lease", {}).get("revoked"):
            continue
        if not configured or task.get("execution_policy_version") != POLICY_VERSION:
            raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
        lease = task.get("lease")
        if lease is None or lease["expires_at_governance_ms"] <= governance(project, at):
            expired.append(task["id"])
        if not participant(state, task["owner_id"]):
            membership.append(task["id"])
        binding = task["bindings"][task["current_binding_id"]]
        descriptor = binding["session"]
        if descriptor and (descriptor["expires_at_wall_ms"] <= at
                           or canonical_json(sessions.get(descriptor["id"])) != canonical_json(descriptor)):
            missing.append(descriptor["id"])
    unknown, invalid = [], []
    for key, action in state.items():
        if key.startswith("verification:") and action.get("action", {}).get("status") in {"in_flight", "unknown"}:
            unknown.append(action["action"]["id"])
        if not key.startswith("action:"):
            continue
        if action["status"] in {"in_flight", "unknown"}:
            unknown.append(action["id"])
        elif action["status"] == "pending":
            from aetp.governance.execution import authorize_action
            try:
                authorize_action(action, state, at)
            except PolicyViolation:
                invalid.append(action["id"])
    pending = observations["pending_commands"]
    if any(not isinstance(identifier, str) or not identifier for identifier in pending):
        raise PolicyViolation("RECOVERY_REQUIRED")
    return {"ready": not any((missing, expired, membership, unknown, invalid, pending)),
            "missing_sessions": sorted(missing), "expired_leases": sorted(expired), "membership_denied": sorted(membership),
            "unknown_actions": sorted(set(unknown)), "invalid_approvals": sorted(invalid), "pending_commands": sorted(pending),
            "runtime": RUNTIME_ID if configured else "not_configured", "observed_at_ms": at,
            "budget_scope": "fixed_bounded_document_operations_no_paid_calls"}


def project_control_input(command, state):
    fields(command.payload, {"intervention_id", "reason", "impact"}, {"intervention_id", "reason", "impact"})
    governance_config, value = current(state, command.project_id)
    if command.actor_id != governance_config["owner_id"]:
        raise PolicyViolation("PERMISSION_DENIED")
    project = state[f"project:{command.project_id}"]
    if command.target_id != command.project_id:
        raise PolicyViolation("INVALID_TARGET")
    revision(command, project)
    identifier = text(command.payload["intervention_id"], identifier=True)
    if f"intervention:{identifier}" in state:
        raise PolicyViolation("REVISION_CONFLICT")
    text(command.payload["reason"])
    text(command.payload["impact"], limit=512)
    if command.type == "project.pause" and project["status"] not in {"planning", "active"}:
        raise PolicyViolation("PROJECT_INACTIVE")
    if command.type == "project.resume" and project["status"] != "paused":
        raise PolicyViolation("PROJECT_NOT_PAUSED")
    return project


def project_control(command, previous, state, at, context):
    project_control_input(command, state)
    updated = copy.deepcopy(previous)
    updated.update(revision=previous["revision"] + 1, observed_at_ms=at)
    action = "pause" if command.type == "project.pause" else "resume"
    clock = copy.deepcopy(previous.get("collaboration_clock", {"excluded_ms": 0, "paused_at_ms": None}))
    if action == "pause":
        updated.update(status="paused", paused_from=previous["status"], dispatch_barrier="closed", execution_quiescence="unconfirmed")
        clock["paused_at_ms"] = at
        updated["binding_pause_status"] = {task["current_binding_id"]: {
            "task_id": task["id"], "lease_epoch": task["lease_epoch"], "pause_status": "unsupported",
            "reason": "fixed document Runtime cannot prove all execution quiescent"}
            for key, task in state.items() if key.startswith("task:") and task.get("current_binding_id") and not task["lease"]["revoked"]}
    else:
        observations = context.get("recovery_observations")
        if observations is None:
            raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
        checks = recovery_assessment(state, command.project_id, at, observations)
        if not checks["ready"]:
            raise PolicyViolation("RECOVERY_REQUIRED")
        if clock["paused_at_ms"] is None:
            raise PolicyViolation("RECOVERY_REQUIRED")
        clock["excluded_ms"] += at - clock["paused_at_ms"]
        clock["paused_at_ms"] = None
        updated.update(status=previous["paused_from"], dispatch_barrier="requires_host_recovery", resume_checks=checks)
    if "execution_clock" in previous:
        updated["execution_clock"] = {"elapsed_ms": governance(previous, at), "wall_anchor_ms": at}
    updated["collaboration_clock"] = clock
    updated["last_control"] = {"intervention_id": command.payload["intervention_id"],
        "actor": {"type": "human", "id": command.actor_id}, "action": action, "command": command.id,
        "target": {"type": "project", "id": command.project_id, "revision": previous["revision"]},
        "reason": command.payload["reason"], "impact": command.payload["impact"]}
    return "project.paused" if action == "pause" else "project.resumed", updated


def intervention(command, previous, state, at, context):
    if previous is not None:
        raise PolicyViolation("REVISION_CONFLICT")
    revision(command, None)
    if command.type == "intervention.record":
        fields(command.payload, set())
        control = state[f"project:{command.project_id}"].get("last_control")
        if (control is None or control["intervention_id"] != command.target_id
                or control["command"] != context.get("parent_command_id")):
            raise PolicyViolation("INVALID_REFERENCE")
        details = {key: copy.deepcopy(control[key]) for key in ("actor", "action", "command", "target", "reason", "impact")}
    else:
        fields(command.payload, {"action", "target", "reason", "impact"}, {"action", "target", "reason", "impact"})
        governance_config, value = current(state, command.project_id)
        if command.actor_id != governance_config["owner_id"]:
            raise PolicyViolation("PERMISSION_DENIED")
        if command.payload["action"] != "stop":
            raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
        target = command.payload["target"]
        fields(target, {"type", "id", "revision"}, {"type", "id", "revision"})
        if target["type"] != "task":
            raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
        task = state.get(f"task:{target['id']}")
        if task is None:
            raise PolicyViolation("INVALID_TARGET")
        if type(target["revision"]) is not int or task["revision"] != target["revision"]:
            raise PolicyViolation("REVISION_CONFLICT")
        details = {"actor": {"type": "human", "id": command.actor_id}, "action": "stop", "target": copy.deepcopy(target),
            "command": command_id(command.project_id, command.id, "task.governance.stop", target["id"]),
            "reason": text(command.payload["reason"]), "impact": text(command.payload["impact"], limit=512)}
    return "intervention.recorded", {"id": command.target_id, "project_id": command.project_id, "revision": 0,
                                      "observed_at_ms": at, "origin_command_id": command.id, **details}


def transition(command, previous, state, at, context):
    if command.type.startswith("intervention."):
        return intervention(command, previous, state, at, context)
    if previous is None:
        raise PolicyViolation("INVALID_TARGET")
    revision(command, previous)
    if command.type in {"project.pause", "project.resume"}:
        return project_control(command, previous, state, at, context)
    if command.type == "task.governance.stop":
        fields(command.payload, {"intervention_id"}, {"intervention_id"})
        governance_config, value = current(state, command.project_id)
        intervention_record = state.get(f"intervention:{command.payload['intervention_id']}")
        if (context.get("internal") is not True or command.actor_id != governance_config["owner_id"]
                or not intervention_record or intervention_record["actor"]["id"] != command.actor_id
                or intervention_record["command"] != command.id or intervention_record["target"]["id"] != previous["id"]
                or intervention_record["target"]["revision"] != previous["revision"]):
            raise PolicyViolation("PERMISSION_DENIED")
        if previous["status"] in {"completed", "cancelled", "failed"}:
            raise PolicyViolation("INVALID_TRANSITION")
        updated = copy.deepcopy(previous)
        updated.update(revision=previous["revision"] + 1, observed_at_ms=at, status="cancelled",
                       cancellation_reason=intervention_record["reason"], stopped_by=command.actor_id)
        if updated.get("lease"):
            updated["lease"]["revoked"] = True
            updated["bindings"][updated["current_binding_id"]]["status"] = "revoked"
        return "task.cancelled", updated
    if command.type == "task.governance.block":
        fields(command.payload, {"approval_id", "reason"}, {"approval_id", "reason"})
        approval = state.get(f"approval:{command.payload['approval_id']}")
        if (approval is None or approval["target"]["type"] != "task" or approval["target"]["id"] != previous["id"]
                or approval["status"] not in {"expired", "revoked"} or approval["risk_level"] not in {"high", "critical"}):
            raise PolicyViolation("INVALID_REFERENCE")
        if previous["status"] in {"completed", "cancelled", "failed"}:
            raise PolicyViolation("INVALID_TRANSITION")
        updated = copy.deepcopy(previous)
        updated.update(revision=previous["revision"] + 1, observed_at_ms=at, status="blocked",
                       blocked_from=previous.get("blocked_from", previous["status"]),
                       blocked_reason=command.payload["reason"], governance_approval_id=approval["id"])
        return "task.blocked", updated
    raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
