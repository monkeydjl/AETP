"""Static vocabulary; roles express approval duties, never Agent hierarchy."""

SCHEMA = "aetp-governance-1"
TARGET_TYPES = frozenset({"decision", "blueprint", "deployment", "budget", "credential", "task", "team", "mission"})
ROLES = frozenset({"human_owner", "human_collaborator", "agent_reviewer", "independent_reviewer"})
RISKS = ("low", "medium", "high", "critical")
ACTION_RISKS = {"decision.activate": "low", "verification.execute": "low", "document.write": "low", "document.restore": "low",
                "document.append": "low", "production.deploy": "high", "database.drop": "critical",
                "payment.transfer": "critical", "account.change": "critical", "public.send": "critical",
                "task.quality.transition": "low", "task.quality.review": "low",
                "task.quality.evaluate": "low", "task.integration.exempt": "low"}
COMMAND_TERMINALS = {
    "project.governance.configure": frozenset({"project.governance_configured"}),
    "approval.request": frozenset({"approval.requested"}), "approval.renew": frozenset({"approval.requested"}),
    "approval.grant": frozenset({"approval.granted"}), "approval.deny": frozenset({"approval.denied"}),
    "approval.delegate": frozenset({"approval.delegated"}), "approval.invalidate": frozenset({"approval.invalidated"}),
    "approval.expire": frozenset({"approval.expired"}), "approval.escalate": frozenset({"approval.escalated"}),
    "approval.revoke": frozenset({"approval.revoked"}),
    "decision.review": frozenset({"decision.reviewing"}), "decision.submit": frozenset({"decision.pending_approval"}),
    "decision.approve": frozenset({"decision.approved"}), "decision.activate": frozenset({"decision.activated"}),
    "decision.invalidate": frozenset({"decision.invalidated", "decision.rejected"}),
    "project.pause": frozenset({"project.paused"}), "project.resume": frozenset({"project.resumed"}),
    "intervention.record": frozenset({"intervention.recorded"}), "intervention.apply": frozenset({"intervention.recorded"}),
    "task.governance.block": frozenset({"task.blocked"}), "task.governance.stop": frozenset({"task.cancelled"}),
    "credential.request": frozenset({"credential.issued"}), "credential.revoke": frozenset({"credential.revoked"}),
}
COMMAND_AGGREGATES = {command: command.split(".")[0] for command in COMMAND_TERMINALS}
DOMAIN_EVENTS = frozenset(event for events in COMMAND_TERMINALS.values() for event in events)
AGGREGATES = frozenset({"approval", "intervention", "credential"})
INTERNAL_COMMANDS = frozenset({"approval.delegate", "approval.invalidate", "approval.expire", "approval.escalate",
                               "approval.renew", "decision.invalidate", "intervention.record", "task.governance.block"})


def system_actor(project_id):
    from aetp.runtime.contracts import child_id
    return child_id("governance-system", project_id, project_id)
