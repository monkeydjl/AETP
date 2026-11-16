"""One credential broker must serve both sides of the revocation fact.

The governance side revokes (`GovernanceService.credential_broker`) while the
consuming side authorises (`DocumentRuntime.credential_broker`, read by
`runtime/actions.py`). If the host wires two different instances, a revocation
is recorded and then silently ignored at the call boundary, which is the exact
loophole the revoke sync was meant to close.

So the two mount points are not independent knobs: attaching a broker on the
governance side must reach the consuming side, and a conflicting broker must be
refused rather than accepted.
"""

import unittest

from aetp.governance.credential_broker import CredentialBroker
from aetp.governance.service import GovernanceService
from tests.m2.governance_support import GovernanceCase


class CredentialBrokerWiringTests(GovernanceCase):
    def test_attaching_a_broker_reaches_the_consuming_side(self):
        """The consuming side must see the same instance, or revoke is cosmetic."""
        broker = CredentialBroker()
        self.service.credential_broker = broker
        self.assertIs(self.runtime.credential_broker, broker)

    def test_conflicting_brokers_are_refused(self):
        """Two instances cannot both be authoritative: refuse the second."""
        self.runtime.credential_broker = CredentialBroker()
        with self.assertRaises(ValueError):
            self.service.credential_broker = CredentialBroker()

    def test_reattaching_the_same_instance_is_idempotent(self):
        broker = CredentialBroker()
        self.service.credential_broker = broker
        self.service.credential_broker = broker
        self.assertIs(self.runtime.credential_broker, broker)

    def test_clearing_the_governance_broker_leaves_the_consuming_side_alone(self):
        """Detaching on one side must not silently disable the other's check."""
        broker = CredentialBroker()
        self.service.credential_broker = broker
        self.service.credential_broker = None
        self.assertIs(self.runtime.credential_broker, broker)

    def test_revoked_credential_is_refused_after_wiring(self):
        """End to end: wire once, revoke, and the consuming side refuses."""
        broker = CredentialBroker()
        self.service.credential_broker = broker
        issued = broker.issue("a-1", permissions=["github.repo.read"],
                              issued_at=self.clock_value, expires_in_ms=30_000)
        broker.assert_permission_by_ref(issued["token_ref"], "github.repo.read", self.clock_value + 1)

        self.accept(self.command("credential.request", "cred-1",
                                 {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1"))
        record = self.state()["credential:cred-1"]
        broker.assert_permission_by_ref(record["token_ref"], "github.repo.read", self.clock_value + 1)

        self.accept(self.command("credential.revoke", "cred-1", {}, actor="human-owner"))
        with self.assertRaises(Exception) as ctx:
            broker.assert_permission_by_ref(record["token_ref"], "github.repo.read", self.clock_value + 1)
        self.assertEqual(getattr(ctx.exception, "code", None), "CREDENTIAL_REVOKED")


    def test_rebinding_the_consuming_side_makes_revoke_fail_closed(self):
        """A swapped consuming broker would ignore the revoke: refuse instead."""
        broker = CredentialBroker()
        self.service.credential_broker = broker
        self.accept(self.command("credential.request", "cred-1",
                                 {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1"))

        # The host swaps the consuming-side broker behind governance's back.
        self.runtime.credential_broker = CredentialBroker()

        result = self.service.handle(self.command("credential.revoke", "cred-1", {}, actor="human-owner"),
                                     authenticated_actor_id="human-owner")
        self.assertEqual((result.status, result.error_code), ("rejected", "CREDENTIAL_UNAVAILABLE"))
        self.assertFalse(self.state()["credential:cred-1"]["revoked"])

    def test_execution_attached_after_wiring_does_not_split_the_broker(self):
        """Late-attached execution must not leave two brokers in charge."""
        broker = CredentialBroker()
        self.service.credential_broker = broker
        self.accept(self.command("credential.request", "cred-1",
                                 {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1"))

        # A second broker appears on the consuming side after the fact.
        self.runtime.credential_broker = CredentialBroker()

        result = self.service.handle(self.command("credential.revoke", "cred-1", {}, actor="a-1"),
                                     authenticated_actor_id="a-1")
        self.assertEqual((result.status, result.error_code), ("rejected", "CREDENTIAL_UNAVAILABLE"))

    def test_execution_attached_after_wiring_pins_the_broker(self):
        """Attaching execution later must still reach the consuming side."""
        broker = CredentialBroker()
        late = GovernanceService(self.store, owner_id="human-owner",
                                 input_authority=self.input_authority,
                                 meter=self.meter, clock=lambda: self.clock_value)
        late.credential_broker = broker
        late.execution = self.execution
        self.assertIs(self.runtime.credential_broker, broker)

    def test_rebinding_the_consuming_side_makes_issue_fail_closed(self):
        """Minting into a broker the call boundary ignores would lie about success.

        Revoke already refuses in this state. Issue must match it: the token
        would be recorded as granted while the consuming side answers
        CREDENTIAL_UNKNOWN, so the Command reports a credential nobody can use.
        """
        broker = CredentialBroker()
        self.service.credential_broker = broker

        # The host swaps the consuming-side broker behind governance's back.
        self.runtime.credential_broker = CredentialBroker()

        result = self.service.handle(
            self.command("credential.request", "cred-1",
                         {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1"),
            authenticated_actor_id="a-1")

        self.assertEqual((result.status, result.error_code), ("rejected", "CREDENTIAL_UNAVAILABLE"))
        self.assertNotIn("credential:cred-1", self.state())
        self.assertEqual(broker._credentials, {}, "a token was minted into an unreachable Broker")

if __name__ == "__main__":
    unittest.main()
