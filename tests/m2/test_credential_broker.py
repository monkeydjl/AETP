"""Credential Broker minimal semantics (spec 14.3 / INV-012).

An Agent never holds long-term secrets. It requests a short-term scoped
credential bound to explicit permissions and a wall-clock expiry. Pausing a
Project must NOT extend a credential's real validity.
"""

import unittest

from aetp.governance.credential_broker import CredentialBroker, CredentialBrokerError


class CredentialBrokerTests(unittest.TestCase):
    def setUp(self):
        self.broker = CredentialBroker()
        self.now = 1_800_000_000_000  # wall clock ms anchor

    def _issue(self, *, permissions=("github.repo.read",), expires_in=30_000):
        return self.broker.issue(
            agent="agent-work",
            permissions=permissions,
            issued_at=self.now,
            expires_in_ms=expires_in,
        )

    def test_issue_returns_scoped_opaque_token(self):
        credential = self._issue()
        self.assertIn("token", credential)
        self.assertIn("expires_at_ms", credential)
        # Credential is scoped, not the long-term secret itself.
        self.assertEqual(credential["permissions"], ["github.repo.read"])

    def test_resolve_within_window_grants_exact_permissions(self):
        credential = self._issue(permissions=("github.repo.read", "github.repo.write"))
        granted = self.broker.resolve(credential["token"], self.now + 10_000)
        self.assertEqual(granted["permissions"], ["github.repo.read", "github.repo.write"])

    def test_expired_credential_is_rejected(self):
        credential = self._issue(expires_in=30_000)
        with self.assertRaises(CredentialBrokerError) as ctx:
            self.broker.resolve(credential["token"], self.now + 30_001)
        self.assertEqual(ctx.exception.code, "CREDENTIAL_EXPIRED")

    def test_permission_not_in_scope_is_rejected(self):
        credential = self._issue(permissions=("github.repo.read",))
        with self.assertRaises(CredentialBrokerError) as ctx:
            self.broker.assert_permission(credential["token"], "github.repo.write", self.now + 1_000)
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")

    def test_pause_does_not_extend_credential_validity(self):
        """Wall-clock expiry: a Project pause must not extend the credential."""
        credential = self._issue(expires_in=30_000)
        # Simulate a long pause: wall clock advances far past expiry.
        with self.assertRaises(CredentialBrokerError):
            self.broker.resolve(credential["token"], self.now + 30_000 + 1)

    def test_revoked_credential_is_rejected(self):
        credential = self._issue()
        self.broker.revoke(credential["token"])
        with self.assertRaises(CredentialBrokerError) as ctx:
            self.broker.resolve(credential["token"], self.now + 1_000)
        self.assertEqual(ctx.exception.code, "CREDENTIAL_REVOKED")

    def test_unknown_token_rejected(self):
        with self.assertRaises(CredentialBrokerError) as ctx:
            self.broker.resolve("not-a-token", self.now)
        self.assertEqual(ctx.exception.code, "CREDENTIAL_UNKNOWN")

    def test_assert_permission_by_ref_uses_non_invertible_ref(self):
        """Consuming side passes the persisted ref, not the token body."""
        credential = self._issue(permissions=("github.repo.read",))
        ref = credential["token_ref"]
        granted = self.broker.assert_permission_by_ref(ref, "github.repo.read", self.now + 1_000)
        self.assertEqual(granted["permissions"], ["github.repo.read"])
        # Ref cannot be used for an out-of-scope permission.
        with self.assertRaises(CredentialBrokerError) as ctx:
            self.broker.assert_permission_by_ref(ref, "github.repo.write", self.now + 1_000)
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")

    def test_assert_permission_by_ref_unknown_ref_rejected(self):
        with self.assertRaises(CredentialBrokerError) as ctx:
            self.broker.assert_permission_by_ref("credref_nope", "github.repo.read", self.now)
        self.assertEqual(ctx.exception.code, "CREDENTIAL_UNKNOWN")

    def test_assert_permission_by_ref_respects_expiry_and_revoke(self):
        credential = self._issue(permissions=("github.repo.read",), expires_in=30_000)
        ref = credential["token_ref"]
        with self.assertRaises(CredentialBrokerError) as ctx:
            self.broker.assert_permission_by_ref(ref, "github.repo.read", self.now + 30_001)
        self.assertEqual(ctx.exception.code, "CREDENTIAL_EXPIRED")
        credential2 = self._issue(permissions=("github.repo.read",))
        ref2 = credential2["token_ref"]
        self.broker.revoke_by_ref(ref2)
        with self.assertRaises(CredentialBrokerError) as ctx:
            self.broker.assert_permission_by_ref(ref2, "github.repo.read", self.now + 1_000)
        self.assertEqual(ctx.exception.code, "CREDENTIAL_REVOKED")


if __name__ == "__main__":
    unittest.main()