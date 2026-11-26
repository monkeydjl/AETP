"""Selected independent peers review immutable, officially submitted outputs."""

import copy

from aetp.acceptance.records import require
from aetp.collaboration.policy import canonical_json, text
from aetp.governance.policy import current, fields, has_role, principal, revision
from aetp.quality.contracts import SCHEMA, review_id
from aetp.quality.cycles import (
    active_cycle,
    advance_task,
    artifact_sources,
    target_binding,
)
from aetp.quality.policy import authorize, no_unsettled


def independent_reviewer(state, task, actor):
    require(actor != task["owner_id"], "INDEPENDENCE_REQUIRED")
    require(principal(state, task["project_id"], actor)["type"] == "agent", "PERMISSION_DENIED")
    _, policy = current(state, task["project_id"])
    require(has_role(policy, actor, "independent_reviewer"), "PERMISSION_DENIED")


def request_reviews(command, state, task, at, context):
    fields(command.payload, {"reviewers"}, {"reviewers"})
    revision(command, task)
    require(task["status"] == "ready_for_review", "INVALID_TRANSITION")
    cycle = active_cycle(state, task, at, context)
    no_unsettled(state, task["id"])
    reviewers = command.payload["reviewers"]
    require(isinstance(reviewers, dict) and set(reviewers) == set(cycle["artifact_ids"]), "REVIEW_SET_INCOMPLETE")
    permission = authorize(command, state, context, "task.quality.review", artifact_sources(state, task))
    effects, links = [], {}
    for artifact_id in cycle["artifact_ids"]:
        artifact = state[f"artifact:{artifact_id}"]
        target_binding(state, artifact)
        actor = text(reviewers[artifact_id], identifier=True)
        independent_reviewer(state, task, actor)
        identifier = review_id(command, artifact_id)
        record = {"schema": SCHEMA, "id": identifier, "project_id": command.project_id, "revision": 0,
            "task_id": task["id"], "artifact_id": artifact_id, "artifact_digest": artifact["content_digest"],
            "task_revision": cycle["anchor_task_revision"], "criteria_digest": cycle["criteria_digest"],
            "quality_cycle_id": cycle["id"], "requested_by": command.actor_id, "reviewer_id": actor,
            "request_command_id": command.id, "status": "pending", "feedback": None,
            "authorization": copy.deepcopy(permission), "response_authorization": None,
            "response_command_id": None, "observed_at_ms": at}
        existing = state.get(f"review:{identifier}")
        # Earlier child effects in this same atomic batch must agree exactly.
        # No arbitrary pre-existing Review can be adopted or overwritten.
        require(existing is None or canonical_json(existing) == canonical_json(record), "REVISION_CONFLICT")
        links[artifact_id] = identifier
        effects.append(("review.quality_requested", "review", identifier, record))
    updated = advance_task(task, at, "in_review")
    updated["quality_cycle"]["reviews"] = links
    effects.append(("task.in_review", "task", task["id"], updated))
    return effects


def submit_review(command, state, at, context):
    fields(command.payload, {"status", "feedback"}, {"status", "feedback"})
    previous = state.get(f"review:{command.target_id}")
    require(previous is not None and previous.get("schema") == SCHEMA, "INVALID_TARGET")
    revision(command, previous)
    require(command.actor_id == previous["reviewer_id"], "PERMISSION_DENIED")
    require(previous["status"] == "pending", "REVIEW_FINAL")
    task = state[f"task:{previous['task_id']}"]
    require(task["status"] == "in_review", "INVALID_TRANSITION")
    cycle = active_cycle(state, task, at, context)
    require(cycle["reviews"].get(previous["artifact_id"]) == previous["id"]
            and cycle["id"] == previous["quality_cycle_id"], "EVIDENCE_STALE")
    independent_reviewer(state, task, command.actor_id)
    target_binding(state, state[f"artifact:{previous['artifact_id']}"])
    status = command.payload["status"]
    require(isinstance(status, str) and status in {"approved", "changes_requested", "rejected"}, "INVALID_PAYLOAD")
    permission = authorize(command, state, context, "task.quality.review", artifact_sources(state, task))
    return {**copy.deepcopy(previous), "revision": previous["revision"] + 1, "status": status,
            "feedback": text(command.payload["feedback"], limit=8192), "observed_at_ms": at,
            "response_command_id": command.id, "response_authorization": permission}
