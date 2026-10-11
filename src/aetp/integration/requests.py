"""Fixed merge refusal dialect. This module never grants execution authority."""
from aetp.acceptance.records import executable_project, require
from aetp.collaboration.messages import participant
from aetp.integration.history import validated_history
from aetp.integration.records import _task_snapshot
from aetp.integration.validation import validate_merge_payload
from aetp.quality.policy import current_policy


def merge_error(command, state):
    project = executable_project(state, command.project_id)
    task = _task_snapshot(state, project, {"task_id": command.target_id, "expected_task_revision": command.expected_revision})
    current_policy(state, command.project_id)
    require(task["owner_id"] == command.actor_id and participant(state, command.actor_id), "PERMISSION_DENIED")
    payload = validate_merge_payload(command.payload)
    history = validated_history(project)
    entry = None if history is None else history["tasks"].get(command.target_id)
    require(entry is not None, "INTEGRATION_DECLARATION_REQUIRED")
    version = entry["current_version"]
    require(payload["declaration_version"] == version
            and payload["declaration_digest"] == entry["versions"][str(version)]["content_digest"],
            "INTEGRATION_DECLARATION_STALE")
    return "ENFORCEMENT_UNAVAILABLE"
