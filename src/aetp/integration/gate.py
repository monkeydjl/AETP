"""Pure validation and guard functions for Integration Gate transitions."""
from aetp.collaboration.policy import PolicyViolation


def validate_integration_ready(task, contract):
    """Validate transition from verified to ready_for_integration."""
    if task["status"] != "verified":
        raise PolicyViolation("INVALID_TASK_STATUS")
    tasks = contract.get("tasks", {})
    entry = tasks.get(task["id"])
    if not entry or not entry.get("current_version"):
        raise PolicyViolation("INTEGRATION_NOT_DECLARED")
    version_data = entry["versions"].get(str(entry["current_version"]), {})
    if version_data.get("requirement") != "required":
        raise PolicyViolation("INTEGRATION_NOT_DECLARED")


def validate_merge(task, payload):
    """Validate git.merge execution parameters and baseline freshness (TEST-024)."""
    if task["status"] != "ready_for_integration":
        raise PolicyViolation("INVALID_TASK_STATUS")
    expected = payload.get("expected_target_commit")
    current = payload.get("current_target_commit")
    if expected is not None and current is not None and expected != current:
        raise PolicyViolation("BASELINE_ADVANCED")


def validate_system_verify(task, payload):
    """Validate system verification before transitioning to system_verified."""
    if task["status"] != "integrated":
        raise PolicyViolation("INVALID_TASK_STATUS")
    if payload.get("outcome") != "passed":
        raise PolicyViolation("VERIFICATION_FAILED")


def validate_can_complete(task, contract, quality_policy=None):
    """TEST-009: Verify that task has passed Integration Gate or is explicitly exempted."""
    status = task["status"]
    if status == "completed":
        return
    if status == "system_verified":
        return

    # If task is in intermediate integration states
    if status in {"ready_for_integration", "integrating", "integrated"}:
        raise PolicyViolation("INTEGRATION_GATE_REQUIRED")

    # If task is in verified status:
    if status == "verified":
        tasks = contract.get("tasks", {}) if contract else {}
        entry = tasks.get(task["id"])
        if entry and entry.get("current_version"):
            # Declared required -> cannot complete without gate
            raise PolicyViolation("INTEGRATION_GATE_REQUIRED")

        # Not declared required: check explicit policy exemption
        if quality_policy:
            exemptions = quality_policy.get("integration_exemptions", [])
            for ex in exemptions:
                if ex.get("task_id") == task["id"]:
                    return  # Explicitly exempted
        raise PolicyViolation("INTEGRATION_GATE_REQUIRED")

    raise PolicyViolation("INVALID_TASK_STATUS")
