"""Explicit new work and a prevalidated two-fact completion continuation."""

import copy

from aetp.acceptance.records import require
from aetp.collaboration.policy import canonical_json, digest_value, text
from aetp.governance.policy import current, fields, revision
from aetp.quality.contracts import SCHEMA
from aetp.quality.cycles import advance_task, artifact_sources
from aetp.quality.evidence import assess
from aetp.quality.policy import author, authorize, current_policy, no_unsettled
from aetp.quality.submission import FENCE


def block(command, state, task, at, context):
    fields(command.payload, FENCE | {"reason"}, FENCE | {"reason"})
    revision(command, task)
    require(task["status"] in {"in_progress", "ready_for_review", "in_review", "verified", "rejected"},
            "INVALID_TRANSITION")
    require(task.get("quality_contract", {}).get("schema") == SCHEMA, "QUALITY_CONTRACT_REQUIRED")
    author(command, state, task, at, context)
    permission = authorize(command, state, context, "task.quality.transition")
    record = copy.deepcopy(task)
    record.update(revision=task["revision"] + 1, observed_at_ms=at, status="blocked",
                  blocked_from=task["status"], blocked_reason=text(command.payload["reason"], limit=2048),
                  quality_block={"command_id": command.id, "authorization": permission, "blocked_at_ms": at})
    if task.get("quality_cycle") and task["quality_cycle"]["current_task_revision"] == task["revision"]:
        record["quality_cycle"]["current_task_revision"] = record["revision"]
    return record


def rework(command, state, task, at, context):
    fields(command.payload, FENCE | {"reason"}, FENCE | {"reason"})
    revision(command, task)
    require(task["status"] in {"rejected", "blocked"}, "INVALID_TRANSITION")
    require(task.get("quality_contract", {}).get("schema") == SCHEMA, "QUALITY_CONTRACT_REQUIRED")
    execution = author(command, state, task, at, context)
    no_unsettled(state, task["id"])
    permission = authorize(command, state, context, "task.quality.transition")
    policy = current_policy(state, command.project_id)
    record = copy.deepcopy(task)
    record.update(revision=task["revision"] + 1, observed_at_ms=at, status="in_progress", quality_cycle=None)
    record.setdefault("quality_history", []).append({"cycle": copy.deepcopy(task.get("quality_cycle")),
        "contract": copy.deepcopy(task["quality_contract"]), "closed_by": command.id,
        "reason": text(command.payload["reason"], limit=2048), "previous_status": task["status"]})
    record["quality_contract"] = {"schema": SCHEMA, "command_id": command.id, "work_revision": record["revision"],
        "activated_at_ms": at, "execution": execution, "policy": policy,
        "criteria_digest": task["criteria_digest"], "authorization": permission}
    for field in ("blocked_from", "blocked_reason", "quality_block"):
        record.pop(field, None)
    return record


def complete(command, state, task, at, context):
    fields(command.payload, set())
    revision(command, task)
    require((task["status"] in {"verified", "system_verified"}) and "completion_pending" not in task, "INVALID_TRANSITION")
    if task["status"] == "system_verified":
        final = advance_task(task, at, "completed")
        final["lease"]["revoked"] = True
        if task.get("current_binding_id") in final.get("bindings", {}):
            final["bindings"][task["current_binding_id"]]["status"] = "completed"
        final["execution_retirement"] = {"command_id": command.id, "reason": "system_verified_completed", "retired_at_ms": at,
            "binding_id": task.get("current_binding_id"), "lease_epoch": task.get("lease_epoch")}
        final["completion"] = {"command_id": command.id, "requested_by": command.actor_id, "completed_at_ms": at}
        return [("task.completed", "task", task["id"], final)]
    project = state.get(f"project:{task['project_id']}", {})
    from aetp.integration.guards import _required
    require(task["id"] not in _required(project), "INTEGRATION_REQUIRED")
    use = assess(state, task, at, context)
    require(use["result"] == "PASSED", "QUALITY_GATE_NOT_MET")
    no_unsettled(state, task["id"])
    permission = authorize(command, state, context, "task.integration.exempt", artifact_sources(state, task))
    cycle = task["quality_cycle"]
    declaration = cycle["policy"]["policy"]["integration_exemptions"].get(task["id"])
    require(declaration is not None, "INTEGRATION_EXEMPTION_REQUIRED")
    governance, _ = current(state, command.project_id)
    require(declaration["declared_by"] == governance["owner_id"]
            and declaration["scope"] == "standalone_fixed_json_document"
            and all(declaration[key] == task[key] for key in ("criteria_digest", "owner_id", "lease_epoch", "workspace_provider_id"))
            and declaration["binding_id"] == task["current_binding_id"], "INTEGRATION_EXEMPTION_STALE")
    use.update(command_id=command.id, requested_by=command.actor_id, authorization=permission, purpose="task_completion")
    intermediate = advance_task(task, at, "verified", use=use)
    intermediate["integration_exemption"] = {"basis": "explicit_human_owner_task_scope",
        "task_id": task["id"], "quality_cycle_id": cycle["id"], "declaration": copy.deepcopy(declaration),
        "task_quality_policy_version": cycle["policy"]["version"], "task_quality_policy_digest": cycle["policy"]["content_digest"],
        "command_id": command.id, "used_at_ms": at, "evidence_use_digest": digest_value(use), "authorization": permission}
    final = advance_task(intermediate, at, "completed")
    final["lease"]["revoked"] = True
    final["bindings"][task["current_binding_id"]]["status"] = "completed"
    final["execution_retirement"] = {"command_id": command.id, "reason": "quality_completed", "retired_at_ms": at,
        "binding_id": task["current_binding_id"], "lease_epoch": task["lease_epoch"]}
    final["completion"] = {"command_id": command.id, "requested_by": command.actor_id, "completed_at_ms": at,
        "quality_cycle_id": cycle["id"], "integration_exemption_digest": digest_value(intermediate["integration_exemption"])}
    # This expected terminal is computed from the original r State. The first
    # reducer validates it; the r+2 reducer consumes only this stored proof.
    intermediate["completion_pending"] = {"command_id": command.id, "command_digest": command.digest(),
        "context_digest": digest_value(context), "observed_at_ms": at, "original_task_revision": task["revision"],
        "terminal_revision": final["revision"], "terminal_digest": digest_value(final), "terminal_record": final}
    return [("task.integration_exempted", "task", task["id"], intermediate),
            ("task.completed", "task", task["id"], final)]


def finish_continuation(command, previous, at, context):
    """Consume a validated predecessor, not a payload-supplied old Task copy."""
    require(previous is not None and previous["status"] == "verified", "INVALID_TRANSITION")
    pending = previous.get("completion_pending")
    require(pending is not None and pending["command_id"] == command.id
            and pending["command_digest"] == command.digest() and pending["context_digest"] == digest_value(context)
            and pending["observed_at_ms"] == at and command.expected_revision == pending["original_task_revision"]
            and previous["revision"] == command.expected_revision + 1
            and pending["terminal_revision"] == previous["revision"] + 1, "COMPLETION_CONTINUATION_INVALID")
    final = pending["terminal_record"]
    require(digest_value(final) == pending["terminal_digest"] and final["revision"] == pending["terminal_revision"]
            and final["id"] == previous["id"] and final["project_id"] == previous["project_id"]
            and final["status"] == "completed" and "completion_pending" not in final, "COMPLETION_CONTINUATION_INVALID")
    return copy.deepcopy(final)
