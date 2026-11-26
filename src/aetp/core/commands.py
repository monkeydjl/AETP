"""Transactional Command acceptance for the AETP M0 core kernel.

The handler deliberately keeps the write path small: a caller submits an
immutable :class:`~aetp.domain.models.Command`, the authenticated actor is
checked, current facts are read from the Event Store, and the resulting
Command plus Event batch are committed in one SQLite transaction.  There is
no State table or direct State mutation in this module; the projection layer
introduced by a later milestone will consume these Events.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from aetp.acceptance.contracts import COMMAND_AGGREGATES as ACCEPTANCE_COMMANDS
from aetp.acceptance.contracts import reserved_report_id
from aetp.collaboration.contracts import COMMAND_AGGREGATES
from aetp.core.idempotency import (
    IdempotencyConflict,
    IdempotencyResult,
    canonical_digest,
)
from aetp.domain.models import (
    AGENT_STATUSES,
    PROJECT_STATUSES,
    Command,
    Event,
    ModelValidationError,
)
from aetp.governance.contracts import COMMAND_AGGREGATES as GOVERNANCE_COMMANDS
from aetp.integration.contracts import COMMAND_AGGREGATES as INTEGRATION_COMMANDS
from aetp.meetings.contracts import COMMAND_AGGREGATES as DISCUSSION_COMMANDS
from aetp.planning.contracts import COMMAND_AGGREGATES as PLANNING_COMMANDS
from aetp.planning.contracts import EXECUTION_COMMANDS as PLANNING_GATED_COMMANDS
from aetp.quality.contracts import COMMAND_AGGREGATES as QUALITY_COMMANDS
from aetp.runtime.contracts import COMMAND_AGGREGATES as EXECUTION_COMMANDS
from aetp.storage.sqlite_store import SQLiteStore

_ACCEPTED = "accepted"
_REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class CommandResult:
    """Durable, JSON-compatible outcome of handling one Command."""

    status: str
    command_id: str
    event_ids: tuple[str, ...]
    aggregate_revision: int | None
    error_code: str | None

    def __post_init__(self) -> None:
        if self.status not in {_ACCEPTED, _REJECTED}:
            raise ValueError("status must be 'accepted' or 'rejected'")
        if not isinstance(self.command_id, str) or not self.command_id.strip():
            raise ValueError("command_id must be a non-empty string")
        if not isinstance(self.event_ids, tuple):
            raise TypeError("event_ids must be a tuple")
        if any(not isinstance(event_id, str) or not event_id.strip() for event_id in self.event_ids):
            raise ValueError("event_ids must contain non-empty strings")
        if self.aggregate_revision is not None and (
            isinstance(self.aggregate_revision, bool)
            or not isinstance(self.aggregate_revision, int)
            or self.aggregate_revision < 0
        ):
            raise ValueError("aggregate_revision must be a non-negative integer or None")
        if self.error_code is not None and (
            not isinstance(self.error_code, str) or not self.error_code.strip()
        ):
            raise ValueError("error_code must be None or a non-empty string")
        if self.status == _ACCEPTED and self.error_code is not None:
            raise ValueError("accepted results cannot contain an error_code")

    def to_dict(self) -> dict[str, Any]:
        """Return a detached JSON-compatible representation for SQLite."""
        return {
            "status": self.status,
            "command_id": self.command_id,
            "event_ids": list(self.event_ids),
            "aggregate_revision": self.aggregate_revision,
            "error_code": self.error_code,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CommandResult":
        if not isinstance(data, Mapping):
            raise TypeError("result must be an object")
        try:
            event_ids = data["event_ids"]
            if not isinstance(event_ids, (list, tuple)):
                raise TypeError("event_ids must be a list or tuple")
            return cls(
                status=data["status"],
                command_id=data["command_id"],
                event_ids=tuple(event_ids),
                aggregate_revision=data.get("aggregate_revision"),
                error_code=data.get("error_code"),
            )
        except KeyError as exc:
            raise ValueError(f"result is missing field: {exc.args[0]}") from exc


@dataclass(frozen=True, slots=True)
class _AggregateSnapshot:
    aggregate_type: str
    aggregate_id: str
    exists: bool
    revision: int
    status: str | None = None
    title: str | None = None
    model_id: str | None = None
    owner_id: str | None = None


class CommandHandler:
    """Validate and atomically submit the supported M0 Command types."""

    _BOOTSTRAP_ACTOR = "bootstrap"
    _SUPPORTED = frozenset(
        {
            "project.create",
            "agent.register",
            "task.create",
            "task.claim",
            "task.release",
        }
    )

    def __init__(self, store: SQLiteStore):
        if not isinstance(store, SQLiteStore):
            raise TypeError("store must be a SQLiteStore")
        self.store = store
        self._idempotency = IdempotencyResult(store)

    def handle(
        self,
        command: Command,
        *,
        authenticated_actor_id: str,
    ) -> CommandResult:
        """Handle *command* using the caller-provided authenticated identity.

        The idempotency lookup, command persistence, validation, Event append,
        and result index update all share one ``BEGIN IMMEDIATE`` transaction.
        An authenticated rejected Command retains received/rejected audit
        Events but no domain effect.  Actor mismatches only enter security
        diagnostics and cannot reserve authoritative Command IDs or keys.
        """
        if not isinstance(command, Command):
            raise TypeError("command must be a Command")
        authenticated_actor_id = self._authenticated_actor(authenticated_actor_id)
        request_digest = canonical_digest(command)
        scope = (
            command.project_id,
            authenticated_actor_id,
            command.idempotency_key,
        )

        with self.store.transaction():
            # Unbound input is not a protocol Command.  In particular it must
            # not reserve an ID or key that the legitimate actor will need.
            if command.actor_id != authenticated_actor_id:
                self.store.record_security_rejection(
                    command,
                    authenticated_actor_id=authenticated_actor_id,
                    error_code="ACTOR_MISMATCH",
                )
                return self._rejected(command, "ACTOR_MISMATCH")

            try:
                existing = self._idempotency.lookup(scope, request_digest)
            except IdempotencyConflict:
                return self._rejected(command, "IDEMPOTENCY_CONFLICT")
            if existing is not None:
                return existing

            # Persist the submitted immutable Command before evaluating domain
            # authorization.  The idempotency row is scoped to the trusted
            # connection identity, not to an actor string in the request.
            self.store.append_command(
                command,
                idempotency_actor_id=authenticated_actor_id,
            )

            # This gate is inside the final writer transaction and shared by
            # every service, including legacy callers that omit all metadata.
            planning_error = None
            if command.type in PLANNING_GATED_COMMANDS:
                from aetp.core.projection import Projection
                from aetp.planning.guards import command_error
                planning_error = command_error(command, Projection.rebuild(self.store.read_events(command.project_id)))
            if command.type in {"artifact.submit", "artifact.capture"} and reserved_report_id(command.target_id):
                planning_error = "ARTIFACT_ID_RESERVED"
            from aetp.integration.guards import GUARDED_COMMANDS
            from aetp.integration.guards import command_error as integration_error
            if not planning_error and command.type in GUARDED_COMMANDS:
                from aetp.core.projection import Projection
                # Never pre-read or cache the required set outside this writer.
                # Existing idempotent results above do not replay old policy effects.
                planning_error = integration_error(command, Projection.rebuild(self.store.read_events(command.project_id)))
            if planning_error:
                result, events = self._rejected(command, planning_error), []
            else:
                result, events = self._evaluate(command, authenticated_actor_id)
            if result.status == _REJECTED:
                result, events = self._rejection_events(command, result)
            self.store.append_events(events)

            self.store.record_idempotency_result(scope, result.to_dict())
            return result

    @staticmethod
    def _authenticated_actor(value: Any) -> str:
        if (
            not isinstance(value, str)
            or not value.strip()
            or value != value.strip()
        ):
            raise ValueError("authenticated_actor_id must be a non-empty string")
        return value

    @staticmethod
    def _rejected(command: Command, error_code: str) -> CommandResult:
        return CommandResult(
            status=_REJECTED,
            command_id=command.id,
            event_ids=(),
            aggregate_revision=None,
            error_code=error_code,
        )

    def _rejection_events(
        self, command: Command, result: CommandResult
    ) -> tuple[CommandResult, list[Event]]:
        """Persist authenticated rejection facts, never an aggregate mutation."""
        aggregate_type, aggregate_id = self._aggregate_address(command)
        if not aggregate_id:
            # Invalid/absent targets have no domain address; audit the request
            # against its project and retain the original target in the error.
            aggregate_type, aggregate_id = "project", command.project_id
        snapshot = self._snapshot(
            self.store.read_events(command.project_id), aggregate_type, aggregate_id
        )
        sequence = self.store.next_sequence(command.project_id)
        received = Event(
            id=f"{command.id}:received",
            project_id=command.project_id,
            sequence=sequence,
            type="command.received",
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            aggregate_revision=snapshot.revision,
            causation_id=command.id,
            correlation_id=command.correlation_id,
            payload={"command_type": command.type, "request_digest": command.digest()},
        )
        rejected = Event(
            id=f"{command.id}:rejected",
            project_id=command.project_id,
            sequence=sequence + 1,
            type="command.rejected",
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            aggregate_revision=snapshot.revision,
            causation_id=command.id,
            correlation_id=command.correlation_id,
            payload={
                "error": {
                    "code": result.error_code,
                    "message": f"Command rejected: {result.error_code}",
                    "retryable": False,
                    "severity": "medium",
                    "context": {
                        "command_id": command.id,
                        "target_id": command.target_id,
                        "expected_revision": command.expected_revision,
                        "current_revision": snapshot.revision if snapshot.exists else None,
                    },
                },
            },
        )
        return CommandResult(
            status=_REJECTED,
            command_id=command.id,
            event_ids=(received.id, rejected.id),
            aggregate_revision=snapshot.revision if snapshot.exists else None,
            error_code=result.error_code,
        ), [received, rejected]

    def _evaluate(
        self,
        command: Command,
        authenticated_actor_id: str,
    ) -> tuple[CommandResult, list[Event]]:
        """Evaluate one new Command against current Event facts."""
        if command.type not in self._SUPPORTED:
            return self._rejected(command, "UNSUPPORTED_COMMAND"), []

        all_events = self.store.read_events(command.project_id)
        aggregate_type, aggregate_id = self._aggregate_address(command)
        snapshot = self._snapshot(all_events, aggregate_type, aggregate_id)

        # Legacy handlers cannot mutate ownership of a Task whose accepted
        # creation explicitly selected Runtime/Lease enforcement.
        if command.type in {"task.claim", "task.release"} and any(
            event.type == "task.created" and event.aggregate_id == command.target_id
            and event.payload.get("execution_policy_version") for event in all_events
        ):
            return self._rejected(command, "EXECUTION_CONTEXT_REQUIRED"), []

        if command.type in {"project.create", "agent.register"}:
            if authenticated_actor_id != self._BOOTSTRAP_ACTOR:
                return self._rejected(command, "PERMISSION_DENIED"), []
        elif not self._agent_is_registered(
            all_events,
            command.project_id,
            authenticated_actor_id,
        ):
            return self._rejected(command, "PERMISSION_DENIED"), []

        if command.type == "project.create":
            if command.target_id is not None:
                return self._rejected(command, "INVALID_TARGET"), []
            if snapshot.exists:
                return self._rejected(command, "REVISION_CONFLICT"), []
            if command.expected_revision not in (None, 0):
                return self._rejected(command, "REVISION_CONFLICT"), []
            status = command.payload.get("status", "planning")
            if not isinstance(status, str) or status not in PROJECT_STATUSES:
                return self._rejected(command, "INVALID_PAYLOAD"), []
            return self._accepted_with_event(
                command,
                aggregate_type,
                aggregate_id,
                current_revision=0,
                event_type="project.created",
                payload={"status": status},
            )

        if command.type == "agent.register":
            if command.target_id is None:
                return self._rejected(command, "INVALID_TARGET"), []
            if not self._project_exists(all_events, command.project_id):
                return self._rejected(command, "INVALID_TARGET"), []
            from aetp.collaboration.policy import PolicyViolation
            from aetp.core.projection import Projection
            from aetp.governance.policy import validate_agent_identity
            try:
                validate_agent_identity(Projection.rebuild(all_events), command.project_id, command.target_id)
            except PolicyViolation as exc:
                return self._rejected(command, exc.code), []
            if snapshot.exists:
                return self._rejected(command, "REVISION_CONFLICT"), []
            if command.expected_revision not in (None, 0):
                return self._rejected(command, "REVISION_CONFLICT"), []
            model_id = command.payload.get("model_id")
            status = command.payload.get("status", "available")
            if (
                not isinstance(model_id, str)
                or not model_id.strip()
                or not isinstance(status, str)
                or status not in AGENT_STATUSES
            ):
                return self._rejected(command, "INVALID_PAYLOAD"), []
            return self._accepted_with_event(
                command,
                aggregate_type,
                aggregate_id,
                current_revision=0,
                event_type="agent.created",
                payload={"model_id": model_id, "status": status},
            )

        # Task creation is the one Task command whose aggregate is absent.
        # It still requires an existing, non-paused Project and a registered
        # Agent caller.
        if command.type == "task.create":
            if command.target_id is None:
                return self._rejected(command, "INVALID_TARGET"), []
            if not self._project_exists(all_events, command.project_id):
                return self._rejected(command, "INVALID_TARGET"), []
            project = self._snapshot(all_events, "project", command.project_id)
            if project.status == "paused":
                return self._rejected(command, "PROJECT_PAUSED"), []
            if snapshot.exists:
                return self._rejected(command, "REVISION_CONFLICT"), []
            if command.expected_revision not in (None, 0):
                return self._rejected(command, "REVISION_CONFLICT"), []
            return self._accepted_with_event(
                command,
                aggregate_type,
                aggregate_id,
                current_revision=0,
                event_type="task.created",
                payload={},
            )

        # The remaining commands operate on an existing Task in an existing
        # Project.
        if command.target_id is None or not snapshot.exists:
            return self._rejected(command, "INVALID_TARGET"), []
        if not self._project_exists(all_events, command.project_id):
            return self._rejected(command, "INVALID_TARGET"), []
        project = self._snapshot(all_events, "project", command.project_id)
        if project.status == "paused":
            return self._rejected(command, "PROJECT_PAUSED"), []
        # None means "absent" only for creation; existing aggregates always
        # require an explicit version precondition, including revision zero.
        if command.expected_revision != snapshot.revision:
            return self._rejected(command, "REVISION_CONFLICT"), []


        if command.type == "task.claim":
            if snapshot.status != "pending" or snapshot.owner_id is not None:
                return self._rejected(command, "TASK_NOT_ASSIGNABLE"), []
            return self._accepted_with_event(
                command,
                aggregate_type,
                aggregate_id,
                current_revision=snapshot.revision,
                event_type="task.claimed",
                payload={"actor_id": authenticated_actor_id, "status": "assigned"},
            )

        if command.type == "task.release":
            if snapshot.owner_id != authenticated_actor_id:
                return self._rejected(command, "PERMISSION_DENIED"), []
            return self._accepted_with_event(
                command,
                aggregate_type,
                aggregate_id,
                current_revision=snapshot.revision,
                event_type="task.requeued",
                payload={
                    "actor_id": authenticated_actor_id,
                    "reason": "release",
                    "status": "pending",
                },
            )

        return self._rejected(command, "UNSUPPORTED_COMMAND"), []

    def _accepted_with_event(
        self,
        command: Command,
        aggregate_type: str,
        aggregate_id: str,
        *,
        current_revision: int,
        event_type: str,
        payload: dict[str, Any],
    ) -> tuple[CommandResult, list[Event]]:
        if event_type not in {
            "project.created",
            "agent.created",
            "task.created",
            "task.claimed",
            "task.requeued",
        }:
            raise ModelValidationError(f"unsupported M0 event type: {event_type}")

        if command.type == "task.create":
            title = command.payload.get("title")
            if not isinstance(title, str) or not title.strip():
                return self._rejected(command, "INVALID_PAYLOAD"), []
            payload = {"title": title, "status": "pending"}
            new_revision = 0
            event_type = "task.created"
            aggregate_type = "task"
            aggregate_id = command.target_id or ""
        elif event_type.endswith("created"):
            new_revision = current_revision
        else:
            new_revision = current_revision + 1

        first_sequence = self.store.next_sequence(command.project_id)
        received = Event(
            id=f"{command.id}:received",
            project_id=command.project_id,
            sequence=first_sequence,
            type="command.received",
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            aggregate_revision=current_revision,
            causation_id=command.id,
            correlation_id=command.correlation_id,
            payload={
                "command_type": command.type,
                "request_digest": command.digest(),
            },
        )
        effect = Event(
            id=f"{command.id}:effect",
            project_id=command.project_id,
            sequence=first_sequence + 1,
            type=event_type,
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            aggregate_revision=new_revision,
            causation_id=command.id,
            correlation_id=command.correlation_id,
            payload=payload,
        )
        result = CommandResult(
            status=_ACCEPTED,
            command_id=command.id,
            event_ids=(received.id, effect.id),
            aggregate_revision=new_revision,
            error_code=None,
        )
        return result, [received, effect]

    @staticmethod
    def _aggregate_address(command: Command) -> tuple[str, str]:
        if command.type in INTEGRATION_COMMANDS:
            return INTEGRATION_COMMANDS[command.type], command.target_id or ""
        if command.type in QUALITY_COMMANDS:
            return QUALITY_COMMANDS[command.type], command.target_id or ""
        if command.type in ACCEPTANCE_COMMANDS:
            return ACCEPTANCE_COMMANDS[command.type], command.target_id or ""
        if command.type in PLANNING_COMMANDS:
            return PLANNING_COMMANDS[command.type], command.target_id or ""
        if command.type in GOVERNANCE_COMMANDS:
            return GOVERNANCE_COMMANDS[command.type], command.target_id or ""
        if command.type in DISCUSSION_COMMANDS:
            return DISCUSSION_COMMANDS[command.type], command.target_id or ""
        if command.type in EXECUTION_COMMANDS:
            return EXECUTION_COMMANDS[command.type], command.target_id or ""
        if command.type in COMMAND_AGGREGATES:
            return COMMAND_AGGREGATES[command.type], command.target_id or ""
        if command.type == "project.create":
            return "project", command.project_id
        if command.type == "agent.register":
            return "agent", command.target_id or ""
        return "task", command.target_id or ""

    @staticmethod
    def _project_exists(events: list[Event], project_id: str) -> bool:
        return CommandHandler._snapshot(events, "project", project_id).exists

    @staticmethod
    def _agent_is_registered(
        events: list[Event],
        project_id: str,
        agent_id: str,
    ) -> bool:
        snapshot = CommandHandler._snapshot(events, "agent", agent_id)
        if not snapshot.exists:
            return False
        # Agent IDs are project-scoped in the protocol even though the M0
        # model stores the scope on the event's project_id.
        return any(
            event.project_id == project_id
            and event.aggregate_type == "agent"
            and event.aggregate_id == agent_id
            and event.type == "agent.created"
            for event in events
        )

    @staticmethod
    def _snapshot(
        events: list[Event],
        aggregate_type: str,
        aggregate_id: str,
    ) -> _AggregateSnapshot:
        state: dict[str, Any] = {
            "exists": False,
            "revision": 0,
            "status": None,
            "title": None,
            "model_id": None,
            "owner_id": None,
        }
        for event in events:
            if (
                event.aggregate_type != aggregate_type
                or event.aggregate_id != aggregate_id
            ):
                continue
            if event.type in {"command.received", "command.rejected"}:
                continue
            state["exists"] = True
            state["revision"] = event.aggregate_revision
            payload = event.payload
            if "governance_schema" in payload or "planning_schema" in payload or "quality_schema" in payload or "integration_schema" in payload:
                payload = payload["record"]
                for field in ("status", "title", "owner_id", "model_id"):
                    if field in payload:
                        state[field] = payload[field]
            if event.type in {"project.created", "agent.created", "task.created"}:
                state["status"] = payload.get("status")
            elif event.type == "project.paused":
                state["status"] = "paused"
            elif event.type == "project.resumed":
                state["status"] = payload.get("status")
            if event.type == "agent.created":
                state["model_id"] = payload.get("model_id")
            if event.type == "task.created":
                state["title"] = payload.get("title")
                state["owner_id"] = None
            elif event.type in {"task.claimed", "task.assigned"}:
                state["status"] = payload.get("status", "assigned")
                state["owner_id"] = payload.get("actor_id") or payload.get("agent_id")
            elif event.type == "task.requeued":
                state["status"] = payload.get("status", "pending")
                state["owner_id"] = None
            elif event.type == "task.started":
                state["status"] = "in_progress"
            elif event.type == "task.blocked":
                state["status"] = "blocked"
            elif event.type == "task.completed":
                state["status"] = "completed"
            elif event.type == "task.failed":
                state["status"] = "failed"
            elif event.type == "task.cancelled":
                state["status"] = "cancelled"
        return _AggregateSnapshot(
            aggregate_type=aggregate_type,
            aggregate_id=aggregate_id,
            exists=bool(state["exists"]),
            revision=int(state["revision"]),
            status=state["status"],
            title=state["title"],
            model_id=state["model_id"],
            owner_id=state["owner_id"],
        )


__all__ = ["CommandHandler", "CommandResult"]


