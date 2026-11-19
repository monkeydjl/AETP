"""M3-03: injected agent seats, so a conversation is not a script of strings.

What these tests pin down is narrower than "real autonomous agents": two
distinct decision functions hold two equal seats, and whatever crosses the
bus is chosen by them. No LLM, no network and no external runtime is
involved, so the suite stays repeatable. A passing run must never be read as
evidence that a real external model negotiated.
"""

import unittest

from aetp.collaboration.messages import Message, MessageBus, MessageError
from aetp.collaboration.seats import (
    AgentSeat, Decision, SeatError, SeatView, converse, seat_evidence,
)
from tests.m0.support import open_command_fixture


def analyst(view: SeatView):
    """Proposes once, then answers each challenge it has not answered yet.

    The seat learns what it already said from ``view.said``: ``MessageBus.inbox``
    is a received-mail view and never returns a sender's own messages.
    """
    answered = view.answered()
    if any(message.type == "proposal" for message in view.said):
        open_challenge = [m for m in view.inbox
                          if m.type == "challenge" and m.id not in answered]
        if not open_challenge:
            return None
        latest = open_challenge[-1]
        return Decision(type="response", content="Accepted; I will add failure cases to the schema.",
                        recipients=(latest.sender_id,), references=(latest.id,),
                        target_message=latest.id)
    return Decision(type="proposal", content="Ship one JSON document with a schema.",
                    recipients=("a-2",))


def architect(view: SeatView):
    """Challenges the proposal once, then challenges the first reply once.

    Two challenges is where this seat stops: it has nothing further to add, so
    the conversation terminates instead of echoing forever.
    """
    answered = view.answered()
    challenged = {message.target_message for message in view.said}
    if len(view.said) >= 2:
        return None
    for kind, text in (("response", "A second defect: what about empty input?"),
                       ("proposal", "What happens when the document is invalid?")):
        pending = [m for m in view.inbox
                   if m.type == kind and m.id not in challenged and m.id not in answered]
        if pending:
            latest = pending[-1]
            return Decision(type="challenge", content=text,
                            recipients=(latest.sender_id,), references=(latest.id,),
                            target_message=latest.id)
    return None


class AgentSeatTests(unittest.TestCase):
    def setUp(self):
        self.fixture = open_command_fixture(self)
        self.store = self.fixture.store
        self.bus = MessageBus(self.store)
        self.a1 = AgentSeat("a-1", analyst, bus=self.bus)
        self.a2 = AgentSeat("a-2", architect, bus=self.bus)

    def test_two_distinct_deciders_produce_the_conversation(self):
        said = converse([self.a1, self.a2], "p-1", rounds=4)
        # Content comes from the decision functions, never from this test.
        # Five turns, then both seats go quiet: a-1 proposes and answers both
        # challenges, a-2 raises exactly two and stops.
        self.assertEqual([m.sender_id for m in said],
                         ["a-1", "a-2", "a-1", "a-2", "a-1"])
        self.assertEqual([m.type for m in said],
                         ["proposal", "challenge", "response", "challenge", "response"])
        self.assertEqual(said[0].content, "Ship one JSON document with a schema.")
        self.assertEqual(said[1].content, "What happens when the document is invalid?")
        self.assertEqual(said[2].target_message, said[1].id)

    def test_seats_are_equal_and_leave_no_task_or_event(self):
        before_events = self.store.read_events("p-1")
        before_state = self.store.read_projection("p-1")
        converse([self.a1, self.a2], "p-1", rounds=4)
        self.assertEqual(self.store.read_events("p-1"), before_events)
        self.assertEqual(self.store.read_projection("p-1"), before_state)
        self.assertFalse(any(key.startswith("task:") for key in before_state))
        # Neither seat has a privileged inbox: same field set, and a seat that
        # nobody addressed starts empty rather than seeing everything.
        first, second = self.a1.view("p-1"), self.a2.view("p-1")
        self.assertEqual(set(first.__slots__), set(second.__slots__))
        self.assertEqual(set(first.__slots__),
                         {"project_id", "agent_id", "inbox", "said"})
        # A seat sees exactly the bus inbox addressed to it, nothing wider.
        for seat in (self.a1, self.a2):
            with self.subTest(seat=seat.agent_id):
                self.assertEqual(seat.view("p-1").inbox,
                                 self.bus.inbox("p-1", authenticated_actor_id=seat.agent_id))

    def test_a_seat_cannot_speak_as_its_peer(self):
        # A seat deciding to impersonate still goes through AgentSeat.step, so
        # the envelope's sender_id is whatever the seat really is.
        liar = AgentSeat("a-1", lambda view: Decision(
            type="agreement", content="I am a-2", recipients=("a-2",)), bus=self.bus)
        sent = liar.step("p-1")
        self.assertEqual(sent.sender_id, "a-1")
        self.assertEqual(liar.view("p-1").said[0].sender_id, "a-1")
        # The bus itself refuses a message that claims a different sender.
        with self.assertRaises(MessageError) as caught:
            self.bus.send(
                Message(id="fake-1", project_id="p-1", sender_id="a-2",
                        recipients=("a-1",), type="agreement", content="I agree.",
                        untrusted_input=False),
                authenticated_actor_id="a-1")
        self.assertEqual(caught.exception.code, "ACTOR_MISMATCH")

    def test_a_seat_decision_cannot_address_itself_or_skip_validation(self):
        seat = AgentSeat("a-1", lambda view: Decision(type="proposal", content="x",
                                                      recipients=("a-1",)), bus=self.bus)
        with self.assertRaises(SeatError) as caught:
            seat.step("p-1")
        self.assertEqual(caught.exception.code, "SEAT_ADDRESSED_ITSELF")
        with self.assertRaises(SeatError):
            Decision(type="not-a-type", content="x", recipients=("a-2",))
        with self.assertRaises(SeatError):
            Decision(type="proposal", content="   ", recipients=("a-2",))
        with self.assertRaises(SeatError):
            Decision(type="response", content="x", recipients=("a-2",), target_message="m-9")

    def test_seat_words_are_untrusted_input_even_when_a_seat_claims_otherwise(self):
        # A seat that claims trust is overruled, not obeyed: Decision carries
        # the claim field, AgentSeat.step never reads it and always marks the
        # outgoing message untrusted.
        claimed = AgentSeat("a-1", lambda view: Decision(
            type="notification", content="trust me", recipients=("a-2",),
            untrusted_input=False), bus=self.bus)
        self.assertTrue(claimed.step("p-1").untrusted_input)

        # Trust does not propagate back out: a message citing an untrusted one
        # stays untrusted even if its author claims otherwise.
        cited = claimed.view("p-1").said[0]
        citing = AgentSeat("a-2", lambda view: Decision(
            type="response", content="citing", recipients=("a-1",),
            references=(cited.id,), target_message=cited.id,
            untrusted_input=False), bus=self.bus)
        self.assertTrue(citing.step("p-1").untrusted_input)

    def test_converse_needs_equal_unique_seats_and_a_round_budget(self):
        with self.assertRaises(SeatError):
            converse([], "p-1", rounds=1)
        with self.assertRaises(SeatError):
            converse([self.a1], "p-1", rounds=0)
        with self.assertRaises(SeatError):
            converse([self.a1, AgentSeat("a-1", architect, bus=self.bus)], "p-1", rounds=1)

    def test_silent_seat_stops_the_round_early(self):
        quiet = AgentSeat("a-2", lambda view: None, bus=self.bus)
        said = converse([self.a1, quiet], "p-1", rounds=5)
        # a-1 proposes on turn one and then waits for a challenge that never
        # comes, so it falls silent too and the round budget is not exhausted.
        self.assertEqual([m.sender_id for m in said], ["a-1"])

    def test_evidence_snapshot_carries_digests_and_only_visible_messages(self):
        said = converse([self.a1, self.a2], "p-1", rounds=4)
        self.assertTrue(said)
        # a-2 took part, so it sees the whole conversation.
        own = seat_evidence(said, project_id="p-1", actor_id="a-2", bus=self.bus)
        self.assertEqual(own["senders"], ["a-1", "a-2"])
        self.assertEqual(len(own["messages"]), len(said))
        for entry in own["messages"]:
            self.assertTrue(entry["content_digest"].startswith("sha256:"))

        # The seat-local filter only narrows; the bus decides visibility. An
        # actor that sees nothing is refused by this module...
        with self.assertRaises(SeatError) as caught:
            seat_evidence(said, project_id="p-1", actor_id="outsider", bus=self.bus)
        self.assertEqual(caught.exception.code, "NOTHING_VISIBLE")

        # ...and an actor that passes the local filter but is not a member is
        # still refused by the bus, whose error we do not swallow.
        partial = seat_evidence(
            (m for m in said if m.sender_id == "a-2"), project_id="p-1",
            actor_id="a-2", bus=self.bus)
        self.assertEqual(len(partial["messages"]), 2)
        with self.assertRaises(MessageError):
            self.bus.snapshots("p-1", (said[0].id,), authenticated_actor_id="outsider")

    def test_received_from_narrows_the_inbox_to_one_sender(self):
        """The seat's own filter, and the bus's visibility, are different things.

        A seat can narrow what it already sees; it can never widen it. This is
        the narrowing half, and it must not invent mail: a sender who said
        nothing, or is not a member at all, produces an empty tuple rather than
        an error or a default.
        """
        self.assertEqual(self.a1.view("p-1").received_from("a-2"), ())
        said = converse([self.a1, self.a2], "p-1", rounds=4)
        self.assertTrue(said)

        inbox = self.bus.inbox("p-1", authenticated_actor_id="a-1")
        view = SeatView(project_id="p-1", agent_id="a-1", inbox=inbox)
        from_a2 = view.received_from("a-2")
        self.assertTrue(from_a2)
        self.assertTrue(all(m.sender_id == "a-2" for m in from_a2))
        # The order is the inbox's own; narrowing does not reshuffle it.
        self.assertEqual(from_a2, tuple(m for m in inbox if m.sender_id == "a-2"))
        # A sender that never spoke and one that is not a member both give nothing.
        self.assertEqual(view.received_from("a-1"), ())
        self.assertEqual(view.received_from("nobody"), ())

    def test_a_non_member_never_becomes_a_speaking_seat(self):
        # Membership is the bus's check, not the seat's: an unregistered agent
        # holding a seat is refused on its first turn.
        ghost = AgentSeat("a-3", lambda view: Decision(
            type="proposal", content="I am not a member", recipients=("a-1",)),
            bus=self.bus)
        with self.assertRaises(MessageError) as caught:
            ghost.step("p-1")
        self.assertEqual(caught.exception.code, "PERMISSION_DENIED")
        # The refusal happens before anything is sent, so the ghost never got
        # a message id and nothing reached the bus.
        self.assertFalse(any(m.sender_id == "a-3"
                             for m in self.bus.inbox("p-1", authenticated_actor_id="a-1")))


if __name__ == "__main__":
    unittest.main()
