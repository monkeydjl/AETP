"""Closed Integration boundaries shared by old command and projection paths."""

from aetp.collaboration.policy import PolicyViolation, canonical_json, text
from aetp.domain.models import ModelValidationError
from aetp.governance.policy import fields
from aetp.integration.history import validated_history
from aetp.meetings.policy import natural

GUARDED_COMMANDS = frozenset({"project.task_quality.configure", "task.complete", "task.quality.complete", "git.merge"})
_INTEGRATION_STATES = frozenset({"ready_for_integration", "integrating", "integrated", "system_verified"})


def _required(project):
    history = validated_history(project)
    return frozenset() if history is None else frozenset(history["tasks"])


def _exemption_ids(payload):
    fields(payload, {"version", "max_evidence_age_ms", "integration_exemptions"},
           {"version", "max_evidence_age_ms", "integration_exemptions"})
    text(payload["version"], identifier=True)
    natural(payload["max_evidence_age_ms"], 86400000, positive=True)
    supplied = payload["integration_exemptions"]
    if not isinstance(supplied, list) or len(supplied) > 64:
        raise PolicyViolation("INVALID_PAYLOAD")
    identifiers = set()
    for entry in supplied:
        fields(entry, {"task_id", "scope", "reason"}, {"task_id", "scope", "reason"})
        identifier = text(entry["task_id"], identifier=True, limit=512)
        text(entry["reason"], limit=2048)
        if entry["scope"] != "standalone_fixed_json_document":
            raise PolicyViolation("INTEGRATION_SCOPE_UNSUPPORTED")
        if identifier in identifiers:
            raise PolicyViolation("INVALID_REFERENCE")
        identifiers.add(identifier)
    return identifiers


def command_error(command, state):
    if command.type not in GUARDED_COMMANDS:
        return None
    try:
        if command.type == "git.merge":
            if "expected_target_commit" in command.payload or "source_ref" in command.payload:
                from aetp.integration.gate import validate_merge
                task = state.get(f"task:{command.target_id}")
                if task is not None:
                    try:
                        validate_merge(task, command.payload)
                    except PolicyViolation as ex:
                        return ex.code
                return None
            from aetp.integration.requests import merge_error
            return merge_error(command, state)
        required = _required(state.get(f"project:{command.project_id}", {}))
        if not required:
            return None
        if command.type == "project.task_quality.configure":
            return "INTEGRATION_SCOPE_CONFLICT" if required & _exemption_ids(command.payload) else None
        if command.target_id in required:
            task = state.get(f"task:{command.target_id}")
            if task is not None and task.get("status") == "system_verified":
                return None
            return "INTEGRATION_REQUIRED"
        return None
    except PolicyViolation as exc:
        return exc.code


def validate_fact(event, state):
    if event.type not in {"task.integration_exempted", "task.completed"}:
        return
    try:
        if event.aggregate_id in _required(state.get(f"project:{event.project_id}", {})):
            if event.type == "task.completed":
                task = state.get(f"task:{event.aggregate_id}")
                if task is not None and task.get("status") == "system_verified":
                    return
            raise ModelValidationError("required Integration cannot be exempted or completed")
    except PolicyViolation as exc:
        raise ModelValidationError("invalid Integration history") from exc


def validate_record(event, previous, updated, state):
    if event.aggregate_type not in {"project", "task"}:
        return
    try:
        if event.aggregate_type == "task":
            status = updated.get("status")
            prev_status = (previous or {}).get("status")
            if status in _INTEGRATION_STATES and status != prev_status:
                expected_event = {
                    "ready_for_integration": "task.integration_ready",
                    "integrated": "integration.completed",
                    "system_verified": "task.system_verified",
                }.get(status)
                if event.type != expected_event:
                    raise ModelValidationError(f"Integration success status {status} requires matching event")
            if status == "completed" and event.aggregate_id in _required(state.get(f"project:{event.project_id}", {})):
                prev_status = (previous or {}).get("status")
                if prev_status != "system_verified":
                    raise ModelValidationError("required Integration cannot be completed")
            return
        before = {} if previous is None else previous
        present = "integration_contract" in before
        if present != ("integration_contract" in updated) or (present and
                canonical_json(before["integration_contract"]) != canonical_json(updated["integration_contract"])):
            if event.type != "project.integration_declared":
                raise ModelValidationError("Project update cannot introduce or change Integration declarations")
            from aetp.integration.projection import reduce_record
            expected = reduce_record(event, previous, state)
            if canonical_json(updated) != canonical_json(expected):
                raise ModelValidationError("Integration append differs from independent recomputation")
        required = _required(updated)
        if required:
            history = updated["task_quality_policy"]
            policy = history["versions"][history["current_version"]]["policy"]
            exemptions = policy["integration_exemptions"]
            if not isinstance(exemptions, dict) or required & exemptions.keys():
                raise ModelValidationError("required Integration conflicts with current exemption policy")
    except (PolicyViolation, KeyError, TypeError, ValueError, RecursionError) as exc:
        if isinstance(exc, ModelValidationError):
            raise
        raise ModelValidationError("invalid Integration record boundary") from exc
