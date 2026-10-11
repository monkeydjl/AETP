"""M0 simulation and read-only recovery, deliberately without a dispatcher.

A simulation observation is not a durable Command acknowledgement. Recovery
never executes a simulation, model, shell, tool, notification or Runtime.start.
It opens existing facts read-only and never creates/repairs caches or results.
"""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from aetp.core.commands import CommandResult
from aetp.core.projection import Projection
from aetp.domain.models import Command, ModelValidationError
from aetp.storage.sqlite_store import SQLiteStore


@dataclass(frozen=True, slots=True)
class SimulationResult(CommandResult):
    """Non-authoritative diagnostic, never a protocol ACK or persisted result.

    ``accepted`` means only that an in-memory simulation ran. The source marker
    survives diagnostic serialization; only CommandHandler may accept durable
    work, create Events and store the ordinary CommandResult in idempotency.
    """

    source: str = field(default="simulation-only", init=False)

    def to_dict(self) -> dict[str, Any]:
        return {**CommandResult.to_dict(self), "source": self.source}


class SimulatedRuntime:
    """Deterministic, effect-free simulator; its counter is diagnostic only."""

    def __init__(self) -> None:
        self._invocation_count = 0

    @property
    def invocation_count(self) -> int:
        return self._invocation_count

    def execute(self, command: Command) -> CommandResult:
        if not isinstance(command, Command):
            raise TypeError("command must be a Command")
        self._invocation_count += 1
        return SimulationResult(
            status="accepted", command_id=command.id, event_ids=(),
            aggregate_revision=None, error_code=None,
        )


_COMMAND_COLUMNS = (
    "id, project_id, actor_id, type, target_id, payload_json, "
    "expected_revision, idempotency_key, correlation_id, request_digest"
)
_EVENT_COLUMNS = (
    "id, project_id, sequence, type, aggregate_type, aggregate_id, "
    "aggregate_revision, causation_id, correlation_id, payload_json"
)


class RuntimeRecovery:
    """A read-only M0 view, with no private authoritative queue or State.

    Each call reloads durable facts. ``reconcile_pending`` only reports Command
    IDs that need investigation; it cannot authorize, retry or dispatch them.
    This is not external Action/UNKNOWN reconciliation or full Orchestrator
    recovery (Lease/Binding/Approval and operational pause remain later scope).
    """

    def __init__(self, store: SQLiteStore):
        self._store = store
        self._runtime = SimulatedRuntime()

    @classmethod
    def open(cls, store_path: str) -> "RuntimeRecovery":
        """Open an existing facts database, never the schema-initializing path."""
        if not isinstance(store_path, (str, os.PathLike)):
            raise TypeError("store_path must be a string or path-like value")
        value = os.fspath(store_path)
        if not isinstance(value, str):
            raise TypeError("store_path must resolve to a string")
        if not value.strip() or value == ":memory:":
            raise ValueError("recovery requires an existing persisted database")
        # as_uri quotes #/%/? and Unicode path characters before appending the
        # mode flag; caller-controlled filenames cannot supply SQLite options.
        uri = Path(value).resolve().as_uri() + "?mode=ro"
        connection = sqlite3.connect(
            uri, uri=True, timeout=30.0, isolation_level=None, check_same_thread=False,
        )
        try:
            # Only facts are required. Disposable projection/result tables may
            # be absent; do not initialize, migrate or validate them as truth.
            connection.execute(f"SELECT {_COMMAND_COLUMNS} FROM commands LIMIT 0")
            connection.execute(f"SELECT {_EVENT_COLUMNS} FROM events LIMIT 0")
            return cls(SQLiteStore(connection))
        except BaseException:
            connection.close()
            raise

    @property
    def runtime_invocation_count(self) -> int:
        """Actual simulator counter, not a hard-coded assertion of Replay purity."""
        return self._runtime.invocation_count

    @staticmethod
    def _validate_project_id(project_id: str) -> None:
        if (
            not isinstance(project_id, str) or not project_id.strip()
            or project_id != project_id.strip()
        ):
            raise ValueError("project_id must be a non-empty string")

    def rebuild_project(self, project_id: str) -> dict[str, dict[str, Any]]:
        self._validate_project_id(project_id)
        with self._store._lock:
            # One SELECT is a consistent snapshot. Never consult read_projection,
            # whose append-optimization cache is intentionally disposable here.
            events = self._store.read_events(project_id)
        return Projection.rebuild(events)

    def reconcile_pending(self, project_id: str) -> list[str]:
        """Report receipt-only Command IDs from one read snapshot, without dispatch or writes.

        The synchronous M0 handler normally commits receipt and terminal facts
        atomically. Receipt-only histories therefore need investigation, not
        automatic execution; missing result indexes alone do NOT mean pending.
        """
        self._validate_project_id(project_id)
        with self._store._lock:
            connection = self._store._ensure_open()
            # A deferred READ transaction is necessary for the two SELECTs to
            # see the same history. SQLiteStore.transaction uses BEGIN IMMEDIATE
            # for writers and must never be used on the recovery connection.
            connection.execute("BEGIN")
            try:
                events = self._store.read_events(project_id)
                commands = self._read_commands(project_id)
            finally:
                connection.rollback()  # Ends the read snapshot; no writes exist.
        return Projection.pending_command_ids(events, commands)

    def _read_commands(self, project_id: str) -> list[Command]:
        rows = self._store._ensure_open().execute(
            f"SELECT {_COMMAND_COLUMNS} FROM commands WHERE project_id = ?",
            (project_id,),
        ).fetchall()
        commands = []
        for row in rows:
            command = Command(
                id=row[0], project_id=row[1], actor_id=row[2], type=row[3],
                target_id=row[4], payload=json.loads(row[5]), expected_revision=row[6],
                idempotency_key=row[7], correlation_id=row[8],
            )
            if row[9] != command.digest():
                raise ModelValidationError("persisted Command digest does not match its content")
            commands.append(command)
        return commands

    def close(self) -> None:
        self._store.close()


__all__ = ["RuntimeRecovery", "SimulatedRuntime", "SimulationResult"]
