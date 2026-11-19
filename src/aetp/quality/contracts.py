"""Static quality vocabulary; importing it performs no execution."""

SCHEMA = "aetp-task-quality-1"
MAX_ARTIFACTS = 8
COMMAND_TERMINALS = {
    "project.task_quality.configure": frozenset({"project.task_quality_configured"}),
    "task.quality.enroll": frozenset({"task.quality_enrolled"}),
    "task.quality.submit": frozenset({"task.ready_for_review"}),
    "task.quality.request_review": frozenset({"task.in_review"}),
    "review.quality.submit": frozenset({"review.quality_submitted"}),
    "task.quality.evaluate": frozenset({"task.verified", "task.quality_rejected", "task.quality_checked"}),
    "task.quality.block": frozenset({"task.quality_blocked"}),
    "task.quality.rework": frozenset({"task.quality_reworked"}),
    "task.quality.complete": frozenset({"task.completed"}),
}
COMMAND_AGGREGATES = {kind: kind.split(".")[0] for kind in COMMAND_TERMINALS}
DOMAIN_EVENTS = frozenset(event for values in COMMAND_TERMINALS.values() for event in values) | {
    "review.quality_requested", "task.integration_exempted"}
AUTHOR_COMMANDS = frozenset({"task.quality.enroll", "task.quality.submit", "task.quality.block", "task.quality.rework"})


def review_id(command, artifact_id):
    from aetp.runtime.contracts import child_id
    return child_id("quality-review", command.project_id, f"{len(command.id)}:{command.id}{artifact_id}")


def effect_address(command, index):
    if command.type == "task.quality.request_review":
        identifiers = sorted(command.payload["reviewers"])
        if index < len(identifiers):
            return "review", review_id(command, identifiers[index])
    return COMMAND_AGGREGATES[command.type], command.target_id
