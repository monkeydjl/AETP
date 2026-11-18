"""A peer agent's delivered work must pass real execution admission, not just planning.

TEST-028 covers the negotiation and planning lifecycle and is honestly labelled
`simulation-only`: it never constructs an ExecutionService, so the "delivery" it
records is a set of planning and acceptance Events. That leaves a question open,
and this module answers it on the real objects: when a second, equal agent takes
on the delivered Task, do execution admission rules actually bite on that path?

The gap that makes this worth pinning: a passing planning chain is easy to
mistake for a working delivery chain. Each test below drives a real
Command -> Event Store -> Projection -> dispatch path and asserts the refusal
arrives from admission, not from a fixture that politely stepped aside.
"""

import unittest

from aetp.core.projection import Projection
from tests.m1 import execution_support

# Named here rather than imported from Projection so the test states the
# contract it relies on instead of borrowing a private constant. Both types are
# audit trail by design: M0 conformance asserts command.received appears in the
# committed batch, so a refusal is expected to leave these behind.
AUDIT_TYPES = frozenset({"command.received", "command.rejected"})


def domain_events(events):
    """Domain effects only, excluding audit trail.

    A refusal may record that it happened; what it must never do is produce a
    domain Event.
    """
    return [event for event in events if event.type not in AUDIT_TYPES]


class PeerDeliveryRealExecutionTests(unittest.TestCase):
    def setUp(self):
        self.case = execution_support.ExecutionCase("runTest")
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()

    def test_the_local_audit_range_matches_production(self):
        """A drift here would silently weaken every refusal assertion below.

        AUDIT_TYPES is restated rather than imported so this module does not lean
        on a private constant; this test is what keeps the restatement honest.
        """
        from aetp.core.projection import _AUDIT_TYPES
        self.assertEqual(AUDIT_TYPES, _AUDIT_TYPES,
                         "test constant drifted from Projection._AUDIT_TYPES")

    def test_a_peer_cannot_take_over_a_task_an_equal_agent_already_claimed(self):
        """Equality means no peer is privileged, not that any peer may seize work.

        Rejecting here is what keeps 'equal agents' from degrading into 'whoever
        asks last owns it'.
        """
        self.case.claim(actor="a-1")
        self.assertEqual(self.case.task()["owner_id"], "a-1")

        result = self.case.service.handle(
            self.case.command("task.claim", "t-1", {}, actor="a-2"),
            authenticated_actor_id="a-2")

        self.assertEqual(result.status, "rejected", result.to_dict())
        self.assertEqual(result.error_code, "TASK_NOT_ASSIGNABLE")
        self.assertEqual(self.case.task()["owner_id"], "a-1",
                         "a rejected claim must not move ownership")

    def test_a_refused_peer_claim_leaves_no_trace(self):
        """A refused Command must not become a fact (§ command handling)."""
        self.case.claim(actor="a-1")
        before = self.case.store.read_events("p-1")
        state_before = self.case.state()

        self.case.service.handle(
            self.case.command("task.claim", "t-1", {}, actor="a-2"),
            authenticated_actor_id="a-2")

        after = self.case.store.read_events("p-1")
        self.assertEqual(domain_events(after), domain_events(before),
                         "a rejected claim must append no domain Event")
        self.assertTrue(all(event.type in AUDIT_TYPES for event in after[len(before):]),
                        "the only new Events may be audit trail")
        self.assertEqual(Projection.rebuild(after), state_before)

    def test_the_delivered_task_reaches_a_real_action_under_the_owners_session(self):
        """The delivery actually executes: claim -> start -> tool.request -> dispatch."""
        self.case.claim(actor="a-1")
        session = self.case.start(actor="a-1")
        self.assertEqual(self.case.task()["status"], "in_progress")

        action = self.case.request(operation="document.write", arguments={"content": "delivered\n"})
        self.assertEqual(action["status"], "pending")
        self.assertEqual(self.case.dispatch(action)["status"], "completed")

    def test_a_tool_request_outside_a_session_is_refused_before_any_action(self):
        """Admission, not luck: no session means no Action.

        Without this, the previous test could pass for the wrong reason (an
        execution path that accepts anything) and still look like proof.
        """
        self.case.claim(actor="a-1")
        before = self.case.store.read_events("p-1")

        command = self.case.command("tool.request", "t-1",
                                    {"binding_id": self.case.task()["current_binding_id"],
                                     "lease_epoch": self.case.task()["lease_epoch"],
                                     "operation": "document.write",
                                     "arguments": {"content": "no session\n"}},
                                    actor="a-1")
        result = self.case.service.handle(command, authenticated_actor_id="a-1")

        self.assertEqual(result.status, "rejected", result.to_dict())
        self.assertEqual(result.error_code, "SESSION_INVALID",
                         "the refusal must come from the missing-session rule by name, "
                         "not merely from some admission check")
        after = self.case.store.read_events("p-1")
        self.assertEqual(domain_events(after), domain_events(before),
                         "a refused tool.request must append no domain Event")
        self.assertFalse([key for key in self.case.state() if key.startswith("action:")],
                         "a refused tool.request must materialise no Action at all")


if __name__ == "__main__":
    unittest.main()
