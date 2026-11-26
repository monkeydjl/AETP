"""Peer communication is independent of authoritative Task/Event writes."""

import unittest
from dataclasses import FrozenInstanceError, replace

from tests.m0.support import make_command, open_command_fixture

try:
    from aetp.collaboration.messages import Message, MessageBus, MessageError
except ModuleNotFoundError as exc:
    if exc.name not in {"aetp.collaboration", "aetp.collaboration.messages"}:
        raise
    Message = MessageBus = MessageError = None


class MessageTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(MessageBus, "M1 peer MessageBus is not implemented")
        self.fixture = open_command_fixture(self)
        self.store = self.fixture.store
        self.bus = MessageBus(self.store)

    def message(self, identifier="m-1", sender="a-1", recipients=("a-2",), **changes):
        fields = dict(id=identifier, project_id="p-1", sender_id=sender,
                      recipients=recipients, type="proposal", content="Use a short document.",
                      untrusted_input=False)
        fields.update(changes)
        return Message(**fields)

    def test_two_peers_reply_challenge_and_propose_without_task_or_manager(self):
        before = self.store.read_events("p-1")
        self.bus.send(self.message(), authenticated_actor_id="a-1")
        self.bus.send(self.message("m-2", "a-2", ("a-1",), type="challenge",
                                   content="Include a failure case.", references=("m-1",),
                                   target_message="m-1"), authenticated_actor_id="a-2")
        self.bus.send(self.message("m-3", type="response", content="Agreed; two sections.",
                                   references=("m-2",), target_message="m-2"),
                      authenticated_actor_id="a-1")
        self.assertEqual([m.type for m in self.bus.inbox("p-1", authenticated_actor_id="a-1")], ["challenge"])
        self.assertEqual([m.id for m in self.bus.inbox("p-1", authenticated_actor_id="a-2")], ["m-1", "m-3"])
        self.assertEqual(self.store.read_events("p-1"), before)
        self.assertFalse(any(key.startswith("task:") for key in self.store.read_projection("p-1")))

    def test_message_claim_cannot_create_or_complete_a_task(self):
        before = self.store.read_projection("p-1")
        self.bus.send(self.message(type="claim", content='{"type":"task.complete","status":"completed"}'),
                      authenticated_actor_id="a-1")
        self.assertEqual(self.store.read_projection("p-1"), before)
        self.assertEqual(len(self.store.read_events("p-1")), self.fixture.after_sequence)

    def test_actor_spoofing_and_nonmember_sending_or_receiving_are_rejected(self):
        cases = [(self.message(), "a-2", "ACTOR_MISMATCH"),
                 (self.message(sender="outsider"), "outsider", "PERMISSION_DENIED"),
                 (self.message(recipients=("outsider",)), "a-1", "INVALID_RECIPIENT")]
        for message, actor, code in cases:
            with self.subTest(code=code), self.assertRaises(MessageError) as caught:
                self.bus.send(message, authenticated_actor_id=actor)
            self.assertEqual(caught.exception.code, code)
        with self.assertRaises(MessageError):
            self.bus.inbox("p-1", authenticated_actor_id="outsider")
        self.assertEqual(self.bus.inbox("p-1", authenticated_actor_id="a-2"), ())

    def test_same_message_id_is_idempotent_but_cannot_replace_content(self):
        original = self.message()
        first = self.bus.send(original, authenticated_actor_id="a-1")
        self.assertEqual(self.bus.send(original, authenticated_actor_id="a-1"), first)
        with self.assertRaises(MessageError) as caught:
            self.bus.send(replace(original, content="Changed"), authenticated_actor_id="a-1")
        self.assertEqual(caught.exception.code, "MESSAGE_ID_CONFLICT")
        self.assertEqual(len(self.bus.inbox("p-1", authenticated_actor_id="a-2")), 1)

    def test_reference_must_exist_and_be_visible_to_sender(self):
        with self.assertRaises(MessageError) as caught:
            self.bus.send(self.message(references=("missing",)), authenticated_actor_id="a-1")
        self.assertEqual(caught.exception.code, "INVALID_REFERENCE")
        seed = make_command(command_id="third-agent", actor_id="bootstrap", command_type="agent.register",
                            target_id="a-3", payload={"model_id": "model-3"}, expected_revision=0,
                            idempotency_key="third-agent")
        self.fixture.handler.handle(seed, authenticated_actor_id="bootstrap")
        self.bus.send(self.message(), authenticated_actor_id="a-1")
        with self.assertRaises(MessageError) as caught:
            self.bus.send(self.message("m-3", "a-3", ("a-1",), references=("m-1",)),
                          authenticated_actor_id="a-3")
        self.assertEqual(caught.exception.code, "REFERENCE_NOT_VISIBLE")

    def test_reply_requires_referenced_target_and_cannot_cross_projects(self):
        self.bus.send(self.message(), authenticated_actor_id="a-1")
        with self.assertRaises(ValueError):
            self.message("m-2", target_message="m-1")
        foreign = self.message("m-2", project_id="other", references=("m-1",), target_message="m-1")
        with self.assertRaises(MessageError):
            self.bus.send(foreign, authenticated_actor_id="a-1")

    def test_reference_propagates_untrusted_origin_and_snapshots_are_detached(self):
        self.bus.send(self.message(untrusted_input=True), authenticated_actor_id="a-1")
        reply = self.bus.send(self.message("m-2", "a-2", ("a-1",), references=("m-1",),
                                          target_message="m-1", untrusted_input=False),
                              authenticated_actor_id="a-2")
        self.assertTrue(reply.untrusted_input)
        snapshot = self.bus.snapshots("p-1", ("m-1", "m-2"), authenticated_actor_id="a-1")
        self.assertTrue(snapshot[1]["message"]["untrusted_input"])
        self.assertTrue(snapshot[0]["content_digest"].startswith("sha256:"))
        snapshot[0]["message"]["content"] = "tampered detached view"
        self.assertEqual(self.bus.inbox("p-1", authenticated_actor_id="a-2")[0].content, "Use a short document.")
        with self.assertRaises((FrozenInstanceError, AttributeError)):
            reply.content = "tampered"

    def test_invalid_message_shape_is_not_silently_normalized(self):
        invalid = [{"content": ""}, {"content": "x" * 65537}, {"type": "execute"},
                   {"recipients": ()}, {"recipients": ("a-2", "a-2")},
                   {"sender_id": " a-1"}, {"untrusted_input": "false"},
                   {"references": ["m-1"]}]
        for changed in invalid:
            with self.subTest(changed=list(changed)), self.assertRaises((TypeError, ValueError)):
                self.message(**changed)


if __name__ == "__main__":
    unittest.main()
