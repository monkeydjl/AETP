"""Immutable, versioned data contracts for the AETP M0 core kernel."""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass, fields
from typing import Any, ClassVar, Mapping, Optional

from aetp.collaboration.contracts import AGGREGATES, COMMAND_AGGREGATES, DOMAIN_EVENTS
from aetp.runtime.contracts import (
    AGGREGATES as EXECUTION_AGGREGATES, COMMAND_AGGREGATES as EXECUTION_COMMANDS,
    DOMAIN_EVENTS as EXECUTION_EVENTS,
)
from aetp.meetings.contracts import (
    AGGREGATES as DISCUSSION_AGGREGATES, COMMAND_AGGREGATES as DISCUSSION_COMMANDS,
    DOMAIN_EVENTS as DISCUSSION_EVENTS,
)
from aetp.governance.contracts import (
    AGGREGATES as GOVERNANCE_AGGREGATES, COMMAND_AGGREGATES as GOVERNANCE_COMMANDS,
    DOMAIN_EVENTS as GOVERNANCE_EVENTS,
)
from aetp.planning.contracts import (
    AGGREGATES as PLANNING_AGGREGATES, COMMAND_AGGREGATES as PLANNING_COMMANDS,
    DOMAIN_EVENTS as PLANNING_EVENTS,
)
from aetp.acceptance.contracts import COMMAND_AGGREGATES as ACCEPTANCE_COMMANDS, DOMAIN_EVENTS as ACCEPTANCE_EVENTS
from aetp.quality.contracts import COMMAND_AGGREGATES as QUALITY_COMMANDS, DOMAIN_EVENTS as QUALITY_EVENTS
from aetp.integration.contracts import COMMAND_AGGREGATES as INTEGRATION_COMMANDS, DOMAIN_EVENTS as INTEGRATION_EVENTS
from aetp.bootstrap.contracts import (
    AGGREGATES as BOOTSTRAP_AGGREGATES, COMMAND_AGGREGATES as BOOTSTRAP_COMMANDS,
    DOMAIN_EVENTS as BOOTSTRAP_EVENTS,
)


SCHEMA_VERSION = "0.1"


class ModelValidationError(ValueError):
    """Raised when a core model does not satisfy its wire contract."""


def _non_empty_string(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ModelValidationError(f"{name} must be a non-empty string")
    if value != value.strip():
        raise ModelValidationError(f"{name} must not contain surrounding whitespace")
    return value


def _non_negative_int(name: str, value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ModelValidationError(f"{name} must be a non-negative integer")
    return value


def _optional_non_negative_int(name: str, value: Any) -> Optional[int]:
    if value is None:
        return None
    return _non_negative_int(name, value)


def _optional_non_empty_string(name: str, value: Any) -> Optional[str]:
    if value is None:
        return None
    return _non_empty_string(name, value)


class _FrozenDict(dict):
    """A JSON-compatible dict that rejects every mutating operation."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("payload mappings are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    clear = _immutable
    pop = _immutable
    popitem = _immutable
    setdefault = _immutable
    update = _immutable
    __ior__ = _immutable

    def __deepcopy__(self, memo: dict[int, Any]) -> dict[Any, Any]:
        result = {
            copy.deepcopy(key, memo): copy.deepcopy(value, memo)
            for key, value in self.items()
        }
        memo[id(self)] = result
        return result


class _FrozenList(list):
    """A JSON-compatible list that rejects every mutating operation."""

    def _immutable(self, *args: Any, **kwargs: Any) -> None:
        raise TypeError("payload sequences are immutable")

    __setitem__ = _immutable
    __delitem__ = _immutable
    __iadd__ = _immutable
    __imul__ = _immutable
    append = _immutable
    clear = _immutable
    extend = _immutable
    insert = _immutable
    pop = _immutable
    remove = _immutable
    reverse = _immutable
    sort = _immutable

    def __deepcopy__(self, memo: dict[int, Any]) -> list[Any]:
        result = [copy.deepcopy(value, memo) for value in self]
        memo[id(self)] = result
        return result


def _freeze_json_value(value: Any) -> Any:
    if isinstance(value, dict):
        return _FrozenDict(
            {key: _freeze_json_value(nested) for key, nested in value.items()}
        )
    if isinstance(value, (list, tuple)):
        return _FrozenList(_freeze_json_value(nested) for nested in value)
    return value


def _enum_string(name: str, value: Any, allowed: frozenset[str]) -> str:
    value = _non_empty_string(name, value)
    if value not in allowed:
        raise ModelValidationError(f"unsupported {name}: {value!r}")
    return value


def _json_value(value: Any) -> Any:
    """Return a detached, deeply immutable JSON-compatible value."""
    try:
        detached = copy.deepcopy(value)
        json.dumps(detached, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise ModelValidationError("payload must contain only JSON-compatible values") from exc
    return _freeze_json_value(detached)


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise ModelValidationError("model contains a non-JSON value") from exc


PROJECT_STATUSES = frozenset(
    {"planning", "active", "paused", "completed", "failed", "cancelled", "archived"}
)
AGENT_STATUSES = frozenset(
    {
        "offline",
        "available",
        "reserved",
        "working",
        "waiting",
        "blocked",
        "recovering",
        "paused",
        "disabled",
        "failed",
        "terminated",
        "active",
        "idle",
        "invited",
        "left",
    }
)
TASK_STATUSES = frozenset(
    {
        "pending",
        "assigned",
        "in_progress",
        "ready_for_review",
        "in_review",
        "verified",
        "ready_for_integration",
        "integrating",
        "integrated",
        "system_verified",
        "completed",
        "blocked",
        "failed",
        "rejected",
        "cancelled",
    }
)
COMMAND_TYPES = frozenset(
    {
        "project.create",
        "project.pause",
        "project.resume",
        "agent.register",
        "agent.join",
        "agent.leave",
        "task.create",
        "task.assign",
        "task.claim",
        "task.release",
        "task.start",
        "task.block",
        "task.complete",
        "task.fail",
        "task.cancel",
        "task.requeue",
    }
).union(COMMAND_AGGREGATES, EXECUTION_COMMANDS, DISCUSSION_COMMANDS, GOVERNANCE_COMMANDS, PLANNING_COMMANDS, ACCEPTANCE_COMMANDS, QUALITY_COMMANDS, INTEGRATION_COMMANDS, BOOTSTRAP_COMMANDS)
EVENT_TYPES = frozenset(
    {
        "project.created",
        "project.paused",
        "project.resumed",
        "agent.created",
        "agent.joined",
        "agent.left",
        "agent.failed",
        "agent.offline",
        "task.created",
        "task.assigned",
        "task.claimed",
        "task.started",
        "task.blocked",
        "task.completed",
        "task.failed",
        "task.cancelled",
        "task.overdue",
        "task.requeued",
        "command.received",
        "command.rejected",
    }
).union(DOMAIN_EVENTS, EXECUTION_EVENTS, DISCUSSION_EVENTS, GOVERNANCE_EVENTS, PLANNING_EVENTS, ACCEPTANCE_EVENTS, QUALITY_EVENTS, INTEGRATION_EVENTS, BOOTSTRAP_EVENTS)
AGGREGATE_TYPES = frozenset({"project", "agent", "task"}).union(
    AGGREGATES, EXECUTION_AGGREGATES, DISCUSSION_AGGREGATES, GOVERNANCE_AGGREGATES, PLANNING_AGGREGATES, BOOTSTRAP_AGGREGATES)


class VersionedModel:
    """Shared stable serialization and version parsing for all M0 models."""

    schema_version: ClassVar[str] = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {field.name: copy.deepcopy(getattr(self, field.name)) for field in fields(self)}

    def to_versioned_dict(self) -> dict[str, Any]:
        result = self.to_dict()
        result["schema_version"] = self.schema_version
        return result

    def to_json(self) -> str:
        return _canonical_json(self.to_dict())

    def to_versioned_json(self) -> str:
        return _canonical_json(self.to_versioned_dict())

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "VersionedModel":
        if not isinstance(data, Mapping):
            raise ModelValidationError("model data must be an object")
        values = dict(data)
        version = values.pop("schema_version", cls.schema_version)
        if version != cls.schema_version:
            raise ModelValidationError(
                f"unsupported {cls.__name__} schema_version: {version!r}"
            )
        allowed = {field.name for field in fields(cls)}
        unexpected = set(values) - allowed
        if unexpected:
            raise ModelValidationError(
                f"unexpected {cls.__name__} fields: {sorted(unexpected)!r}"
            )
        try:
            return cls(**values)
        except TypeError as exc:
            raise ModelValidationError(f"invalid {cls.__name__} fields") from exc


@dataclass(frozen=True, slots=True)
class Project(VersionedModel):
    id: str
    revision: int
    status: str

    def __post_init__(self) -> None:
        _non_empty_string("id", self.id)
        _non_negative_int("revision", self.revision)
        _enum_string("status", self.status, PROJECT_STATUSES)


@dataclass(frozen=True, slots=True)
class Agent(VersionedModel):
    id: str
    project_id: str
    model_id: str
    status: str

    def __post_init__(self) -> None:
        _non_empty_string("id", self.id)
        _non_empty_string("project_id", self.project_id)
        _non_empty_string("model_id", self.model_id)
        _enum_string("status", self.status, AGENT_STATUSES)


@dataclass(frozen=True, slots=True)
class Task(VersionedModel):
    id: str
    project_id: str
    title: str
    status: str
    revision: int

    def __post_init__(self) -> None:
        _non_empty_string("id", self.id)
        _non_empty_string("project_id", self.project_id)
        _non_empty_string("title", self.title)
        _enum_string("status", self.status, TASK_STATUSES)
        _non_negative_int("revision", self.revision)


@dataclass(frozen=True, slots=True)
class Command(VersionedModel):
    id: str
    project_id: str
    actor_id: str
    type: str
    target_id: Optional[str]
    payload: dict[str, Any]
    expected_revision: Optional[int]
    idempotency_key: str
    correlation_id: str

    def __post_init__(self) -> None:
        _non_empty_string("id", self.id)
        _non_empty_string("project_id", self.project_id)
        _non_empty_string("actor_id", self.actor_id)
        _enum_string("type", self.type, COMMAND_TYPES)
        _optional_non_empty_string("target_id", self.target_id)
        if not isinstance(self.payload, dict):
            raise ModelValidationError("payload must be an object")
        object.__setattr__(self, "payload", _json_value(self.payload))
        _optional_non_negative_int("expected_revision", self.expected_revision)
        _non_empty_string("idempotency_key", self.idempotency_key)
        _non_empty_string("correlation_id", self.correlation_id)

    def digest(self) -> str:
        return hashlib.sha256(self.to_json().encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class Event(VersionedModel):
    id: str
    project_id: str
    sequence: int
    type: str
    aggregate_type: str
    aggregate_id: str
    aggregate_revision: int
    causation_id: str
    correlation_id: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        _non_empty_string("id", self.id)
        _non_empty_string("project_id", self.project_id)
        _non_negative_int("sequence", self.sequence)
        _enum_string("type", self.type, EVENT_TYPES)
        _enum_string("aggregate_type", self.aggregate_type, AGGREGATE_TYPES)
        _non_empty_string("aggregate_id", self.aggregate_id)
        _non_negative_int("aggregate_revision", self.aggregate_revision)
        _non_empty_string("causation_id", self.causation_id)
        _non_empty_string("correlation_id", self.correlation_id)
        if not isinstance(self.payload, dict):
            raise ModelValidationError("payload must be an object")
        object.__setattr__(self, "payload", _json_value(self.payload))


__all__ = [
    "AGENT_STATUSES",
    "AGGREGATE_TYPES",
    "COMMAND_TYPES",
    "EVENT_TYPES",
    "ModelValidationError",
    "Project",
    "Agent",
    "Task",
    "Command",
    "Event",
    "SCHEMA_VERSION",
]
