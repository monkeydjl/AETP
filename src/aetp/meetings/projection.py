"""Pure lifecycle checkpoints and Command/effect validation."""

import copy
from types import SimpleNamespace

from aetp.collaboration.policy import PolicyViolation, canonical_json
from aetp.domain.models import ModelValidationError
from aetp.meetings.contracts import COMMAND_AGGREGATES, COMMAND_TERMINALS
from aetp.meetings.policy import natural, projected_time
from aetp.meetings.records import create_conversation, event_type, step_conversation


def reduce_record(event, previous, state):
    try:
        payload = event.payload
        if set(payload) != {"record", "command_type", "command_payload"}:
            raise ModelValidationError("unexpected structured collaboration Event fields")
        record, kind = payload["record"], payload["command_type"]
        if kind not in COMMAND_AGGREGATES or event.type not in COMMAND_TERMINALS[kind]:
            raise ModelValidationError("unsupported structured collaboration effect")
        actor = record.get("proposed_by") if event.aggregate_type == "decision" else record.get("last_actor_id")
        command = SimpleNamespace(id=event.causation_id, project_id=event.project_id, actor_id=actor,
            type=kind, target_id=event.aggregate_id, payload=payload["command_payload"],
            expected_revision=previous["revision"] if previous else 0)
        if event.aggregate_type == "decision":
            from aetp.decisions.projection import reduce_proposal
            expected = reduce_proposal(command, record, previous, state)
        else:
            at = natural(record["observed_at_ms"])
            if at < max((value.get("observed_at_ms", 0) for value in state.values()), default=0):
                raise PolicyViolation("CLOCK_REGRESSION")
            elapsed = projected_time(state[f"project:{event.project_id}"], at)
            if previous is None:
                if kind not in {"discussion.open", "meeting.create"}:
                    raise ModelValidationError("missing conversation")
                expected = create_conversation(command, state, record["meter_source"], at, elapsed)
            else:
                expected = step_conversation(command, previous, record["checkpoint"], state, at, elapsed)
            if event.type != event_type(command, expected) or canonical_json(record) != canonical_json(expected):
                raise ModelValidationError("invalid conversation transition or checkpoint")
        if (expected["id"], expected["project_id"], expected["revision"]) != (
                event.aggregate_id, event.project_id, event.aggregate_revision):
            raise ModelValidationError("structured record identity or revision mismatch")
        if event.aggregate_type != "decision":
            history = copy.deepcopy(previous["checkpoint_history"]) if previous else []
            if not history or expected["checkpoint"] != history[-1]:
                history.append(copy.deepcopy(expected["checkpoint"]))
            expected["checkpoint_history"] = history
        return expected
    except (PolicyViolation, KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, ModelValidationError):
            raise
        raise ModelValidationError("invalid structured collaboration Event") from exc


def validate_command_effect(event, command):
    payload, record = event.payload, event.payload["record"]
    actor = record["proposed_by"] if event.aggregate_type == "decision" else record["last_actor_id"]
    creation = command.type in {"discussion.open", "meeting.create", "decision.propose"}
    if (payload["command_type"] != command.type
            or canonical_json(payload["command_payload"]) != canonical_json(command.payload)
            or actor != command.actor_id
            or (creation and command.expected_revision not in (None, 0))
            or (not creation and command.expected_revision != event.aggregate_revision - 1)):
        raise ModelValidationError("structured effect does not match its persisted Command")
