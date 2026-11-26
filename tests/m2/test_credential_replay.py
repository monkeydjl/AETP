"""Deterministic replay of credential Events (spec 14.3 / INV-012).

A credential Event must reconstruct the exact same Projection record it was
scored from, with no re-minting and no token body materializing.
"""

import unittest

from aetp.collaboration.policy import canonical_json
from aetp.domain.models import Command, Event
from aetp.governance import credentials
from aetp.governance.projection import reduce_record


def _state():
    return {
        "project:p-1": {
            "id": "p-1", "revision": 1, "status": "active",
            "governance": {
                "current_version": "gov-1",
                "versions": {"gov-1": {"policy": {"subjects": {
                    "a-1": {"type": "agent", "roles": ["engineer"]},
                    "human-owner": {"type": "human", "roles": ["human_owner"]},
                }}}},
            },
        },
        "agent:a-1": {"id": "a-1", "project_id": "p-1", "status": "available"},
    }


class CredentialReplayTests(unittest.TestCase):
    def test_credential_event_replays_to_same_record(self):
        """The issued record reduces deterministically from the event payload."""
        state = _state()
        command = Command("cred-cmd", "p-1", "a-1", "credential.request", "cred-1",
                          {"permissions": ["github.repo.read"], "ttl_ms": 1000},
                          0, "cred-cmd", "corr")
        context = {"idempotency_key": "cred-cmd", "broker_token_ref": "credref_deadbeef"}
        kind, expected = credentials.issue(command, state, at=1000, context=context)

        # Build the same governance envelope reduce_record expects.
        from aetp.governance.contracts import SCHEMA
        payload = {
            "governance_schema": SCHEMA, "actor_id": "a-1", "command_type": "credential.request",
            "command_payload": {"permissions": ["github.repo.read"], "ttl_ms": 1000},
            "expected_revision": 0, "observed_at_ms": 1000, "context": context,
            "record": expected, "continuations": [],
        }
        event = Event("e-1", "p-1", 1, "credential.issued", "credential", "cred-1",
                      1, "cred-cmd", "corr", payload)
        reduced = reduce_record(event, None, state)
        self.assertEqual(canonical_json(reduced), canonical_json(expected))
        self.assertNotIn("token", reduced)

    def test_revoke_event_replays_to_revoked_record(self):
        state = _state()
        previous = {"id": "cred-1", "project_id": "p-1", "revision": 1,
                    "token_ref": "credref_deadbeef", "permissions": ["github.repo.read"],
                    "issued_at_ms": 1000, "expires_at_ms": 2000, "revoked": False}
        state["credential:cred-1"] = previous
        command = Command("rev-cmd", "p-1", "human-owner", "credential.revoke", "cred-1",
                          {}, 1, "rev-cmd", "corr")
        kind, expected = credentials.revoke(command, previous, state, at=2000, context={})

        from aetp.governance.contracts import SCHEMA
        payload = {
            "governance_schema": SCHEMA, "actor_id": "human-owner", "command_type": "credential.revoke",
            "command_payload": {}, "expected_revision": 1, "observed_at_ms": 2000,
            "context": {"idempotency_key": "rev-cmd"}, "record": expected, "continuations": [],
        }
        event = Event("e-2", "p-1", 2, "credential.revoked", "credential", "cred-1",
                      2, "rev-cmd", "corr", payload)
        reduced = reduce_record(event, previous, state)
        self.assertTrue(reduced["revoked"])
        self.assertNotIn("token", reduced)
        self.assertNotIn("secret", reduced)


if __name__ == "__main__":
    unittest.main()
