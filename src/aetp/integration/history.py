"""Structural declaration history validation, not receipt or causal authority."""

import copy

from aetp.acceptance.records import require
from aetp.collaboration.policy import PolicyViolation, digest_value, text
from aetp.governance.policy import fields
from aetp.integration.contracts import MAX_TASKS, MAX_VERSIONS, SCHEMA


def validated_history(project):
    """Return detached checked history, or None only when the key is absent."""
    if "integration_contract" not in project:
        return None
    history = project["integration_contract"]
    try:
        fields(history, {"schema", "tasks"}, {"schema", "tasks"})
        require(history["schema"] == SCHEMA and isinstance(history["tasks"], dict)
                and 1 <= len(history["tasks"]) <= MAX_TASKS, "INVALID_REFERENCE")
        for task_id, entry in history["tasks"].items():
            text(task_id, identifier=True, limit=512)
            fields(entry, {"current_version", "versions"}, {"current_version", "versions"})
            current_version, versions = entry["current_version"], entry["versions"]
            require(type(current_version) is int and 1 <= current_version <= MAX_VERSIONS
                    and isinstance(versions, dict)
                    and set(versions) == {str(v) for v in range(1, current_version + 1)}, "INVALID_REFERENCE")
            for number in range(1, current_version + 1):
                value = versions[str(number)]
                require(isinstance(value, dict) and value.get("task_id") == task_id
                        and type(value.get("version")) is int and value["version"] == number
                        and value.get("requirement") == "required", "INVALID_REFERENCE")
                previous = value.get("supersedes_version")
                require("supersedes_version" in value and (previous is None if number == 1 else
                        type(previous) is int and previous == number - 1), "INVALID_REFERENCE")
                require(value.get("content_digest") == digest_value({k: v for k, v in value.items()
                        if k != "content_digest"}), "INVALID_REFERENCE")
    except (PolicyViolation, TypeError, ValueError) as exc:
        raise PolicyViolation("INVALID_REFERENCE") from exc
    return copy.deepcopy(history)
