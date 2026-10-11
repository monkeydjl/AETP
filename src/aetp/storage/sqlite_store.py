"""SQLite persistence for durable AETP Commands, Events and idempotency records."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Optional

from aetp.core.projection import Projection
from aetp.domain.models import Command, Event, ModelValidationError


_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS commands (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    type TEXT NOT NULL,
    target_id TEXT,
    payload_json TEXT NOT NULL,
    expected_revision INTEGER,
    idempotency_key TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    CHECK (expected_revision IS NULL OR expected_revision >= 0)
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    type TEXT NOT NULL,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    aggregate_revision INTEGER NOT NULL,
    causation_id TEXT NOT NULL,
    correlation_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    UNIQUE (project_id, sequence),
    CHECK (sequence >= 0),
    CHECK (aggregate_revision >= 0)
);

CREATE TABLE IF NOT EXISTS idempotency (
    project_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    command_id TEXT NOT NULL,
    result_json TEXT,
    PRIMARY KEY (project_id, actor_id, idempotency_key),
    UNIQUE (project_id, actor_id, idempotency_key, request_digest),
    FOREIGN KEY (command_id) REFERENCES commands(id)
);

-- Entry security diagnostics are NOT protocol Commands/Events.  Claimed
-- identifiers stay labelled as claims and never acquire authoritative keys.
CREATE TABLE IF NOT EXISTS security_audit (
    audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
    command_id TEXT NOT NULL,
    claimed_project_id TEXT NOT NULL,
    claimed_actor_id TEXT NOT NULL,
    authenticated_actor_id TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    error_code TEXT NOT NULL,
    observed_at TEXT NOT NULL
);

-- Derived cache only.  This table is never used to authorize a Command.
CREATE TABLE IF NOT EXISTS projections (
    project_id TEXT PRIMARY KEY,
    state_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projection_meta (
    project_id TEXT PRIMARY KEY,
    last_sequence INTEGER NOT NULL DEFAULT 0,
    projection_digest TEXT,
    CHECK (last_sequence >= 0)
);
"""


class SQLiteStore:
    """Small append-only store used by the M0 model and later kernel layers."""

    def __init__(self, connection: sqlite3.Connection):
        self._connection: Optional[sqlite3.Connection] = connection
        self._lock = threading.RLock()
        self._transaction_depth = 0

    @classmethod
    def open(cls, path: str) -> "SQLiteStore":
        if not isinstance(path, (str, os.PathLike)):
            raise TypeError("path must be a string or path-like value")
        if str(path) != ":memory:":
            Path(path).expanduser().parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            str(path),
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        connection.executescript(_SCHEMA)
        return cls(connection)

    def _ensure_open(self) -> sqlite3.Connection:
        if self._connection is None:
            raise RuntimeError("SQLiteStore is closed")
        return self._connection

    @property
    def database_path(self) -> str | None:
        """Trusted host address; an in-memory store cannot host external effects."""
        with self._lock:
            for _, name, path in self._ensure_open().execute("PRAGMA database_list"):
                if name == "main":
                    return path or None
        return None

    @property
    def in_transaction(self) -> bool:
        """Let an execution host reject effects inside an existing transaction."""
        with self._lock:
            return self._ensure_open().in_transaction

    @contextmanager
    def transaction(self) -> Iterator["SQLiteStore"]:
        """Serialize writers; every nested unit has its own rollback boundary."""
        with self._lock:
            connection = self._ensure_open()
            outermost = self._transaction_depth == 0
            savepoint = f"aetp_nested_{self._transaction_depth}"
            if outermost:
                connection.execute("BEGIN IMMEDIATE")
            else:
                connection.execute(f"SAVEPOINT {savepoint}")
            self._transaction_depth += 1
            try:
                yield self
                if outermost:
                    connection.commit()
                else:
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            except BaseException:
                if outermost:
                    connection.rollback()
                else:
                    connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                    connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                raise
            finally:
                self._transaction_depth -= 1

    def append_command(
        self,
        command: Command,
        *,
        idempotency_actor_id: str | None = None,
    ) -> None:
        if not isinstance(command, Command):
            raise TypeError("command must be a Command")
        if idempotency_actor_id is None:
            idempotency_actor_id = command.actor_id
        if (
            not isinstance(idempotency_actor_id, str)
            or not idempotency_actor_id.strip()
            or idempotency_actor_id != idempotency_actor_id.strip()
        ):
            raise ValueError("idempotency_actor_id must be a non-empty string")
        if self._transaction_depth == 0:
            with self.transaction():
                self.append_command(
                    command,
                    idempotency_actor_id=idempotency_actor_id,
                )
            return
        connection = self._ensure_open()
        try:
            connection.execute(
                """
                INSERT INTO commands (
                    id, project_id, actor_id, type, target_id, payload_json,
                    expected_revision, idempotency_key, correlation_id, request_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    command.id,
                    command.project_id,
                    command.actor_id,
                    command.type,
                    command.target_id,
                    json.dumps(command.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                    command.expected_revision,
                    command.idempotency_key,
                    command.correlation_id,
                    command.digest(),
                ),
            )
            connection.execute(
                """
                INSERT INTO idempotency (
                    project_id, actor_id, idempotency_key, request_digest, command_id
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    command.project_id,
                    idempotency_actor_id,
                    command.idempotency_key,
                    command.digest(),
                    command.id,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"command conflicts with existing durable record: {command.id}") from exc

    def record_security_rejection(
        self,
        command: Command,
        *,
        authenticated_actor_id: str,
        error_code: str,
    ) -> None:
        """Keep trusted-entry diagnostics separate from project fact history."""
        if not isinstance(command, Command):
            raise TypeError("command must be a Command")
        for name, value in (("authenticated_actor_id", authenticated_actor_id),
                            ("error_code", error_code)):
            if not isinstance(value, str) or not value.strip() or value != value.strip():
                raise ValueError(f"{name} must be a non-empty string")
        with self.transaction():
            self._ensure_open().execute(
                """
                INSERT INTO security_audit (
                    command_id, claimed_project_id, claimed_actor_id,
                    authenticated_actor_id, request_digest, error_code, observed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (command.id, command.project_id, command.actor_id,
                 authenticated_actor_id, command.digest(), error_code,
                 datetime.now(timezone.utc).isoformat()),
            )

    def read_security_audit(self, *, authenticated_actor_id: str) -> list[dict[str, Any]]:
        """Read diagnostics for a trusted actor; no untrusted payload is stored."""
        if not isinstance(authenticated_actor_id, str) or not authenticated_actor_id.strip():
            raise ValueError("authenticated_actor_id must be a non-empty string")
        columns = ("audit_id", "command_id", "claimed_project_id", "claimed_actor_id",
                   "authenticated_actor_id", "request_digest", "error_code", "observed_at")
        with self._lock:
            rows = self._ensure_open().execute(
                "SELECT audit_id, command_id, claimed_project_id, claimed_actor_id, "
                "authenticated_actor_id, request_digest, error_code, observed_at "
                "FROM security_audit WHERE authenticated_actor_id = ? ORDER BY audit_id",
                (authenticated_actor_id,),
            ).fetchall()
        return [dict(zip(columns, row)) for row in rows]

    def next_sequence(self, project_id: str) -> int:
        """Inspect the durable next number; only append assigns final sequence.

        This trusted-kernel helper does not reserve a number.  The caller must
        hold the append/Command transaction, never pass it to an Agent Runtime.
        """
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        with self._lock:
            if self._transaction_depth == 0:
                raise RuntimeError("next_sequence must be called inside a transaction")
            row = self._ensure_open().execute(
                "SELECT COALESCE(MAX(sequence), 0) + 1 FROM events WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            return int(row[0])

    def append_events(self, events: list[Event]) -> None:
        """Sequence and commit one trusted Event batch, then derive its cache.

        Zero is an internal unnumbered draft, not a persisted sequence.  Positive
        values from the current CommandHandler are only checked expectations;
        the Sequencer still assigns each final number under BEGIN IMMEDIATE.
        Agent input enters through CommandHandler, not this storage primitive.
        """
        if not isinstance(events, list):
            raise TypeError("events must be a list")
        if not events:
            return
        if any(not isinstance(event, Event) for event in events):
            raise TypeError("events must contain Event objects")
        project_ids = {event.project_id for event in events}
        if len(project_ids) != 1:
            raise ModelValidationError("one event batch must belong to one project")
        project_id = events[0].project_id
        try:
            # Always isolate this batch, even when its caller catches a failure
            # inside an outer transaction and continues with unrelated work.
            with self.transaction():
                first = self.next_sequence(project_id)
                numbered = []
                for index, event in enumerate(events):
                    sequence = first + index
                    if event.sequence not in (0, sequence):
                        raise ModelValidationError("Event sequence does not match the Sequencer cursor")
                    numbered.append(replace(event, sequence=sequence))
                projection = self._load_projection(project_id)
                connection = self._ensure_open()
                connection.executemany(
                    """
                    INSERT INTO events (
                        id, project_id, sequence, type, aggregate_type, aggregate_id,
                        aggregate_revision, causation_id, correlation_id, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            event.id, event.project_id, event.sequence, event.type,
                            event.aggregate_type, event.aggregate_id,
                            event.aggregate_revision, event.causation_id,
                            event.correlation_id,
                            json.dumps(event.payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                        )
                        for event in numbered
                    ],
                )
                # Never persist State first and fill in its Event history later.
                for event in numbered:
                    projection.apply(event)
                self._write_projection(projection)
        except sqlite3.IntegrityError as exc:
            raise ValueError("Event batch or derived Projection could not be committed") from exc

    @staticmethod
    def _projection_digest(project_id: str, state: dict[str, Any], last_sequence: int) -> str:
        content = json.dumps(
            {"project_id": project_id, "last_sequence": last_sequence, "state": state},
            sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        )
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _load_projection(self, project_id: str) -> Projection:
        """Read a cache snapshot or purely rebuild; the caller holds the lock."""
        # Cache, cursor and Event head are read in ONE SQLite statement.  A
        # concurrent connection cannot make a stale cache appear up-to-date
        # between separate reads of its metadata and the durable Event head.
        row = self._ensure_open().execute(
            """
            SELECT p.state_json, m.last_sequence, m.projection_digest,
                   (SELECT COALESCE(MAX(sequence), 0) FROM events WHERE project_id = requested.project_id)
            FROM (SELECT ? AS project_id) AS requested
            LEFT JOIN projections AS p ON p.project_id = requested.project_id
            LEFT JOIN projection_meta AS m ON m.project_id = requested.project_id
            """,
            (project_id,),
        ).fetchone()
        if row[0] is not None and row[1] == row[3]:
            try:
                state = json.loads(row[0])
                if isinstance(state, dict) and row[2] == self._projection_digest(project_id, state, row[1]):
                    return Projection._from_cache(project_id, state, row[1])
            except (TypeError, ValueError):
                pass
        # Missing, corrupt or lagging cache never becomes an alternative fact
        # source.  Read calls do not repair tables; the next append can replace
        # the cache as part of its transaction after consuming Event history.
        projection = Projection(project_id)
        for event in self.read_events(project_id):
            projection.apply(event)
        return projection

    def _write_projection(self, projection: Projection) -> None:
        """Persist only reducer output after Event insertion, in its transaction."""
        if self._transaction_depth == 0:
            raise RuntimeError("Projection persistence requires an Event transaction")
        state = projection.state
        project_id = projection.project_id
        last_sequence = projection.last_sequence
        connection = self._ensure_open()
        connection.execute(
            """
            INSERT INTO projections (project_id, state_json) VALUES (?, ?)
            ON CONFLICT(project_id) DO UPDATE SET state_json = excluded.state_json
            """,
            (project_id, json.dumps(state, sort_keys=True, separators=(",", ":"), ensure_ascii=False)),
        )
        connection.execute(
            """
            INSERT INTO projection_meta (project_id, last_sequence, projection_digest)
            VALUES (?, ?, ?)
            ON CONFLICT(project_id) DO UPDATE SET
                last_sequence = excluded.last_sequence,
                projection_digest = excluded.projection_digest
            """,
            (project_id, last_sequence, self._projection_digest(project_id, state, last_sequence)),
        )

    def read_projection(self, project_id: str) -> dict[str, dict[str, Any]]:
        """Return detached derived State without SQL writes or Command dispatch."""
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        with self._lock:
            return self._load_projection(project_id).state

    def read_events(self, project_id: str, after_sequence: int = 0) -> list[Event]:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be a non-empty string")
        if isinstance(after_sequence, bool) or not isinstance(after_sequence, int) or after_sequence < 0:
            raise ValueError("after_sequence must be a non-negative integer")
        connection = self._ensure_open()
        rows = connection.execute(
            """
            SELECT id, project_id, sequence, type, aggregate_type, aggregate_id,
                   aggregate_revision, causation_id, correlation_id, payload_json
            FROM events
            WHERE project_id = ? AND sequence > ?
            ORDER BY sequence ASC
            """,
            (project_id, after_sequence),
        ).fetchall()
        result: list[Event] = []
        for row in rows:
            result.append(
                Event(
                    id=row[0],
                    project_id=row[1],
                    sequence=row[2],
                    type=row[3],
                    aggregate_type=row[4],
                    aggregate_id=row[5],
                    aggregate_revision=row[6],
                    causation_id=row[7],
                    correlation_id=row[8],
                    payload=json.loads(row[9]),
                )
            )
        return result

    def read_idempotency(self, scope: tuple[str, str, str]) -> Optional[dict[str, Any]]:
        if not isinstance(scope, tuple) or len(scope) != 3:
            raise ValueError("scope must be (project_id, actor_id, idempotency_key)")
        project_id, actor_id, idempotency_key = scope
        if any(not isinstance(value, str) or not value.strip() for value in scope):
            raise ValueError("idempotency scope values must be non-empty strings")
        connection = self._ensure_open()
        row = connection.execute(
            """
            SELECT project_id, actor_id, idempotency_key, request_digest,
                   command_id, result_json
            FROM idempotency
            WHERE project_id = ? AND actor_id = ? AND idempotency_key = ?
            """,
            (project_id, actor_id, idempotency_key),
        ).fetchone()
        if row is None:
            return None
        result: dict[str, Any] = {
            "project_id": row[0],
            "actor_id": row[1],
            "idempotency_key": row[2],
            "request_digest": row[3],
            "command_id": row[4],
        }
        if row[5] is not None:
            result["result"] = json.loads(row[5])
        return result

    def record_idempotency_result(
        self, scope: tuple[str, str, str], result: dict[str, Any]
    ) -> None:
        if not isinstance(result, dict):
            raise TypeError("result must be an object")
        if self._transaction_depth == 0:
            with self.transaction():
                self.record_idempotency_result(scope, result)
            return
        project_id, actor_id, idempotency_key = scope
        connection = self._ensure_open()
        connection.execute(
            """
            UPDATE idempotency SET result_json = ?
            WHERE project_id = ? AND actor_id = ? AND idempotency_key = ?
            """,
            (
                json.dumps(result, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
                project_id,
                actor_id,
                idempotency_key,
            ),
        )

    def close(self) -> None:
        with self._lock:
            if self._connection is None:
                return
            if self._transaction_depth:
                raise RuntimeError("cannot close SQLiteStore during an active transaction")
            connection = self._connection
            self._connection = None
            connection.close()

    def __enter__(self) -> "SQLiteStore":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


__all__ = ["SQLiteStore"]
