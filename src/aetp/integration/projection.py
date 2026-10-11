"""Independent exact declaration recomputation from facts, without ingress IO."""
from aetp.collaboration.policy import PolicyViolation, canonical_json
from aetp.domain.models import Command, ModelValidationError
from aetp.integration.contracts import DOMAIN_EVENTS, SCHEMA
from aetp.integration.records import evaluate


def effect_command(event):
    payload = event.payload
    if (set(payload) != {"integration_schema", "command", "context", "observed_at_ms", "effect_index", "effect_count", "record"}
            or payload["integration_schema"] != SCHEMA or event.type not in DOMAIN_EVENTS):
        raise ModelValidationError("unsupported Integration envelope")
    command = Command.from_dict(payload["command"])
    if (command.id != event.causation_id
            or command.project_id != event.project_id or command.correlation_id != event.correlation_id
            or canonical_json(command.to_dict()) != canonical_json(payload["command"])
            or type(payload["effect_index"]) is not int or payload["effect_index"] != 0
            or type(payload["effect_count"]) is not int or payload["effect_count"] != 1):
        raise ModelValidationError("Integration effect differs from Command identity or single-effect contract")
    return command


def reduce_record(event, previous, state):
    try:
        command = effect_command(event)
        if event.type == "project.integration_declared":
            if canonical_json(previous) != canonical_json(state.get(f"project:{event.project_id}")):
                raise ModelValidationError("Integration previous record differs from prefix")
            effects = evaluate(command, state, event.payload["observed_at_ms"], event.payload["context"])
            kind, aggregate, identifier, record = effects[0]
            if (len(effects) != 1 or (event.type, event.aggregate_type, event.aggregate_id) != (kind, aggregate, identifier)
                    or event.aggregate_revision != record["revision"]
                    or canonical_json(event.payload["record"]) != canonical_json(record)):
                raise ModelValidationError("Integration record differs from deterministic declaration")
            return record
        # Task aggregate transitions
        record = event.payload["record"]
        if (event.aggregate_type != "task" or event.aggregate_revision != record.get("revision")
                or event.aggregate_id != record.get("id")):
            raise ModelValidationError("Integration task record mismatch")
        return record
    except (PolicyViolation, KeyError, TypeError, ValueError, RecursionError, OverflowError) as exc:
        if isinstance(exc, ModelValidationError):
            raise
        raise ModelValidationError("invalid Integration declaration fact") from exc


def validate_command_effect(event, command):
    if event.type == "command.rejected":
        context = event.payload["error"]["context"]
        expected = {"command_id": command.id, "target_id": command.target_id,
                    "expected_revision": command.expected_revision}
        if canonical_json({key: context[key] for key in expected}) != canonical_json(expected):
            raise ModelValidationError("Integration rejection differs from persisted Command")
        return True
    actual = effect_command(event)
    if canonical_json(actual.to_dict()) != canonical_json(command.to_dict()):
        raise ModelValidationError("Integration effect differs from persisted Command")
    return True
