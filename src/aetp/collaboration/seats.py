"""Injected agent seats: real decision functions occupying equal peer positions.

The M3-02 fixture shows the delivery chain works, but both sides of its
conversation are hard-coded strings. A seat closes that gap: it is an
adapter object that, given only its own inbox and its own view of the
project, decides what to say next. The bus, the discussion and the delivery
chain then operate on content the system never supplied.

Design constraints, all enforced below or by the existing bus:

* A seat speaks only as its own ``agent_id``; the bus rejects any spoofing.
* Seats are equal. A seat gets no Role, no Task ownership, no Lease and no
  privileged inbox: whatever one seat may ask, the other may ask too.
* The system never supplies message content. A seat returns a decision and
  the seat fills in the envelope; there is no template to copy from.
* Seats are deterministic given the same inputs so runs stay replayable in
  the test suite. Determinism is a property of the injected function, not
  something the protocol can assume about a real model.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from aetp.collaboration.messages import MESSAGE_TYPES, Message, MessageBus, MessageError

SeatDecision = Callable[["SeatView"], "Decision | None"]


class SeatError(ValueError):
    """A seat broke its own contract; never a protocol refusal of the bus."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True)
class SeatView:
    """Everything a seat may see, and nothing more.

    Deliberately excludes Roles, Task ownership, Leases and every other
    Agent's private state: the view is identical in shape for all seats so
    no seat can reach a place its peer cannot.
    """

    project_id: str
    agent_id: str
    inbox: tuple[Message, ...]
    #: Messages this seat itself sent. ``MessageBus.inbox`` is a received-mail
    #: view and deliberately excludes a sender's own words, so remembering what
    #: one has already said is the seat's own responsibility. Nothing here is
    #: privileged: it is exactly this seat's own outbox.
    said: tuple[Message, ...] = ()

    def received_from(self, other: str) -> tuple[Message, ...]:
        return tuple(message for message in self.inbox if message.sender_id == other)

    def answered(self) -> frozenset[str]:
        """Identifiers this seat has already replied to."""
        return frozenset(message.target_message for message in self.said
                         if message.target_message is not None)


@dataclass(frozen=True, slots=True)
class Decision:
    """What a seat wants to say. The system supplies no defaults.

    ``untrusted_input`` exists only so a seat can *claim* trust and be
    overruled: ``AgentSeat.step`` never reads it and always marks the outgoing
    message untrusted. Keeping the field makes the refusal testable instead of
    letting a seat believe its claim was honoured.
    """

    type: str
    content: str
    recipients: tuple[str, ...]
    references: tuple[str, ...] = ()
    target_message: str | None = None
    untrusted_input: bool = True

    def __post_init__(self) -> None:
        if self.type not in MESSAGE_TYPES:
            raise SeatError("UNSUPPORTED_MESSAGE_TYPE")
        if not isinstance(self.content, str) or not self.content.strip():
            raise SeatError("EMPTY_CONTENT")
        if not isinstance(self.recipients, tuple) or not self.recipients:
            raise SeatError("EMPTY_RECIPIENTS")
        if not isinstance(self.references, tuple):
            raise SeatError("INVALID_REFERENCES")
        if not isinstance(self.untrusted_input, bool):
            raise SeatError("INVALID_TRUST_FLAG")
        if self.target_message is not None and self.target_message not in self.references:
            raise SeatError("TARGET_NOT_REFERENCED")


class AgentSeat:
    """One equal participant: a decision function plus its own identity."""

    def __init__(self, agent_id: str, decide: SeatDecision, *, bus: MessageBus):
        if not isinstance(agent_id, str) or not agent_id.strip():
            raise SeatError("INVALID_AGENT_ID")
        if not callable(decide):
            raise SeatError("INVALID_DECISION_FUNCTION")
        if not isinstance(bus, MessageBus):
            raise SeatError("INVALID_BUS")
        self.agent_id = agent_id
        self._decide = decide
        self._bus = bus
        self._counter = 0
        self._said: list[Message] = []

    def view(self, project_id: str) -> SeatView:
        return SeatView(project_id=project_id, agent_id=self.agent_id,
                        inbox=self._bus.inbox(project_id, authenticated_actor_id=self.agent_id),
                        said=tuple(message for message in self._said
                                   if message.project_id == project_id))

    def step(self, project_id: str) -> Message | None:
        """Ask the decision function once and, if it decided, speak as this seat."""
        decision = self._decide(self.view(project_id))
        if decision is None:
            return None
        if not isinstance(decision, Decision):
            raise SeatError("INVALID_DECISION")
        if self.agent_id in decision.recipients:
            raise SeatError("SEAT_ADDRESSED_ITSELF")
        self._counter += 1
        message = Message(
            id=f"{self.agent_id}-seat-{self._counter}",
            project_id=project_id,
            sender_id=self.agent_id,
            recipients=decision.recipients,
            type=decision.type,
            content=decision.content,
            references=decision.references,
            target_message=decision.target_message,
            # A seat's words are its own opinion, never trusted project input.
            untrusted_input=True,
        )
        # The bus authenticates with this seat's identity, so a seat cannot
        # speak for its peer even if its decision claims otherwise.
        sent = self._bus.send(message, authenticated_actor_id=self.agent_id)
        self._said.append(sent)
        return sent


def converse(seats: Sequence[AgentSeat], project_id: str, *, rounds: int) -> list[Message]:
    """Round-robin turns until every seat is silent or the round budget ends.

    Round-robin keeps the seats equal: no seat is the chair, and a silent
    seat never loses its turn for the next round.
    """
    if not isinstance(seats, (list, tuple)) or not seats:
        raise SeatError("NO_SEATS")
    if not isinstance(rounds, int) or rounds < 1:
        raise SeatError("INVALID_ROUNDS")
    identifiers = [seat.agent_id for seat in seats]
    if len(set(identifiers)) != len(identifiers):
        raise SeatError("DUPLICATE_SEAT")
    said: list[Message] = []
    for _ in range(rounds):
        spoke = False
        for seat in seats:
            message = seat.step(project_id)
            if message is None:
                continue
            said.append(message)
            spoke = True
        if not spoke:
            break
    return said


def seat_evidence(messages: Sequence[Message], *, project_id: str, actor_id: str,
                  bus: MessageBus) -> dict[str, Any]:
    """Snapshot a conversation as evidence, with digests computed by the bus.

    Only messages the actor can already see are snapshotted, so this cannot
    widen anyone's visibility.
    """
    visible = [message for message in messages
               if message.project_id == project_id
               and (message.sender_id == actor_id or actor_id in message.recipients)]
    if not visible:
        # A seat-level code, not the bus's INVALID_REFERENCE: nothing here was
        # an invalid reference, the actor simply has no visible messages.
        raise SeatError("NOTHING_VISIBLE")
    identifiers = tuple(message.id for message in visible)
    return {
        "project_id": project_id,
        "snapshotted_by": actor_id,
        "senders": sorted({message.sender_id for message in visible}),
        "messages": bus.snapshots(project_id, identifiers, authenticated_actor_id=actor_id),
    }
