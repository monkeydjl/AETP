"""Static vocabulary and addresses; importing it does not start a Runtime."""

import hashlib

POLICY_VERSION = "m1-fixed-document-execution-v1"
RUNTIME_ID = "fixed-document-v1"
LEASE_MS = 300_000
SESSION_MS = 120_000

COMMAND_AGGREGATES = {
    "project.execution.configure": "project", "project.pause": "project", "project.resume": "project",
    "execution.start": "task", "execution.report": "task", "lease.renew": "task", "lease.revoke": "task",
    "task.requeue": "task", "checkpoint.create": "task", "tool.request": "task",
    "tool.dispatch": "action", "tool.report": "action", "tool.reconcile": "action", "tool.cancel": "action",
}
COMMAND_TERMINALS = {
    "project.execution.configure": frozenset({"project.execution_configured"}),
    "project.pause": frozenset({"project.paused"}), "project.resume": frozenset({"project.resumed"}),
    "execution.start": frozenset({"task.started"}), "execution.report": frozenset({"execution.reported"}),
    "lease.renew": frozenset({"lease.renewed"}), "lease.revoke": frozenset({"lease.revoked"}),
    "task.requeue": frozenset({"task.requeued"}), "checkpoint.create": frozenset({"checkpoint.created"}),
    "tool.request": frozenset({"tool.requested"}), "tool.dispatch": frozenset({"tool.invoked"}),
    "tool.report": frozenset({"tool.completed", "tool.failed", "tool.outcome_unknown"}),
    "tool.reconcile": frozenset({"tool.reconciled", "tool.outcome_unknown"}),
    "tool.cancel": frozenset({"tool.cancelled"}),
}
EVENT_AGGREGATES = {event: aggregate for command, aggregate in COMMAND_AGGREGATES.items()
                    for event in COMMAND_TERMINALS[command]}
EVENT_AGGREGATES.update({"tool.requested": "action", "checkpoint.created": "checkpoint",
                         "task.claimed": "task", "task.requeued": "task"})
DOMAIN_EVENTS = frozenset(EVENT_AGGREGATES)
AGGREGATES = frozenset({"action", "checkpoint"})
INTERNAL_COMMANDS = frozenset({"execution.start", "tool.dispatch", "tool.report", "tool.reconcile", "tool.cancel"})
UNSETTLED = frozenset({"pending", "in_flight", "unknown"})


def child_id(kind, project_id, command_id):
    """Unambiguous deterministic identities for owned subresources."""
    identity = f"{len(project_id)}:{project_id}{len(command_id)}:{command_id}".encode("utf-8")
    return kind + "-" + hashlib.sha256(identity).hexdigest()


def effect_address(command):
    if command.type in {"tool.request", "checkpoint.create"}:
        kind = "action" if command.type == "tool.request" else "checkpoint"
        return kind, child_id(kind, command.project_id, command.id)
    return None
