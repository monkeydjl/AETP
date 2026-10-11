"""Pure prospective declarations, not an ingress, Event writer or capability verifier.

Inputs are a validated prefix and a Command-shaped internal value. Historical
proof can be recomputed here but cannot authenticate a live caller. The eventual
service must verify the real Command/connection/InputReceipt in its writer
transaction; the eventual Projection must validate causal envelopes separately.
"""

import copy

from aetp.acceptance.records import executable_project, require
from aetp.collaboration.policy import POLICY_VERSION, PolicyViolation, digest_value, text
from aetp.governance.policy import current, fields, principal
from aetp.governance.trust import source_record
from aetp.integration.contracts import MAX_TASKS, MAX_VERSIONS, SCHEMA
from aetp.integration.validation import validate_declaration_payload
from aetp.integration.history import validated_history
from aetp.quality.policy import current_policy
from aetp.runtime.contracts import POLICY_VERSION as EXECUTION_POLICY
from aetp.runtime.policy import observed_time

_ALLOWED_STAGES = frozenset({
    "assigned", "in_progress", "ready_for_review", "in_review", "verified", "rejected", "blocked",
})


def _source(command, context, configuration):
    try:
        source = source_record(command, context, configuration.get("input_authority_id"))
    except (PolicyViolation, TypeError, ValueError) as exc:
        # Provenance syntax is not a payload field, and unhashable exposure must
        # not escape as a Python exception from a pure rejection evaluator.
        raise PolicyViolation("INPUT_CONTEXT_INVALID") from exc
    require(source["untrusted_input"] is False, "SOURCE_UNVERIFIED")
    return source


def _task_snapshot(state, project, payload):
    task = state.get(f"task:{payload['task_id']}")
    require(task is not None and task.get("project_id") == project["id"]
            and task.get("id") == payload["task_id"], "INVALID_TARGET")
    require(payload["expected_task_revision"] == task["revision"], "REVISION_CONFLICT")
    require(task.get("execution_policy_version") == EXECUTION_POLICY
            and task.get("policy_version") == POLICY_VERSION, "POLICY_UNAVAILABLE")
    require(task.get("status") in _ALLOWED_STAGES, "INVALID_TRANSITION")
    owner = task.get("owner_id")
    require(isinstance(owner, str) and bool(owner), "INVALID_TARGET")
    identifier, epoch = task.get("current_binding_id"), task.get("lease_epoch")
    binding = task.get("bindings", {}).get(identifier)
    require(binding is not None and binding.get("id") == identifier
            and binding.get("agent_id") == owner and type(epoch) is int and epoch > 0
            and type(binding.get("lease_epoch")) is int and binding["lease_epoch"] == epoch,
            "STALE_EXECUTION")
    workspace = project.get("workspace_provider_id")
    require(isinstance(workspace, str) and bool(workspace)
            and task.get("workspace_provider_id") == workspace
            and binding.get("workspace_provider_id") == workspace, "WORKSPACE_MISMATCH")
    # Deliberately no live Session, Lease expiry/revocation or participant check:
    # human requirement configuration must not acquire/revive author execution.
    return task


def _history(project, payload):
    """Validate structural history without treating a digest as causal proof."""
    history = validated_history(project)
    if history is None:
        history = {"schema": SCHEMA, "tasks": {}}
    task_id = payload["task_id"]
    entry = history["tasks"].get(task_id)
    if entry is None:
        require(len(history["tasks"]) < MAX_TASKS, "INTEGRATION_DECLARATION_LIMIT")
        previous = None
    else:
        previous = entry["current_version"]
        require(previous < MAX_VERSIONS, "INTEGRATION_DECLARATION_LIMIT")
    require(payload["version"] == (1 if previous is None else previous + 1)
            and payload["supersedes_version"] == previous, "INTEGRATION_DECLARATION_VERSION_CONFLICT")
    return history


def evaluate(command, state, at, context):
    """Return a detached prospective Project effect; never publish it to State."""
    observed_time(state, at)
    text(command.target_id, identifier=True, limit=512)
    fields(context, {"channel", "input_proof"}, {"channel"})
    require(context["channel"] == "agent" and command.type == "project.integration.declare",
            "ENFORCEMENT_UNAVAILABLE")
    project = executable_project(state, command.project_id)
    require(command.target_id == command.project_id, "INVALID_TARGET")
    require(type(command.expected_revision) is int and command.expected_revision == project["revision"],
            "REVISION_CONFLICT")
    configuration, governance_policy = current(state, command.project_id)
    require(command.actor_id == configuration["owner_id"], "PERMISSION_DENIED")
    identity = principal(state, command.project_id, command.actor_id)
    require(identity["type"] == "human"
            and "human_owner" in governance_policy["subjects"][command.actor_id]["roles"], "PERMISSION_DENIED")
    source = _source(command, context, configuration)
    payload = validate_declaration_payload(command.payload)
    task = _task_snapshot(state, project, payload)
    quality = current_policy(state, command.project_id)
    governance_value = configuration["versions"][configuration["current_version"]]
    require(governance_value["content_digest"] == digest_value(governance_policy)
            and quality["content_digest"] == digest_value(quality["policy"]), "INVALID_REFERENCE")
    require(task["id"] not in quality["policy"]["integration_exemptions"], "INTEGRATION_SCOPE_CONFLICT")
    history = _history(project, payload)
    version = {
        **payload, "declared_by": command.actor_id, "command_id": command.id, "observed_at_ms": at,
        "project_revision": project["revision"], "task_revision": task["revision"],
        **{key: task[key] for key in ("criteria_digest", "owner_id", "current_binding_id", "lease_epoch", "workspace_provider_id")},
        "governance": {"owner_id": configuration["owner_id"], "version": configuration["current_version"],
                       "content_digest": governance_value["content_digest"]},
        "task_quality_policy": {"version": quality["version"], "content_digest": quality["content_digest"]},
        "source": source,
    }
    version["content_digest"] = digest_value(version)
    entry = history["tasks"].setdefault(task["id"], {"current_version": 0, "versions": {}})
    entry["versions"][str(payload["version"])] = version
    entry["current_version"] = payload["version"]
    record = {**copy.deepcopy(project), "revision": project["revision"] + 1,
              "observed_at_ms": at, "integration_contract": history}
    return [("project.integration_declared", "project", command.project_id, record)]
