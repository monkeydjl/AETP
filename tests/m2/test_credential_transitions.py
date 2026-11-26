"""Credential command transitions (spec 14.3 / INV-012): scoped, wall-clock TTL.

The Broker holds the secret; only an opaque token_ref and scope/expiry metadata
enter the Projection. Replay rebuilds that metadata without re-minting.
"""

import unittest

from aetp.collaboration.policy import PolicyViolation
from aetp.domain.models import Command
from aetp.governance import credentials


class CredentialTransitionTests(unittest.TestCase):
    def _command(self, type_, payload, *, actor="a-1", target="cred-1", revision=0):
        return Command("cmd-1", "p-1", actor, type_, target, payload, revision, "cmd-1", "corr")

    def _state(self, *, credential=None):
        state = {
            "project:p-1": {
                "id": "p-1", "revision": 1, "status": "active",
                "governance": {
                    "current_version": "gov-1",
                    "versions": {"gov-1": {"policy": {
                        "subjects": {
                            "a-1": {"type": "agent", "roles": ["engineer"]},
                            "human-owner": {"type": "human", "roles": ["human_owner"]},
                        },
                    }}},
                },
            },
            "agent:a-1": {"id": "a-1", "project_id": "p-1", "status": "available"},
        }
        if credential is not None:
            state["credential:cred-1"] = credential
        return state

    def test_issue_persists_scope_and_expiry_without_token(self):
        """Issued credential records scope/expiry, never the token body."""
        state = self._state()
        command = self._command("credential.request", {
            "permissions": ["github.repo.read"], "ttl_ms": 1800000},
            actor="a-1")
        kind, record = credentials.issue(command, state, at=1000, context={"broker_token_ref": "cred_abc123"})
        self.assertEqual(kind, "credential.issued")
        self.assertEqual(record["token_ref"], "cred_abc123")
        self.assertEqual(record["permissions"], ["github.repo.read"])
        self.assertEqual(record["expires_at_ms"], 1000 + 1800000)
        self.assertNotIn("token", record)  # secret never enters the projection
        self.assertNotIn("secret", record)

    def test_issue_rejects_unknown_permission_scope(self):
        """A permission outside the broker's known scope is rejected."""
        state = self._state()
        command = self._command("credential.request", {"permissions": ["aws.s3.write"], "ttl_ms": 1000},
                                actor="a-1")
        with self.assertRaises(PolicyViolation) as ctx:
            credentials.issue(command, state, at=1000, context={"broker_token_ref": "cred_abc"})
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")

    def test_revoke_marks_revoked_and_preserves_history(self):
        previous = {"id": "cred-1", "revision": 1, "token_ref": "cred_old", "revoked": False}
        state = self._state(credential=previous)
        command = self._command("credential.revoke", {}, actor="human-owner", target="cred-1", revision=1)
        kind, record = credentials.revoke(command, previous, state, at=2000, context={})
        self.assertEqual(kind, "credential.revoked")
        self.assertTrue(record["revoked"])
        # No token body materializes during revocation.
        self.assertNotIn("token", record)
        self.assertNotIn("secret", record)

    def test_evaluate_dispatches_credential_aggregate(self):
        """evaluate() routes credential aggregates to the credential transitions."""
        from aetp.governance.projection import evaluate
        state = self._state()
        command = self._command("credential.request", {
            "permissions": ["github.repo.read"], "ttl_ms": 1000}, actor="a-1")
        kind, record = evaluate(command, state, 500,
                                {"idempotency_key": "cmd-1", "broker_token_ref": "credref_abc"})
        self.assertEqual(kind, "credential.issued")
        self.assertNotIn("token", record)
        self.assertEqual(record["token_ref"], "credref_abc")

    def test_non_owner_agent_cannot_revoke_another_agents_credential(self):
        """Only the owning Agent or a human may revoke (see revoke docstring)."""
        previous = {"id": "cred-1", "revision": 1, "token_ref": "cred_a",
                    "revoked": False, "owner_id": "a-1"}
        state = self._state(credential=previous)
        state["agent:a-2"] = {"id": "a-2", "project_id": "p-1", "status": "available"}
        state["project:p-1"]["governance"]["versions"]["gov-1"]["policy"]["subjects"]["a-2"] = {
            "type": "agent", "roles": ["engineer"]}
        command = self._command("credential.revoke", {}, actor="a-2", target="cred-1", revision=1)
        with self.assertRaises(PolicyViolation) as ctx:
            credentials.revoke(command, previous, state, at=2000, context={})
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")

    def test_owning_agent_can_revoke_its_own_credential(self):
        previous = {"id": "cred-1", "revision": 1, "token_ref": "cred_a",
                    "revoked": False, "owner_id": "a-1"}
        state = self._state(credential=previous)
        command = self._command("credential.revoke", {}, actor="a-1", target="cred-1", revision=1)
        kind, record = credentials.revoke(command, previous, state, at=2000, context={})
        self.assertEqual(kind, "credential.revoked")
        self.assertTrue(record["revoked"])


if __name__ == "__main__":
    unittest.main()
