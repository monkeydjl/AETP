"""Candidate vocabulary only; no Bootstrap or active-graph success event."""

SCHEMA = "aetp-planning-candidate-1"
COMMAND_TERMINALS = {
    "project.planning.configure": frozenset({"project.planning_configured"}),
    "mission.propose": frozenset({"mission.proposed"}),
    "team.propose": frozenset({"team.proposed"}),
    "team.revise": frozenset({"team.proposal_revised"}),
    "blueprint.propose": frozenset({"blueprint.proposed"}),
    "blueprint.change.request": frozenset({"blueprint.change_requested"}),
    "task.propose": frozenset({"blueprint.task_proposed"}),
    "team.activate": frozenset(), "blueprint.activate": frozenset(),
    "blueprint.apply": frozenset(),
    "mission.activate": frozenset({"mission.activated"}),
    "mission.acceptance_start": frozenset({"mission.acceptance_started"}),
    "mission.verify": frozenset({"mission.criteria_verified"}),
    "mission.complete": frozenset({"mission.completed"}),
    "project.bootstrap.finalize": frozenset({"project.bootstrap_verified"}),
}
COMMAND_AGGREGATES = {command: command.split(".")[0] for command in COMMAND_TERMINALS}
COMMAND_AGGREGATES["task.propose"] = "blueprint"
COMMAND_AGGREGATES["project.bootstrap.finalize"] = "project"
DOMAIN_EVENTS = frozenset(event for events in COMMAND_TERMINALS.values() for event in events)
AGGREGATES = frozenset({"mission", "team", "blueprint"})
FORMAL_COMMANDS = frozenset(command for command, events in COMMAND_TERMINALS.items() if not events)
EXECUTION_COMMANDS = frozenset({"task.create", "task.claim", "execution.start", "tool.request", "tool.dispatch"})
EXECUTION_EVENTS = frozenset({"task.created", "task.claimed", "task.assigned", "task.started", "action.requested"})
