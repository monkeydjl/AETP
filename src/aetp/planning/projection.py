"""Replay checks candidate effects by recomputing them from the prior facts."""

from aetp.collaboration.policy import PolicyViolation, canonical_json
from aetp.domain.models import Command, ModelValidationError
from aetp.planning.contracts import COMMAND_AGGREGATES, COMMAND_TERMINALS, SCHEMA
from aetp.planning.records import evaluate


def reduce_record(event, previous, state):
    try:
        payload = event.payload
        if set(payload) != {"planning_schema", "command", "observed_at_ms", "record"} or payload["planning_schema"] != SCHEMA:
            raise ModelValidationError("unexpected planning Event fields")
        command = Command.from_dict(payload["command"])
        if (command.id != event.causation_id or command.project_id != event.project_id
                or command.correlation_id != event.correlation_id or command.target_id != event.aggregate_id
                or command.type not in COMMAND_AGGREGATES or COMMAND_AGGREGATES[command.type] != event.aggregate_type):
            raise ModelValidationError("planning effect has a different Command address")
        kind, expected = evaluate(command, state, payload["observed_at_ms"])
        if (kind != event.type or expected["revision"] != event.aggregate_revision
                or canonical_json(expected) != canonical_json(payload["record"])):
            raise ModelValidationError("planning fact disagrees with its deterministic transition")
        return expected
    except (PolicyViolation, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ModelValidationError):
            raise
        raise ModelValidationError("invalid planning Event") from exc


def validate_command_effect(event, command):
    if (event.type not in COMMAND_TERMINALS[command.type]
            or canonical_json(event.payload["command"]) != canonical_json(command.to_dict())):
        raise ModelValidationError("planning fact differs from its persisted Command")
