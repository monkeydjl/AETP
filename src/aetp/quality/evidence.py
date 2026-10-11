"""Collect every official record before assessing its current applicability."""

from aetp.acceptance.records import require
from aetp.collaboration.policy import digest_value
from aetp.governance.policy import fields, revision
from aetp.quality.contracts import SCHEMA
from aetp.quality.cycles import active_cycle, advance_task, artifact_sources, durable_cycle, target_binding
from aetp.quality.evidence_checks import verification_use
from aetp.quality.policy import authorize, no_unsettled
from aetp.quality.reviews import independent_reviewer


def verification_allowed(state, artifact_id, actor):
    artifact = state[f"artifact:{artifact_id}"]
    task = state[f"task:{artifact['task_id']}"]
    require(task["status"] == "in_review", "INVALID_TRANSITION")
    cycle = durable_cycle(state, task)
    identifier = cycle["reviews"].get(artifact_id)
    review = state.get(f"review:{identifier}")
    require(review is not None and review.get("schema") == SCHEMA and review["quality_cycle_id"] == cycle["id"]
            and review["reviewer_id"] == actor, "REVIEWER_MISMATCH")
    independent_reviewer(state, task, actor)


def assess(state, task, at, context):
    """Pure usage decision. Never calls the dispatch authorizer or any Runner."""
    cycle = active_cycle(state, task, at, context)
    no_unsettled(state, task["id"], target_verifications=False)
    # Do not predicate collection on validity, actor, finality or PASSED.
    records = sorted((record for key, record in state.items() if key.startswith("verification:")
        and record.get("input", {}).get("quality_cycle_id") == cycle["id"]
        and record.get("artifact_id") in cycle["artifact_ids"]), key=lambda row: row["id"])
    reviews, verifications, missing = [], [], []
    negative, all_passed = False, True
    for identifier in cycle["artifact_ids"]:
        target_binding(state, state[f"artifact:{identifier}"])
        review_id = cycle["reviews"].get(identifier)
        review = state.get(f"review:{review_id}")
        if review is None:
            missing.append({"artifact_id": identifier, "kind": "review"})
            all_passed = False
            continue
        require(review.get("schema") == SCHEMA and review["quality_cycle_id"] == cycle["id"]
                and review["artifact_id"] == identifier and review["task_id"] == task["id"]
                and review["task_revision"] == cycle["anchor_task_revision"]
                and review["criteria_digest"] == cycle["criteria_digest"]
                and review["artifact_digest"] == cycle["artifacts"][identifier]["artifact_digest"], "EVIDENCE_STALE")
        independent_reviewer(state, task, review["reviewer_id"])
        for permission in (review["authorization"], review.get("response_authorization")):
            if permission is None:
                continue
            require(permission["source"]["untrusted_input"] is False, "SOURCE_UNVERIFIED")
            require(permission["governance_version"] == cycle["authorization"]["governance_version"]
                    and permission["governance_digest"] == cycle["authorization"]["governance_digest"], "GOVERNANCE_CHANGED")
        require(review["status"] in {"pending", "approved", "changes_requested", "rejected"}, "EVIDENCE_STALE")
        require(review["status"] == "pending" or review["response_authorization"] is not None, "EVIDENCE_STALE")
        negative |= review["status"] in {"changes_requested", "rejected"}
        all_passed &= review["status"] == "approved"
        reviews.append({"id": review["id"], "record_digest": digest_value(review), "status": review["status"],
                        "reviewer_id": review["reviewer_id"], "artifact_id": identifier})
        if not any(row["artifact_id"] == identifier for row in records):
            missing.append({"artifact_id": identifier, "kind": "verification"})
            all_passed = False
    # A bad record rejects use even when another record already proves failure.
    for record in records:
        use = verification_use(record, state, task, cycle, at, context)
        verifications.append(use)
        negative |= use["result"] == "FAILED"
        all_passed &= use["result"] == "PASSED"
    return {"schema": SCHEMA, "quality_cycle_id": cycle["id"], "submission_digest": cycle["submission_digest"],
        "original_task_revision": cycle["anchor_task_revision"], "current_task_revision": task["revision"],
        "criteria_digest": cycle["criteria_digest"], "task_quality_policy": cycle["policy"],
        "governance_version": cycle["authorization"]["governance_version"],
        "governance_digest": cycle["authorization"]["governance_digest"], "used_at_ms": at,
        "review_ids": [row["id"] for row in reviews], "verification_ids": [row["id"] for row in records],
        "reviews": reviews, "verifications": verifications, "missing": missing,
        "result": "FAILED" if negative else "PASSED" if all_passed else "INCONCLUSIVE"}


def evaluate_task(command, state, task, at, context):
    fields(command.payload, set())
    revision(command, task)
    require(task["status"] == "in_review", "INVALID_TRANSITION")
    use = assess(state, task, at, context)
    permission = authorize(command, state, context, "task.quality.evaluate", artifact_sources(state, task))
    use.update(command_id=command.id, requested_by=command.actor_id, authorization=permission, purpose="task_evaluation")
    status, kind = {"PASSED": ("verified", "task.verified"), "FAILED": ("rejected", "task.quality_rejected"),
                    "INCONCLUSIVE": ("in_review", "task.quality_checked")}[use["result"]]
    return kind, advance_task(task, at, status, use=use)
