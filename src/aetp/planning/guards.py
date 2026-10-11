"""Scope gates consume durable Project facts, never caller planning flags."""

from aetp.planning.contracts import EXECUTION_COMMANDS, EXECUTION_EVENTS


def candidate_scope(state, project_id):
    return state.get(f"project:{project_id}", {}).get("planning", {}).get("mode") == "candidate_only"


def command_error(command, state):
    if command.type in EXECUTION_COMMANDS and candidate_scope(state, command.project_id):
        return "PLANNING_NOT_ACTIVE"
    return None


def validate_fact(event, state):
    if event.type in EXECUTION_EVENTS and candidate_scope(state, event.project_id):
        from aetp.domain.models import ModelValidationError
        raise ModelValidationError("candidate planning cannot create or execute a runtime Task")
