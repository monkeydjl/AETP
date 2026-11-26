"""Immutable submission identity and explicitly permitted Task revisions."""

import copy

from aetp.acceptance.records import require
from aetp.collaboration.policy import (
    POLICY_VERSION,
    canonical_json,
    digest_text,
    digest_value,
)
from aetp.governance.policy import current
from aetp.quality.contracts import SCHEMA
from aetp.quality.policy import current_policy, execution_context, observed_live
from aetp.runtime.records import receipt


def durable_cycle(state, task):
    cycle, contract = task.get("quality_cycle"), task.get("quality_contract")
    require(isinstance(cycle, dict) and cycle.get("schema") == SCHEMA
            and isinstance(contract, dict) and contract.get("schema") == SCHEMA, "QUALITY_CONTRACT_REQUIRED")
    require(task["revision"] == cycle["current_task_revision"]
            and task["criteria_digest"] == cycle["criteria_digest"] == contract["criteria_digest"]
            and contract["work_revision"] == cycle["anchor_task_revision"], "QUALITY_CONTEXT_STALE")
    require(cycle["submission_digest"] == digest_value({key: value for key, value in cycle.items()
            if key not in {"submission_digest", "current_task_revision", "reviews", "uses"}}), "QUALITY_CONTEXT_STALE")
    execution = cycle["execution"]
    binding = task.get("bindings", {}).get(task.get("current_binding_id"), {})
    lease = task.get("lease") or {}
    require(task["owner_id"] == execution["owner_id"] and task["current_binding_id"] == execution["binding_id"]
            and task["lease_epoch"] == execution["lease_epoch"]
            and task["workspace_provider_id"] == execution["workspace_provider_id"]
            and canonical_json(binding.get("session")) == canonical_json(execution["session"])
            and lease.get("expires_at_governance_ms") == execution["lease_expires_at"], "QUALITY_CONTEXT_STALE")
    require(canonical_json(current_policy(state, task["project_id"])) == canonical_json(cycle["policy"]),
            "TASK_QUALITY_POLICY_CHANGED")
    governance, policy = current(state, task["project_id"])
    require(governance["current_version"] == cycle["authorization"]["governance_version"]
            and digest_value(policy) == cycle["authorization"]["governance_digest"], "GOVERNANCE_CHANGED")
    return cycle


def active_cycle(state, task, at, context):
    cycle = durable_cycle(state, task)
    execution = execution_context(state, task, at)
    require(canonical_json(execution) == canonical_json(cycle["execution"]), "QUALITY_CONTEXT_STALE")
    observed_live(context.get("target_live"), execution)
    return cycle


def target_binding(state, artifact):
    """Returns only the durable round ID, never changes Artifact revision."""
    task = state[f"task:{artifact['task_id']}"]
    cycle = durable_cycle(state, task)
    require(task["status"] in {"ready_for_review", "in_review", "verified", "rejected"}, "EVIDENCE_STALE")
    identifier = artifact["id"]
    require(identifier in cycle["artifacts"], "EVIDENCE_STALE")
    origin = artifact.get("capture_origin") or {}
    action = state.get(f"action:{origin.get('action_id')}")
    require(action is not None and action["status"] == "completed" and not action["historical"]
            and action["operation"] == "document.write", "SOURCE_UNVERIFIED")
    actual = {"artifact_id": identifier, "artifact_digest": artifact["content_digest"], "task_id": task["id"],
        "task_revision": artifact["task_revision"], "criteria_digest": artifact["criteria_digest"],
        "criteria": artifact["criteria"], "artifact_author_id": artifact["created_by"],
        "source_digest": digest_value(artifact["source"]), "capture_origin_digest": digest_value(origin),
        "source_action_id": action["id"], "action_revision": action["revision"], "result_digest": digest_value(action["result"])}
    require(canonical_json(actual) == canonical_json(cycle["artifacts"][identifier])
            and artifact["task_revision"] == cycle["anchor_task_revision"]
            and artifact["criteria_digest"] == task["criteria_digest"] == digest_value(artifact["criteria"])
            and artifact["content_digest"] == digest_text(artifact["content"])
            and artifact["policy_version"] == task["policy_version"] == POLICY_VERSION, "EVIDENCE_STALE")
    require(action["requested_task_revision"] == cycle["anchor_task_revision"]
            and action["actor_id"] == artifact["created_by"] == cycle["execution"]["owner_id"]
            and all(action[key] == cycle["execution"][key] for key in ("binding_id", "lease_epoch", "session_id"))
            and action["arguments"]["content"] == artifact["content"]
            and action["revision"] == origin["action_revision"]
            and canonical_json(action["result"]) == canonical_json(receipt(action)), "SOURCE_UNVERIFIED")
    require(artifact["source"]["untrusted_input"] is False, "SOURCE_UNVERIFIED")
    return cycle["id"]


def artifact_sources(state, task):
    return [("artifact", identifier, state[f"artifact:{identifier}"]["source"],
             state[f"artifact:{identifier}"]["content_digest"]) for identifier in task["quality_cycle"]["artifact_ids"]]


def advance_task(task, at, status, *, use=None):
    record = copy.deepcopy(task)
    record.update(revision=task["revision"] + 1, observed_at_ms=at, status=status)
    record["quality_cycle"]["current_task_revision"] = record["revision"]
    if use is not None:
        record["quality_cycle"]["uses"].append(copy.deepcopy(use))
    return record
