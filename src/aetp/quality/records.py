"""Deterministic quality effects for live handling and pure Replay."""

from aetp.acceptance.records import executable_project, require
from aetp.collaboration.policy import text
from aetp.governance.policy import fields
from aetp.quality.policy import configure
from aetp.quality.submission import enroll, submit
from aetp.quality.reviews import request_reviews, submit_review
from aetp.quality.evidence import evaluate_task
from aetp.quality.lifecycle import block, complete, rework
from aetp.runtime.policy import observed_time


def evaluate(command, state, at, context):
    observed_time(state, at)
    text(command.target_id, identifier=True, limit=512)
    fields(context, {"channel", "requester_live", "target_live", "runner", "input_proof"}, {"channel"})
    require(context["channel"] == "agent", "ENFORCEMENT_UNAVAILABLE")
    if command.type == "project.task_quality.configure":
        record = configure(command, state, at)
        return [("project.task_quality_configured", "project", command.target_id, record)]
    executable_project(state, command.project_id)
    if command.type == "review.quality.submit":
        record = submit_review(command, state, at, context)
        return [("review.quality_submitted", "review", command.target_id, record)]
    task = state.get(f"task:{command.target_id}")
    require(task is not None, "INVALID_TARGET")
    if command.type == "task.quality.enroll":
        record, kind = enroll(command, state, task, at, context), "task.quality_enrolled"
    elif command.type == "task.quality.submit":
        record, kind = submit(command, state, task, at, context), "task.ready_for_review"
    elif command.type == "task.quality.request_review":
        return request_reviews(command, state, task, at, context)
    elif command.type == "task.quality.evaluate":
        kind, record = evaluate_task(command, state, task, at, context)
    elif command.type == "task.quality.block":
        record, kind = block(command, state, task, at, context), "task.quality_blocked"
    elif command.type == "task.quality.rework":
        record, kind = rework(command, state, task, at, context), "task.quality_reworked"
    elif command.type == "task.quality.complete":
        return complete(command, state, task, at, context)
    else:
        require(False, "ENFORCEMENT_UNAVAILABLE")
    return [(kind, "task", task["id"], record)]
