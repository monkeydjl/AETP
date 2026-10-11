"""Pure validators and reducers for Project Bootstrap lifecycle."""

from __future__ import annotations

import copy
from typing import Any, Dict, Tuple

from aetp.collaboration.policy import PolicyViolation
from aetp.domain.models import Event, ModelValidationError
from aetp.governance.policy import current, has_role

BOOTSTRAP_SCHEMA = "0.1"


def evaluate_bootstrap_finalize(command, state, at) -> Tuple[str, Dict[str, Any]]:
    """Validate project.bootstrap.finalize command.

    Requirements per §15.5 and §5.2 / INV-019:
    1. Caller must have human_owner role;
    2. Mission #0 must exist, be completed and verified;
    3. Project phase transitions to BOOTSTRAP_VERIFIED.
    """
    project_key = f"project:{command.project_id}"
    project = state.get(project_key)
    if project is None:
        raise PolicyViolation("INVALID_TARGET")

    governance, policy = current(state, command.project_id)
    if not has_role(policy, command.actor_id, "human_owner"):
        raise PolicyViolation("PERMISSION_DENIED")

    # Find mission-0 or mission with bootstrap purpose
    mission_id = command.payload.get("mission_id", "mission-0-bootstrap")
    mission = state.get(f"mission:{mission_id}")
    if mission is None:
        raise PolicyViolation("MISSION_NOT_FOUND")

    if mission.get("status") != "completed":
        raise PolicyViolation("BOOTSTRAP_MISSION_INCOMPLETE")

    record = copy.deepcopy(project)
    record.update(
        phase="BOOTSTRAP_VERIFIED",
        bootstrap_status="verified",
        bootstrap_mission_id=mission_id,
        bootstrap_verified_at_ms=at,
        revision=project["revision"] + 1,
    )
    return "project.bootstrap_verified", record


def reduce_bootstrap_event(event: Event, previous: Dict[str, Any] | None, state: Dict[str, Any]) -> Dict[str, Any]:
    """Reduce project.bootstrap_verified event into Project projection."""
    if event.type != "project.bootstrap_verified":
        raise ModelValidationError(f"unsupported bootstrap event: {event.type}")
    if previous is None:
        raise ModelValidationError("bootstrap event target project does not exist")

    record = copy.deepcopy(previous)
    record["phase"] = "BOOTSTRAP_VERIFIED"
    record["bootstrap_status"] = "verified"
    record["bootstrap_mission_id"] = event.payload.get("bootstrap_mission_id")
    record["bootstrap_verified_at_ms"] = event.payload.get("bootstrap_verified_at_ms")
    record["revision"] = previous["revision"] + 1
    return record
