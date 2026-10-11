"""Recompute each accepted quality effect without live Runtime or IO calls."""

from aetp.collaboration.policy import PolicyViolation, canonical_json
from aetp.domain.models import Command, ModelValidationError
from aetp.quality.contracts import COMMAND_AGGREGATES, COMMAND_TERMINALS, SCHEMA
from aetp.quality.records import evaluate
from aetp.quality.lifecycle import finish_continuation


def reduce_record(event, previous, state):
    try:
        payload = event.payload
        if (set(payload) != {"quality_schema", "command", "context", "observed_at_ms",
                             "effect_index", "effect_count", "record"} or payload["quality_schema"] != SCHEMA):
            raise ModelValidationError("unsupported quality fact envelope")
        command = Command.from_dict(payload["command"])
        if (command.type not in COMMAND_AGGREGATES or command.id != event.causation_id
                or command.project_id != event.project_id or command.correlation_id != event.correlation_id):
            raise ModelValidationError("quality fact has another Command identity")
        index, count = payload["effect_index"], payload["effect_count"]
        if command.type == "task.quality.complete" and index == 1:
            if type(index) is not int or type(count) is not int or count != 2:
                raise ModelValidationError("invalid completion continuation index/count")
            record = finish_continuation(command, previous, payload["observed_at_ms"], payload["context"])
            if (event.type != "task.completed" or event.aggregate_type != "task" or event.aggregate_id != command.target_id
                    or event.aggregate_revision != record["revision"]
                    or canonical_json(payload["record"]) != canonical_json(record)):
                raise ModelValidationError("terminal completion differs from its validated continuation")
            return record
        effects = evaluate(command, state, payload["observed_at_ms"], payload["context"])
        if type(index) is not int or type(count) is not int or count != len(effects) or not 0 <= index < count:
            raise ModelValidationError("quality effect index/count differs from Command")
        kind, aggregate, identifier, record = effects[index]
        if event.type == "review.quality_requested" and previous is not None:
            raise ModelValidationError("quality Review identity is immutable")
        if event.type == "task.in_review" and any(canonical_json(state.get(f"review:{effect[2]}"))
                != canonical_json(effect[3]) for effect in effects[:-1]):
            raise ModelValidationError("Task review stage requires every preceding Review")
        if ((event.type, event.aggregate_type, event.aggregate_id) != (kind, aggregate, identifier)
                or event.aggregate_revision != record["revision"]
                or canonical_json(payload["record"]) != canonical_json(record)):
            raise ModelValidationError("quality fact differs from deterministic transition")
        return record
    except (PolicyViolation, KeyError, TypeError, ValueError, RecursionError, OverflowError) as exc:
        if isinstance(exc, ModelValidationError):
            raise
        raise ModelValidationError("invalid quality fact") from exc


def validate_command_effect(event, command):
    if canonical_json(event.payload["command"]) != canonical_json(command.to_dict()):
        raise ModelValidationError("quality effect differs from persisted Command")
    final = event.payload["effect_index"] == event.payload["effect_count"] - 1
    if final and event.type not in COMMAND_TERMINALS[command.type]:
        raise ModelValidationError("quality terminal differs from Command")
    return final
