"""Pure, project-scoped reduction of the Event types implemented by M0.

This module has no persistence or dispatch dependencies.  A live reducer
consumes a complete ordered stream; ``rebuild`` sorts that stream first.
State is disposable, and callers only receive detached copies of it.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable
from typing import Any

from aetp.domain.models import AGENT_STATUSES, PROJECT_STATUSES, Command, Event, ModelValidationError
from aetp.collaboration.contracts import COMMAND_AGGREGATES, COMMAND_TERMINALS, DOMAIN_EVENTS
from aetp.runtime.contracts import (
    COMMAND_AGGREGATES as EXECUTION_COMMANDS, COMMAND_TERMINALS as EXECUTION_TERMINALS,
    DOMAIN_EVENTS as EXECUTION_EVENTS, EVENT_AGGREGATES as EXECUTION_ADDRESSES,
    effect_address,
)
from aetp.meetings.contracts import (
    COMMAND_AGGREGATES as DISCUSSION_COMMANDS, COMMAND_TERMINALS as DISCUSSION_TERMINALS,
    DOMAIN_EVENTS as DISCUSSION_EVENTS,
)
from aetp.governance.contracts import (
    COMMAND_AGGREGATES as GOVERNANCE_COMMANDS, COMMAND_TERMINALS as GOVERNANCE_TERMINALS,
    DOMAIN_EVENTS as GOVERNANCE_EVENTS, SCHEMA as GOVERNANCE_SCHEMA,
)
from aetp.governance.causality import CausalCursor
from aetp.planning.contracts import (
    COMMAND_AGGREGATES as PLANNING_COMMANDS, COMMAND_TERMINALS as PLANNING_TERMINALS,
    DOMAIN_EVENTS as PLANNING_EVENTS, SCHEMA as PLANNING_SCHEMA,
)
from aetp.planning.causality import PlanningCursor
from aetp.acceptance.contracts import (
    COMMAND_AGGREGATES as ACCEPTANCE_COMMANDS, COMMAND_TERMINALS as ACCEPTANCE_TERMINALS,
    DOMAIN_EVENTS as ACCEPTANCE_EVENTS, SCHEMA as ACCEPTANCE_SCHEMA, report_id, reserved_report_id,
)
from aetp.acceptance.causality import AcceptanceCursor
from aetp.quality.contracts import (
    COMMAND_AGGREGATES as QUALITY_COMMANDS, COMMAND_TERMINALS as QUALITY_TERMINALS,
    DOMAIN_EVENTS as QUALITY_EVENTS, SCHEMA as QUALITY_SCHEMA, effect_address as quality_effect_address,
)
from aetp.quality.causality import QualityCursor
from aetp.integration.contracts import (
    COMMAND_AGGREGATES as INTEGRATION_COMMANDS, COMMAND_TERMINALS as INTEGRATION_TERMINALS,
    DOMAIN_EVENTS as INTEGRATION_EVENTS, EVENT_AGGREGATES as INTEGRATION_ADDRESSES,
    SCHEMA as INTEGRATION_SCHEMA,
)
from aetp.integration.causality import IntegrationCursor
from aetp.bootstrap.contracts import DOMAIN_EVENTS as BOOTSTRAP_EVENTS


_AUDIT_TYPES = frozenset({"command.received", "command.rejected"})
_CREATION_TYPES = frozenset({"project.created", "agent.created", "task.created"})
_DOMAIN_TYPES = (_CREATION_TYPES | {"task.claimed", "task.requeued"} | DOMAIN_EVENTS | EXECUTION_EVENTS
                 | DISCUSSION_EVENTS | GOVERNANCE_EVENTS | PLANNING_EVENTS | ACCEPTANCE_EVENTS | QUALITY_EVENTS | INTEGRATION_EVENTS | BOOTSTRAP_EVENTS)


class Projection:
    """An in-memory view of one project's complete M0 Event stream.

    The SQLite Sequencer emits a gapless stream from sequence one.  Missing
    entries in that stream fail closed rather than producing partial State.
    Exact redelivery is harmless; conflicting identities are not redelivery.
    """

    def __init__(self, project_id: str | None = None):
        if project_id is not None and (
            not isinstance(project_id, str)
            or not project_id.strip()
            or project_id != project_id.strip()
        ):
            raise ValueError("project_id must be a non-empty string")
        self._project_id = project_id
        self._state: dict[str, dict[str, Any]] = {}
        self._last_sequence = 0
        self._seen: dict[str, str] = {}
        self._governance_cursor = CausalCursor()
        self._planning_cursor = PlanningCursor()
        self._acceptance_cursor = AcceptanceCursor()
        self._quality_cursor = QualityCursor()
        self._integration_cursor = IntegrationCursor()

    @property
    def project_id(self) -> str | None:
        return self._project_id

    @property
    def last_sequence(self) -> int:
        return self._last_sequence

    @property
    def state(self) -> dict[str, dict[str, Any]]:
        return copy.deepcopy(self._state)

    @classmethod
    def _from_cache(
        cls, project_id: str, state: dict[str, dict[str, Any]], last_sequence: int
    ) -> "Projection":
        """Internal append continuation, after the store checked cache integrity.

        Only new Events may be applied to this cursor.  SQLite's immutable
        Event ID/sequence constraints retain deduplication for earlier facts.
        This is not a public State mutation or recovery interface.
        """
        project = state.get(f"project:{project_id}", {})
        if "integration_contract" in project:
            raise ValueError("Integration continuation requires complete facts, not an aggregate-only cache")
        if project.get("governance") or project.get("planning") or project.get("task_quality_policy"):
            # The old cache has only aggregate State, not the causal cursor.
            # Rebuild from facts instead of losing incomplete compound proofs.
            raise ValueError("governance continuation cursor requires complete facts")
        if "execution_policy_version" in project and "collaboration_clock" not in project:
            # Older M1 caches predate the independent pause accumulator. The
            # store catches ValueError here and rebuilds from immutable facts.
            raise ValueError("Projection cache predates collaboration clock metadata")
        if any(key.startswith(("meeting:", "discussion:")) and (
                not isinstance(record, dict) or "checkpoint_history" not in record)
                for key, record in state.items()):
            raise ValueError("Projection cache predates collaboration checkpoint history")
        projection = cls(project_id)
        projection._state = copy.deepcopy(state)
        projection._last_sequence = last_sequence
        return projection

    def apply(self, event: Event) -> None:
        """Apply one fact atomically in memory, or raise without changing State."""
        if not isinstance(event, Event):
            raise TypeError("event must be an Event")
        if self._project_id is not None and event.project_id != self._project_id:
            raise ModelValidationError("one Projection cannot mix projects")
        if event.type not in _AUDIT_TYPES | _DOMAIN_TYPES:
            raise ModelValidationError(f"unsupported M0 projection Event: {event.type}")
        canonical = event.to_json()
        if event.id in self._seen:
            if self._seen[event.id] != canonical:
                raise ModelValidationError("conflicting duplicate Event identity")
            return
        if event.sequence != self._last_sequence + 1:
            raise ModelValidationError("duplicate or missing Event sequence")

        if (event.type in INTEGRATION_EVENTS or "integration_schema" in event.payload) and (
                event.type not in INTEGRATION_EVENTS or event.payload.get("integration_schema") != INTEGRATION_SCHEMA):
            raise ModelValidationError("Integration Event requires its supported domain-only envelope")
        key = f"{event.aggregate_type}:{event.aggregate_id}"
        updated = None
        if event.type == "command.received" and event.payload.get("command_type") in INTEGRATION_COMMANDS:
            current_revision = self._state.get(key, {}).get("revision", 0)
            if event.aggregate_revision != current_revision:
                raise ModelValidationError("Integration receipt differs from current aggregate revision")
        if event.type == "command.received" and event.payload.get("command_type") in ACCEPTANCE_COMMANDS:
            current_revision = self._state.get(key, {}).get("revision", 0)
            if event.aggregate_revision != current_revision:
                raise ModelValidationError("Acceptance receipt differs from current aggregate revision")
        if event.type == "command.received" and event.payload.get("command_type") in QUALITY_COMMANDS:
            current_revision = self._state.get(key, {}).get("revision", 0)
            if event.aggregate_revision != current_revision:
                raise ModelValidationError("quality receipt differs from current aggregate revision")
        if event.type in _AUDIT_TYPES and "planning_schema" in event.payload:
            raise ModelValidationError("audit Event cannot carry a planning effect envelope")
        if event.type in _AUDIT_TYPES and "acceptance_schema" in event.payload:
            raise ModelValidationError("audit Event cannot carry an Acceptance effect envelope")
        if event.type in _AUDIT_TYPES and "quality_schema" in event.payload:
            raise ModelValidationError("audit Event cannot carry a quality effect envelope")
        if event.type not in _AUDIT_TYPES:
            from aetp.integration.guards import validate_fact as validate_integration_fact
            validate_integration_fact(event, self._state)
            from aetp.planning.guards import validate_fact
            validate_fact(event, self._state)
            if (event.aggregate_type == "artifact" and reserved_report_id(event.aggregate_id)
                    and event.type != "artifact.verification_reported"
                    and self._state.get(f"project:{event.project_id}", {}).get("quality")):
                raise ModelValidationError("Quality-enabled Project reserves Verification report identities")
            if (event.type in ACCEPTANCE_EVENTS or "acceptance_schema" in event.payload) and (
                    event.type not in ACCEPTANCE_EVENTS or event.payload.get("acceptance_schema") != ACCEPTANCE_SCHEMA):
                raise ModelValidationError("Acceptance Event requires its supported schema")
            if (event.type in QUALITY_EVENTS or "quality_schema" in event.payload) and (
                    event.type not in QUALITY_EVENTS or event.payload.get("quality_schema") != QUALITY_SCHEMA):
                raise ModelValidationError("quality Event requires its supported schema")
            if (event.type in PLANNING_EVENTS or "planning_schema" in event.payload) and (
                    event.type not in PLANNING_EVENTS or event.payload.get("planning_schema") != PLANNING_SCHEMA):
                raise ModelValidationError("planning Event requires its supported schema")
            marker = event.payload.get("governance_schema")
            governed_control = event.type in {"project.paused", "project.resumed"} and self._state.get(
                f"project:{event.project_id}", {}).get("governance")
            requires_governance = event.type in GOVERNANCE_EVENTS - {"project.paused", "project.resumed"} or governed_control
            if ("governance_schema" in event.payload or requires_governance) and marker != GOVERNANCE_SCHEMA:
                raise ModelValidationError("governance Event requires its supported schema and causal proof")
            if event.type == "agent.created":
                from aetp.collaboration.policy import PolicyViolation
                from aetp.governance.policy import validate_agent_identity
                try:
                    validate_agent_identity(self._state, event.project_id, event.aggregate_id)
                except PolicyViolation as exc:
                    raise ModelValidationError("Agent fact conflicts with a reserved identity") from exc
            expected_type = INTEGRATION_ADDRESSES.get(event.type, EXECUTION_ADDRESSES.get(event.type, event.type.split(".", 1)[0]))
            if expected_type != event.aggregate_type:
                raise ModelValidationError("Event type does not match aggregate type")
            if event.aggregate_type == "project" and event.aggregate_id != event.project_id:
                raise ModelValidationError("Project Event has a different project address")
            if event.type in INTEGRATION_EVENTS:
                from aetp.integration.projection import reduce_record
                updated = reduce_record(event, self._state.get(key), self._state)
            elif event.type in QUALITY_EVENTS:
                from aetp.quality.projection import reduce_record
                updated = reduce_record(event, self._state.get(key), self._state)
            elif event.type in ACCEPTANCE_EVENTS:
                from aetp.acceptance.projection import reduce_record
                updated = reduce_record(event, self._state.get(key), self._state)
            elif event.type in PLANNING_EVENTS:
                from aetp.planning.projection import reduce_record
                updated = reduce_record(event, self._state.get(key), self._state)
            elif event.payload.get("governance_schema") == GOVERNANCE_SCHEMA:
                if event.type not in GOVERNANCE_EVENTS:
                    raise ModelValidationError("unsupported governance Event")
                from aetp.governance.projection import reduce_record
                updated = reduce_record(event, self._state.get(key), self._state)
            elif event.type in EXECUTION_EVENTS and (
                event.type not in {"task.claimed", "task.requeued"}
                or self._state.get(key, {}).get("execution_policy_version")
            ):
                from aetp.runtime.projection import reduce_record
                updated = reduce_record(event, self._state.get(key), self._state)
            elif event.type in DISCUSSION_EVENTS:
                from aetp.meetings.projection import reduce_record
                updated = reduce_record(event, self._state.get(key), self._state)
            elif event.type in DOMAIN_EVENTS:
                from aetp.collaboration.projection import reduce_record
                updated = reduce_record(event, self._state.get(key), self._state)
            elif event.type in BOOTSTRAP_EVENTS:
                from aetp.bootstrap.records import reduce_bootstrap_event
                updated = reduce_bootstrap_event(event, self._state.get(key), self._state)
            else:
                updated = self._reduce_domain(event, self._state.get(key))
                if event.type == "task.created" and "execution_policy_version" in event.payload:
                    from aetp.runtime.projection import task_metadata
                    updated.update(task_metadata({**event.payload, "project_id": event.project_id}, self._state))

            if event.type == "project.execution_configured":
                updated["collaboration_clock"] = copy.deepcopy(self._state[key].get(
                    "collaboration_clock", {"excluded_ms": 0, "paused_at_ms": None}))
            if event.type in {"project.paused", "project.resumed"}:
                # The M2 wall-time origin is independent of optional M1 clock
                # configuration. This is derived only from Project facts.
                clock = copy.deepcopy(self._state[key].get("collaboration_clock",
                    {"excluded_ms": 0, "paused_at_ms": None}))
                at = event.payload["observed_at_ms"]
                if event.type == "project.paused":
                    clock["paused_at_ms"] = at
                else:
                    if clock["paused_at_ms"] is None:
                        raise ModelValidationError("missing durable pause interval")
                    clock["excluded_ms"] += at - clock["paused_at_ms"]
                    clock["paused_at_ms"] = None
                updated["collaboration_clock"] = clock

        if updated is not None:
            from aetp.integration.guards import validate_record as validate_integration_record
            validate_integration_record(event, self._state.get(key), updated, self._state)

        planning_cursor = self._planning_cursor.advance(event)
        causal_cursor = self._governance_cursor.advance(event)
        acceptance_cursor = self._acceptance_cursor.advance(event)
        quality_cursor = self._quality_cursor.advance(event)
        integration_cursor = self._integration_cursor.advance(event)
        # All checks happen before publishing any change, including the cursor
        # and identity binding.  Rejection audits consume sequence, not revision.
        if updated is not None:
            self._state[key] = updated
        self._project_id = event.project_id
        self._last_sequence = event.sequence
        self._seen[event.id] = canonical
        self._governance_cursor = causal_cursor
        self._planning_cursor = planning_cursor
        self._acceptance_cursor = acceptance_cursor
        self._quality_cursor = quality_cursor
        self._integration_cursor = integration_cursor

    @staticmethod
    def _text(payload: dict[str, Any], field: str) -> str:
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ModelValidationError(f"Event payload requires non-empty {field}")
        return value

    @classmethod
    def _reduce_domain(
        cls, event: Event, previous: dict[str, Any] | None
    ) -> dict[str, Any]:
        payload = event.payload
        if event.type in _CREATION_TYPES:
            if previous is not None or event.aggregate_revision != 0:
                raise ModelValidationError("creation requires an absent aggregate at revision zero")
            updated: dict[str, Any] = {
                "id": event.aggregate_id,
                "project_id": event.project_id,
                "revision": event.aggregate_revision,
            }
            # Old low-level model/storage fixtures contain partial creation
            # metadata.  Preserve only known fields; never invent missing titles
            # or let arbitrary payload keys override identity/revision/ownership.
            if "status" in payload:
                status = cls._text(payload, "status")
                allowed = {
                    "project": PROJECT_STATUSES,
                    "agent": AGENT_STATUSES,
                    "task": {"pending"},
                }[event.aggregate_type]
                if status not in allowed:
                    raise ModelValidationError("invalid M0 creation status")
                updated["status"] = status
            if event.aggregate_type == "agent" and "model_id" in payload:
                updated["model_id"] = cls._text(payload, "model_id")
            if event.aggregate_type == "task":
                if "title" in payload:
                    updated["title"] = cls._text(payload, "title")
                updated["owner_id"] = None
                if "policy_version" in payload:
                    from aetp.collaboration.projection import task_metadata
                    updated.update(task_metadata(payload))
            return updated

        if previous is None or event.aggregate_revision != previous["revision"] + 1:
            raise ModelValidationError("missing aggregate or aggregate revision gap")
        updated = dict(previous)
        actor_id = cls._text(payload, "actor_id")
        if event.type == "task.claimed":
            if previous.get("status") != "pending" or previous.get("owner_id") is not None:
                raise ModelValidationError("claim requires an unowned pending Task")
            if payload.get("status", "assigned") != "assigned":
                raise ModelValidationError("claim must project assigned status")
            updated.update(status="assigned", owner_id=actor_id)
        elif event.type == "task.requeued":
            if previous.get("status") != "assigned" or previous.get("owner_id") != actor_id:
                raise ModelValidationError("M0 release requires the current Task owner")
            if payload.get("status", "pending") != "pending" or payload.get("reason") != "release":
                raise ModelValidationError("only release requeue is implemented in M0")
            updated.update(status="pending", owner_id=None)
        updated["revision"] = event.aggregate_revision
        return updated

    @classmethod
    def rebuild(cls, events: Iterable[Event]) -> dict[str, dict[str, Any]]:
        """Rebuild detached State without executing Commands, tools, or IO."""
        ordered = list(events)
        if any(not isinstance(event, Event) for event in ordered):
            raise TypeError("events must contain Event objects")
        projection = cls()
        for event in sorted(ordered, key=lambda fact: fact.sequence):
            projection.apply(event)
        return projection.state


    @classmethod
    def pending_command_ids(
        cls, events: Iterable[Event], commands: Iterable[Command],
    ) -> list[str]:
        """Pure implemented receipt/terminal projection, never an execution queue.

        Caller supplies Command/Event facts from one project and one snapshot.
        Validate the causal chain instead of trusting a disposable result index
        or treating an arbitrary event with the same cause as a terminal result.
        """
        ordered = list(events)
        command_list = list(commands)
        if any(not isinstance(event, Event) for event in ordered):
            raise TypeError("events must contain Event objects")
        if any(not isinstance(command, Command) for command in command_list):
            raise TypeError("commands must contain Command objects")
        by_id = {}
        for command in command_list:
            # Python equality collapses JSON booleans/numbers (True == 1,
            # 1 == 1.0). Identity follows the same canonical content as digest.
            if (
                command.id in by_id
                and by_id[command.id].to_json() != command.to_json()
            ):
                raise ModelValidationError("conflicting duplicate Command identity")
            by_id[command.id] = command
        projects = {command.project_id for command in command_list}
        projects.update(event.project_id for event in ordered)
        if len(projects) > 1:
            raise ModelValidationError("one pending projection cannot mix projects")

        terminal_types = {
            "project.create": "project.created", "agent.register": "agent.created",
            "task.create": "task.created", "task.claim": "task.claimed",
            "task.release": "task.requeued",
        }
        projection = cls()
        receipts: dict[str, Event] = {}
        terminal_ids: set[str] = set()
        precheck_evidence: set[str] = set()
        acceptance_evidence: set[str] = set()
        seen: set[str] = set()
        for event in sorted(ordered, key=lambda fact: fact.sequence):
            projection.apply(event)  # Validate the full stream, including gaps.
            if event.id in seen:
                continue
            seen.add(event.id)
            command = by_id.get(event.causation_id)
            if command is None:
                raise ModelValidationError("Event has no matching persisted Command")
            # Mirror the existing M0 Handler's audit address for both success
            # and rejected unsupported/missing-target Commands. Not a new role
            # or execution permission rule, and not a general Command vocabulary.
            if command.type in INTEGRATION_COMMANDS and command.target_id:
                address = (INTEGRATION_COMMANDS[command.type], command.target_id)
            elif command.type in QUALITY_COMMANDS and command.target_id:
                address = (QUALITY_COMMANDS[command.type], command.target_id)
            elif command.type in ACCEPTANCE_COMMANDS and command.target_id:
                address = (ACCEPTANCE_COMMANDS[command.type], command.target_id)
            elif command.type in PLANNING_COMMANDS and command.target_id:
                address = (PLANNING_COMMANDS[command.type], command.target_id)
            elif command.type in GOVERNANCE_COMMANDS and command.target_id:
                address = (GOVERNANCE_COMMANDS[command.type], command.target_id)
            elif command.type in DISCUSSION_COMMANDS and command.target_id:
                address = (DISCUSSION_COMMANDS[command.type], command.target_id)
            elif command.type in EXECUTION_COMMANDS and command.target_id:
                address = (EXECUTION_COMMANDS[command.type], command.target_id)
            elif command.type in COMMAND_AGGREGATES and command.target_id:
                address = (COMMAND_AGGREGATES[command.type], command.target_id)
            elif command.type == "project.create":
                address = ("project", command.project_id)
            elif command.type == "agent.register" and command.target_id:
                address = ("agent", command.target_id)
            elif command.target_id:
                address = ("task", command.target_id)
            else:
                address = ("project", command.project_id)
            is_precheck_evidence = command.type == "verification.run" and event.type == "artifact.created"
            is_acceptance_evidence = command.type == "verification.record" and event.type == "artifact.verification_reported"
            event_address = ("artifact", f"{command.target_id}:evidence") if is_precheck_evidence else address
            if is_acceptance_evidence:
                event_address = ("artifact", report_id(command.project_id, command.target_id))
            if event.type not in _AUDIT_TYPES and effect_address(command) is not None:
                event_address = effect_address(command)
            if event.type not in _AUDIT_TYPES and command.type in QUALITY_COMMANDS:
                event_address = quality_effect_address(command, event.payload["effect_index"])
            if (
                event.project_id != command.project_id
                or event.correlation_id != command.correlation_id
                or (event.aggregate_type, event.aggregate_id) != event_address
            ):
                raise ModelValidationError("Event identity/target does not match Command")
            if event.type == "command.received":
                if command.id in receipts:
                    raise ModelValidationError("Command has multiple distinct receipt Events")
                if (
                    event.payload.get("command_type") != command.type
                    or event.payload.get("request_digest") != command.digest()
                ):
                    raise ModelValidationError("receipt type/digest does not match Command")
                receipts[command.id] = event
            else:
                if command.id not in receipts:
                    raise ModelValidationError("terminal Event has no prior Command receipt")
                if command.id in terminal_ids:
                    raise ModelValidationError("Command has contradictory M0 terminal Events")
                if command.type in INTEGRATION_COMMANDS:
                    from aetp.integration.projection import validate_command_effect
                    validate_command_effect(event, command)
                if command.type in ACCEPTANCE_COMMANDS and event.type != "command.rejected":
                    from aetp.acceptance.projection import validate_command_effect
                    validate_command_effect(event, command)
                if command.type in QUALITY_COMMANDS and event.type != "command.rejected":
                    from aetp.quality.projection import validate_command_effect
                    if not validate_command_effect(event, command):
                        continue
                if is_acceptance_evidence:
                    if command.id in acceptance_evidence:
                        raise ModelValidationError("Verification Command has multiple report Artifacts")
                    acceptance_evidence.add(command.id)
                    continue
                if is_precheck_evidence:
                    if command.id in precheck_evidence:
                        raise ModelValidationError("Verification Command has multiple evidence Artifacts")
                    precheck_evidence.add(command.id)
                    continue
                if event.type == "command.rejected":
                    if command.id in precheck_evidence or command.id in acceptance_evidence:
                        raise ModelValidationError("rejected Command cannot retain precheck effects")
                    error = event.payload.get("error")
                    if not isinstance(error, dict) or not isinstance(error.get("code"), str) or not error["code"].strip():
                        raise ModelValidationError("rejection Event has no typed error")
                elif event.type not in INTEGRATION_TERMINALS.get(command.type, QUALITY_TERMINALS.get(command.type, ACCEPTANCE_TERMINALS.get(command.type, PLANNING_TERMINALS.get(command.type, GOVERNANCE_TERMINALS.get(command.type, DISCUSSION_TERMINALS.get(command.type,
                        EXECUTION_TERMINALS.get(command.type, COMMAND_TERMINALS.get(command.type, {terminal_types.get(command.type)})))))))):
                    raise ModelValidationError("terminal Event type does not match M0 Command")
                elif command.type == "verification.run" and command.id not in precheck_evidence:
                    raise ModelValidationError("Verification has no preceding evidence Artifact")
                if event.type != "command.rejected" and command.type in PLANNING_COMMANDS:
                    from aetp.planning.projection import validate_command_effect
                    validate_command_effect(event, command)
                elif event.type != "command.rejected" and event.payload.get("governance_schema") == GOVERNANCE_SCHEMA:
                    from aetp.governance.projection import validate_command_effect
                    validate_command_effect(event, command)
                elif event.type != "command.rejected" and command.type in EXECUTION_COMMANDS:
                    from aetp.runtime.projection import validate_command_effect
                    validate_command_effect(event, command)
                if (event.type != "command.rejected" and command.type in DISCUSSION_COMMANDS
                        and event.payload.get("governance_schema") != GOVERNANCE_SCHEMA):
                    from aetp.meetings.projection import validate_command_effect
                    validate_command_effect(event, command)
                terminal_ids.add(command.id)
        if by_id.keys() - receipts.keys():
            raise ModelValidationError("persisted Command has no receipt Event")
        return [command_id for command_id in receipts
                if command_id not in terminal_ids or command_id in projection._governance_cursor.pending]


__all__ = ["Projection"]
