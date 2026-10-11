"""Explicit opt-in and execution-end snapshots for immutable documents."""

import copy

from aetp.acceptance.contracts import SCHEMA as ACCEPTANCE_SCHEMA
from aetp.acceptance.records import require, target_snapshot
from aetp.collaboration.policy import canonical_json, digest_value, strings, text
from aetp.governance.policy import fields, revision
from aetp.quality.contracts import MAX_ARTIFACTS, SCHEMA
from aetp.quality.policy import author, authorize, current_policy, no_unsettled
from aetp.runtime.contracts import child_id
from aetp.runtime.records import receipt

FENCE = {"binding_id", "lease_epoch", "session_id"}


def enroll(command, state, task, at, context):
    fields(command.payload, FENCE | {"policy_version"}, FENCE | {"policy_version"})
    revision(command, task)
    require(task["status"] == "in_progress", "INVALID_TRANSITION")
    execution = author(command, state, task, at, context)
    policy = current_policy(state, command.project_id)
    require(command.payload["policy_version"] == policy["version"], "TASK_QUALITY_POLICY_CHANGED")
    previous = task.get("quality_contract")
    require(previous is None or previous["execution"]["lease_epoch"] != task["lease_epoch"], "QUALITY_ALREADY_ENROLLED")
    no_unsettled(state, task["id"])
    permission = authorize(command, state, context, "task.quality.transition")
    record = copy.deepcopy(task)
    record.update(revision=task["revision"] + 1, observed_at_ms=at, quality_cycle=None)
    record["quality_contract"] = {"schema": SCHEMA, "command_id": command.id, "work_revision": record["revision"],
        "activated_at_ms": at, "execution": execution, "policy": policy,
        "criteria_digest": task["criteria_digest"], "authorization": permission}
    record.setdefault("quality_history", [])
    if task.get("quality_cycle") is not None:
        record["quality_history"].append({"cycle": copy.deepcopy(task["quality_cycle"]),
                                          "closed_by": command.id, "reason": "new_execution_epoch"})
    return record


def submit(command, state, task, at, context):
    fields(command.payload, FENCE | {"artifact_ids", "summary"}, FENCE | {"artifact_ids", "summary"})
    revision(command, task)
    require(task["status"] == "in_progress", "INVALID_TRANSITION")
    contract = task.get("quality_contract")
    require(contract is not None and contract.get("schema") == SCHEMA, "QUALITY_CONTRACT_REQUIRED")
    execution = author(command, state, task, at, context)
    require(task["revision"] == contract["work_revision"], "QUALITY_CONTEXT_STALE")
    require(canonical_json(execution) == canonical_json(contract["execution"])
            and task["criteria_digest"] == contract["criteria_digest"], "QUALITY_CONTEXT_STALE")
    policy = current_policy(state, command.project_id)
    require(canonical_json(policy) == canonical_json(contract["policy"]), "TASK_QUALITY_POLICY_CHANGED")
    no_unsettled(state, task["id"])
    identifiers = strings(command.payload["artifact_ids"], required=True)
    require(len(identifiers) <= MAX_ARTIFACTS and len(identifiers) == len(set(identifiers)), "INVALID_PAYLOAD")
    identifiers = sorted(identifiers)
    snapshots, actions, sources = {}, set(), []
    for identifier in identifiers:
        artifact = state.get(f"artifact:{identifier}")
        require(artifact is not None and artifact["task_id"] == task["id"], "INVALID_REFERENCE")
        snapshot = target_snapshot(state, identifier)
        origin = artifact.get("capture_origin")
        require(origin is not None and origin.get("schema") == ACCEPTANCE_SCHEMA, "SOURCE_UNVERIFIED")
        action = state.get(f"action:{origin['action_id']}")
        require(action is not None and action["status"] == "completed" and not action["historical"]
                and action["operation"] == "document.write", "SOURCE_UNVERIFIED")
        require(action["requested_task_revision"] == contract["work_revision"]
                and artifact["task_revision"] == contract["work_revision"], "EVIDENCE_STALE")
        require(action["actor_id"] == task["owner_id"] and artifact["created_by"] == task["owner_id"]
                and all(action[key] == execution[key] for key in ("binding_id", "lease_epoch", "session_id")),
                "STALE_EXECUTION")
        require(action["revision"] == origin["action_revision"] and canonical_json(action["result"]) == canonical_json(receipt(action)),
                "SOURCE_UNVERIFIED")
        require(action["id"] not in actions, "OUTPUT_SET_INCOMPLETE")
        actions.add(action["id"])
        snapshots[identifier] = {**snapshot, "source_action_id": action["id"], "action_revision": action["revision"],
                                 "result_digest": digest_value(action["result"])}
        sources.append(("artifact", identifier, artifact["source"], artifact["content_digest"]))
    completed = {row["id"] for key, row in state.items() if key.startswith("action:") and row["task_id"] == task["id"]
                 and row["requested_task_revision"] == contract["work_revision"] and row["status"] == "completed"
                 and not row["historical"]}
    require(actions == completed, "OUTPUT_SET_INCOMPLETE")
    permission = authorize(command, state, context, "task.quality.transition", sources)
    require(permission["governance_version"] == contract["authorization"]["governance_version"]
            and permission["governance_digest"] == contract["authorization"]["governance_digest"], "GOVERNANCE_CHANGED")
    summary = text(command.payload["summary"], limit=8192)
    cycle = {"schema": SCHEMA, "id": child_id("quality-cycle", command.project_id, command.id),
             "submission_command_id": command.id, "anchor_task_revision": task["revision"],
             "current_task_revision": task["revision"] + 1, "artifact_ids": identifiers, "artifacts": snapshots,
             "criteria_digest": task["criteria_digest"], "execution": execution, "policy": policy,
             "authorization": permission, "summary": summary, "submitted_at_ms": at, "reviews": {}, "uses": []}
    cycle["submission_digest"] = digest_value({key: value for key, value in cycle.items()
                                               if key not in {"current_task_revision", "reviews", "uses"}})
    return {**copy.deepcopy(task), "revision": task["revision"] + 1, "observed_at_ms": at,
            "status": "ready_for_review", "quality_cycle": cycle}
