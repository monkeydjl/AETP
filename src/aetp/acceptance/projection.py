"""Pure reduction binds each new fact to its complete accepted Command."""

from aetp.acceptance.contracts import COMMAND_AGGREGATES, COMMAND_TERMINALS, SCHEMA
from aetp.acceptance.records import evaluate
from aetp.collaboration.policy import PolicyViolation, canonical_json
from aetp.domain.models import Command, ModelValidationError


def reduce_record(event, previous, state):
    try:
        payload = event.payload
        if (set(payload) != {"acceptance_schema", "command", "context", "observed_at_ms", "record"}
                or payload["acceptance_schema"] != SCHEMA):
            raise ModelValidationError("unexpected Acceptance Event fields")
        command = Command.from_dict(payload["command"])
        if (command.type not in COMMAND_AGGREGATES or command.id != event.causation_id
                or command.project_id != event.project_id or command.correlation_id != event.correlation_id):
            raise ModelValidationError("Acceptance fact has a different Command identity")
        effects = evaluate(command, state, payload["observed_at_ms"], payload["context"])
        matches = [record for kind, aggregate, identifier, record in effects
                   if (kind, aggregate, identifier) == (event.type, event.aggregate_type, event.aggregate_id)]
        if len(matches) != 1:
            raise ModelValidationError("Acceptance fact has a different effect address")
        expected = matches[0]
        if expected["revision"] != event.aggregate_revision or canonical_json(expected) != canonical_json(payload["record"]):
            raise ModelValidationError("Acceptance fact disagrees with deterministic transition")
        if event.type == "artifact.verification_reported" and previous is not None:
            raise ModelValidationError("Verification evidence identity is immutable")
        if event.type == "verification.finished":
            evidence = state.get(f"artifact:{expected['evidence_id']}")
            if canonical_json(evidence) != canonical_json(effects[0][3]):
                raise ModelValidationError("Verification requires its exact preceding evidence")
        return expected
    except (PolicyViolation, KeyError, TypeError, ValueError, RecursionError, OverflowError) as exc:
        if isinstance(exc, ModelValidationError):
            raise
        raise ModelValidationError("invalid Acceptance Event") from exc


def validate_command_effect(event, command):
    if ((event.type not in COMMAND_TERMINALS[command.type] and not (
            command.type == "verification.record" and event.type == "artifact.verification_reported"))
            or canonical_json(event.payload["command"]) != canonical_json(command.to_dict())):
        raise ModelValidationError("Acceptance fact differs from persisted Command")
