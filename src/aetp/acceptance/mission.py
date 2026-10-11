"""Mission Acceptance verification and delivery gate rules (TEST-010 / INV-019)."""

import copy

from aetp.collaboration.policy import PolicyViolation, text
from aetp.governance.policy import current, fields, has_role


def validate_mission_activate(command, previous, state, at):
    if previous is None:
        raise PolicyViolation("INVALID_TARGET")
    governance, policy = current(state, command.project_id)
    if not has_role(policy, command.actor_id, "human_owner"):
        raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
    if previous.get("status") not in {"proposed", "approved"}:
        raise PolicyViolation("INVALID_STATE")
    record = copy.deepcopy(previous)
    record.update(
        status="active",
        revision=previous["revision"] + 1,
        observed_at_ms=at,
        last_command_id=command.id,
        active_version=previous.get("latest_proposal_version")
    )
    return "mission.activated", record


def validate_mission_acceptance_start(command, previous, state, at):
    if previous is None:
        raise PolicyViolation("INVALID_TARGET")
    governance, policy = current(state, command.project_id)
    if not has_role(policy, command.actor_id, "human_owner"):
        raise PolicyViolation("PERMISSION_DENIED")
    if previous.get("status") != "active":
        raise PolicyViolation("INVALID_STATE")
    record = copy.deepcopy(previous)
    record.update(
        status="acceptance",
        revision=previous["revision"] + 1,
        observed_at_ms=at,
        last_command_id=command.id
    )
    if "criteria_verifications" not in record:
        record["criteria_verifications"] = {}
    return "mission.acceptance_started", record


def validate_mission_verify(command, previous, state, at):
    if previous is None:
        raise PolicyViolation("INVALID_TARGET")
    if previous.get("status") != "acceptance":
        raise PolicyViolation("MISSION_NOT_IN_ACCEPTANCE")
    fields(command.payload, {"criterion", "result", "evidence", "verifier_id"},
           {"criterion", "result", "evidence", "verifier_id"})
    active_ver = str(previous.get("active_version") or previous.get("latest_proposal_version"))
    content = previous.get("versions", {}).get(active_ver, {}).get("content", {})
    criteria = content.get("success_criteria", [])
    criterion = command.payload["criterion"]
    if criterion not in criteria:
        raise PolicyViolation("INVALID_CRITERION")
    result = command.payload["result"]
    if result not in {"PASSED", "FAILED", "INCONCLUSIVE"}:
        raise PolicyViolation("INVALID_PAYLOAD")
    evidence = command.payload["evidence"]
    if not isinstance(evidence, dict) or not evidence.get("artifact_id") or not evidence.get("content_digest"):
        raise PolicyViolation("INVALID_PAYLOAD")
    record = copy.deepcopy(previous)
    record.update(
        revision=previous["revision"] + 1,
        observed_at_ms=at,
        last_command_id=command.id
    )
    if "criteria_verifications" not in record:
        record["criteria_verifications"] = {}
    record["criteria_verifications"][criterion] = {
        "result": result,
        "evidence": copy.deepcopy(evidence),
        "verifier_id": command.payload["verifier_id"],
        "verified_at_ms": at
    }
    return "mission.criteria_verified", record


def evaluate_mission_delivery(command, previous, state, at):
    if previous is None:
        raise PolicyViolation("INVALID_TARGET")
    if previous.get("status") != "acceptance":
        raise PolicyViolation("MISSION_NOT_IN_ACCEPTANCE")
    active_ver = str(previous.get("active_version") or previous.get("latest_proposal_version"))
    content = previous.get("versions", {}).get(active_ver, {}).get("content", {})
    criteria = content.get("success_criteria", [])
    verifications = previous.get("criteria_verifications", {})
    for c in criteria:
        if c not in verifications or verifications[c].get("result") != "PASSED":
            raise PolicyViolation("CRITERIA_UNVERIFIED")
    governance, policy = current(state, command.project_id)
    if not has_role(policy, command.actor_id, "human_owner"):
        raise PolicyViolation("CRITICAL_APPROVAL_REQUIRED")
    record = copy.deepcopy(previous)
    record.update(
        status="completed",
        revision=previous["revision"] + 1,
        observed_at_ms=at,
        last_command_id=command.id
    )
    return "mission.completed", record
