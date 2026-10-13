"""Pure validation and guard functions for Integration Gate transitions."""
from aetp.collaboration.policy import PolicyViolation
from aetp.integration.gitref import resolve_ref


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


def validate_merge_against_repo(task, payload, repo_dir):
    """Re-check the merge baseline against the real target-branch tip (TEST-024/§10.6).

    Unlike :func:`validate_merge`, this never trusts a caller-supplied
    ``current_target_commit``. It resolves the actual tip of ``target_ref`` from
    ``repo_dir`` and compares it with the expected commit, so a target branch
    that advanced since verification cannot be merged on stale trust.
    """
    if task["status"] != "ready_for_integration":
        raise PolicyViolation("INVALID_TASK_STATUS")
    target_ref = payload.get("target_ref")
    expected = payload.get("expected_target_commit")
    if not isinstance(target_ref, str) or not target_ref:
        raise PolicyViolation("INVALID_PAYLOAD")
    if not isinstance(expected, str) or not expected:
        raise PolicyViolation("INVALID_PAYLOAD")
    actual_tip = resolve_ref(repo_dir, target_ref)
    if expected != actual_tip:
        raise PolicyViolation("BASELINE_ADVANCED")


def dispatch_merge(provider, task, payload):
    """Route git.merge to the trusted provider when present, else simulate.

    With a trusted Workspace Provider (holding its own repo_dir), the merge is
    real: the provider re-checks the target tip and returns a conflict instead
    of silently resolving it. Without a provider, the legacy simulated path
    (:func:`validate_merge`) is preserved for backward compatibility.

    The task-status guard applies to both paths: a Task must be
    ``ready_for_integration`` before any merge, real or simulated.
    """
    if task.get("status") != "ready_for_integration":
        raise PolicyViolation("INVALID_TASK_STATUS")
    if provider is not None:
        # A real provider only reads the agent-supplied refs and expected
        # commit; it never trusts persisted conflict/result placeholders.
        result = provider.merge(
            payload.get("source_ref"),
            payload.get("target_ref"),
            payload.get("expected_target_commit"),
        )
        if result.get("status") == "conflict":
            return {"conflict": True, "conflict_paths": result.get("conflict_paths", []), "result_commit": None}
        return {"conflict": False, "conflict_paths": [], "result_commit": result.get("result_commit")}

    validate_merge(task, payload)
    has_conflict = bool(payload.get("has_conflict"))
    return {
        "conflict": has_conflict,
        "conflict_paths": payload.get("conflict_paths", []) if has_conflict else [],
        "result_commit": payload.get("result_commit"),
    }


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
