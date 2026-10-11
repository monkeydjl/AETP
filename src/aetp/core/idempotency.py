"""Read-only access to durable M0 idempotency results.

A retry retains the complete immutable Command, including its identity and
correlation context. The canonical format deliberately matches the digest
already stored by M0-02; this extraction does not migrate existing records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from aetp.domain.models import Command
from aetp.storage.sqlite_store import SQLiteStore

if TYPE_CHECKING:
    from aetp.core.commands import CommandResult


class IdempotencyConflict(ValueError):
    """The scoped key is already bound to a different immutable Command."""


def canonical_digest(command: Command) -> str:
    """Hash validated Command content using the existing canonical JSON format."""
    if not isinstance(command, Command):
        raise TypeError("command must be a Command")
    return command.digest()


class IdempotencyResult:
    """Look up an original result without reserving keys or modifying storage.

    The actor in ``scope`` must come from the trusted entry, not the payload.
    The Handler performs this lookup inside its write transaction, after actor
    binding and before append. A standalone read cannot authorize a write.
    Missing/corrupt results fail closed; recovery is a separate work item.
    """

    def __init__(self, store: SQLiteStore):
        self.store = store

    def lookup(
        self, scope: tuple[str, str, str], digest: str
    ) -> CommandResult | None:
        if not isinstance(digest, str):
            raise TypeError("digest must be a string")
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise ValueError("digest must be a canonical lowercase SHA-256 value")
        record = self.store.read_idempotency(scope)
        if record is None:
            return None
        if record["request_digest"] != digest:
            raise IdempotencyConflict("scoped key is bound to different Command content")
        stored_result = record.get("result")
        if stored_result is None:
            raise RuntimeError(
                "idempotency record has no durable result; recovery is required"
            )

        # Keep the result's established public type without a module import cycle.
        from aetp.core.commands import CommandResult

        result = CommandResult.from_dict(stored_result)
        if result.command_id != record["command_id"]:
            raise RuntimeError(
                "durable result has a foreign command_id; recovery is required"
            )
        return result


__all__ = ["canonical_digest", "IdempotencyConflict", "IdempotencyResult"]
