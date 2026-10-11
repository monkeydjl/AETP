"""Pure governance reduction and binding to the original persisted Command."""

from aetp.collaboration.policy import PolicyViolation, canonical_json
from aetp.domain.models import Command, ModelValidationError
from aetp.governance.contracts import COMMAND_AGGREGATES, COMMAND_TERMINALS, INTERNAL_COMMANDS, SCHEMA, system_actor
from aetp.governance.causality import continuations, validate_context
from aetp.governance.policy import configure, current, principal
from aetp.runtime.policy import observed_time


def evaluate(command, state, at, context):
    observed_time(state, at)
    if command.target_id is None:
        raise PolicyViolation("INVALID_TARGET")
    if command.type in INTERNAL_COMMANDS:
        if context.get("internal") is not True or command.actor_id != system_actor(command.project_id):
            raise PolicyViolation("PERMISSION_DENIED")
    validate_context(command, state, context)
    if command.type == "project.governance.configure":
        return "project.governance_configured", configure(command, state, at, context)
    current(state, command.project_id)
    principal(state, command.project_id, command.actor_id, internal=context.get("internal") is True)
    aggregate = COMMAND_AGGREGATES[command.type]
    previous = state.get(f"{aggregate}:{command.target_id}")
    if aggregate == "approval":
        from aetp.governance.approvals import transition
        return transition(command, previous, state, at, context)
    if aggregate == "decision":
        from aetp.governance.decisions import transition
        return transition(command, previous, state, at, context)
    if aggregate in {"project", "intervention", "task"}:
        from aetp.governance.controls import transition
        return transition(command, previous, state, at, context)
    raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")


def reduce_record(event, previous, state):
    try:
        payload = event.payload
        if set(payload) != {"governance_schema", "actor_id", "command_type", "command_payload", "expected_revision",
                           "observed_at_ms", "context", "record", "continuations"} or payload["governance_schema"] != SCHEMA:
            raise ModelValidationError("unexpected governance Event fields")
        command = Command(event.causation_id, event.project_id, payload["actor_id"], payload["command_type"],
                          event.aggregate_id, payload["command_payload"], payload["expected_revision"],
                          payload["context"]["idempotency_key"], event.correlation_id)
        if command.type not in COMMAND_AGGREGATES:
            raise ModelValidationError("unknown governance Command")
        kind, expected = evaluate(command, state, payload["observed_at_ms"], payload["context"])
        if (kind != event.type or COMMAND_AGGREGATES[command.type] != event.aggregate_type
                or expected["id"] != event.aggregate_id or expected["project_id"] != event.project_id
                or expected["revision"] != event.aggregate_revision
                or canonical_json(expected) != canonical_json(payload["record"])
                or canonical_json(continuations(command, expected, state)) != canonical_json(payload["continuations"])):
            raise ModelValidationError("governance Event disagrees with deterministic transition")
        return expected
    except (PolicyViolation, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ModelValidationError):
            raise
        raise ModelValidationError("invalid governance Event") from exc


def validate_command_effect(event, command):
    payload = event.payload
    if (payload["command_type"] != command.type or event.type not in COMMAND_TERMINALS[command.type]
            or payload["actor_id"] != command.actor_id
            or canonical_json(payload["command_payload"]) != canonical_json(command.payload)
            or canonical_json(payload["expected_revision"]) != canonical_json(command.expected_revision)
            or payload["context"]["idempotency_key"] != command.idempotency_key):
        raise ModelValidationError("governance fact differs from its Command")
