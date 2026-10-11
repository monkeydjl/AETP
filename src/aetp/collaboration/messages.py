"""Ephemeral peer messages, deliberately outside the authoritative Event log."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Mapping
from dataclasses import dataclass, replace

from aetp.core.projection import Projection
from aetp.domain.models import ModelValidationError, VersionedModel, _non_empty_string
from aetp.storage.sqlite_store import SQLiteStore


MESSAGE_TYPES = frozenset({
    "question", "proposal", "claim", "challenge", "agreement", "disagreement",
    "evidence", "clarification", "request", "response", "notification",
})


class MessageError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def _ids(name: str, values: tuple[str, ...], *, required: bool = False) -> None:
    if not isinstance(values, tuple) or (required and not values):
        raise ModelValidationError(f"{name} must be {'a non-empty' if required else 'a'} tuple")
    for value in values:
        _non_empty_string(name, value)
    if len(set(values)) != len(values):
        raise ModelValidationError(f"{name} contains duplicate identifiers")


@dataclass(frozen=True, slots=True)
class Message(VersionedModel):
    id: str
    project_id: str
    sender_id: str
    recipients: tuple[str, ...]
    type: str
    content: str
    references: tuple[str, ...] = ()
    target_message: str | None = None
    untrusted_input: bool = True

    @classmethod
    def from_dict(cls, data: Mapping[str, object]) -> Message:
        if isinstance(data, Mapping):
            data = dict(data)
            for name in ("recipients", "references"):
                if isinstance(data.get(name), list):
                    data[name] = tuple(data[name])
        return super(Message, cls).from_dict(data)

    def __post_init__(self) -> None:
        for name in ("id", "project_id", "sender_id"):
            _non_empty_string(name, getattr(self, name))
        _ids("recipients", self.recipients, required=True)
        _ids("references", self.references)
        if self.type not in MESSAGE_TYPES:
            raise ModelValidationError("unsupported message type")
        if not isinstance(self.content, str) or not self.content.strip():
            raise ModelValidationError("message content must be non-empty text")
        try:
            size = len(self.content.encode("utf-8"))
        except UnicodeError as exc:
            raise ModelValidationError("message content must be valid UTF-8") from exc
        if size > 65536:
            raise ModelValidationError("message exceeds 65536 bytes")
        if self.target_message is not None and self.target_message not in self.references:
            raise ModelValidationError("reply target must be an explicit reference")
        if not isinstance(self.untrusted_input, bool):
            raise ModelValidationError("untrusted_input must be a boolean")


def participant(state: dict, actor_id: str) -> bool:
    """Equal membership check, without Role, Task ownership or Lease tests."""
    agent = state.get(f"agent:{actor_id}")
    return bool(agent and agent.get("status") not in {"disabled", "terminated", "left", "failed"})


class MessageBus:
    """Process-local conversation records; only explicit snapshots become evidence.

    Caller identity and input-exposure flags belong to the trusted in-process
    entry boundary. They are not a certification of an external Runtime.
    Unknown exposure defaults to untrusted, and references cannot clear it.
    """

    def __init__(self, store: SQLiteStore):
        if not isinstance(store, SQLiteStore):
            raise TypeError("store must be a SQLiteStore")
        self.store = store
        self._messages: dict[tuple[str, str], Message] = {}
        self._lock = threading.RLock()

    def _authorize(self, project_id: str, actor_id: str) -> dict:
        _non_empty_string("project_id", project_id)
        _non_empty_string("authenticated_actor_id", actor_id)
        state = Projection.rebuild(self.store.read_events(project_id))
        if f"project:{project_id}" not in state or not participant(state, actor_id):
            raise MessageError("PERMISSION_DENIED")
        return state

    def _visible(self, project_id: str, identifier: str, actor_id: str) -> Message:
        message = self._messages.get((project_id, identifier))
        if message is None:
            raise MessageError("INVALID_REFERENCE")
        if actor_id != message.sender_id and actor_id not in message.recipients:
            raise MessageError("REFERENCE_NOT_VISIBLE")
        return message

    def send(self, message: Message, *, authenticated_actor_id: str) -> Message:
        if not isinstance(message, Message):
            raise TypeError("message must be a Message")
        if message.sender_id != authenticated_actor_id:
            raise MessageError("ACTOR_MISMATCH")
        # Same lock order as snapshot consumption inside a Command transaction.
        # This SELECT and process-record mutation do not write Project State.
        with self.store._lock, self._lock:
            state = self._authorize(message.project_id, authenticated_actor_id)
            if any(not participant(state, recipient) for recipient in message.recipients):
                raise MessageError("INVALID_RECIPIENT")
            references = [self._visible(message.project_id, ref, authenticated_actor_id)
                          for ref in message.references]
            accepted = replace(message, untrusted_input=message.untrusted_input or any(
                ref.untrusted_input for ref in references))
            key = (message.project_id, message.id)
            existing = self._messages.get(key)
            if existing is not None and existing != accepted:
                raise MessageError("MESSAGE_ID_CONFLICT")
            self._messages[key] = accepted
            return accepted

    def inbox(self, project_id: str, *, authenticated_actor_id: str) -> tuple[Message, ...]:
        with self.store._lock, self._lock:
            self._authorize(project_id, authenticated_actor_id)
            return tuple(message for (project, _), message in self._messages.items()
                         if project == project_id and authenticated_actor_id in message.recipients)

    def snapshots(self, project_id: str, message_ids: tuple[str, ...], *,
                  authenticated_actor_id: str) -> list[dict]:
        _ids("message_ids", message_ids)
        with self.store._lock, self._lock:
            self._authorize(project_id, authenticated_actor_id)
            messages = [self._visible(project_id, identifier, authenticated_actor_id)
                        for identifier in message_ids]
            return [{"message": message.to_versioned_dict(), "content_digest": "sha256:" +
                     hashlib.sha256(message.to_versioned_json().encode("utf-8")).hexdigest()}
                    for message in messages]
