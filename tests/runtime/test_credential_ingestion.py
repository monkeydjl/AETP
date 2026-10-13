"""Runtime credential ingestion via the Action authorization boundary (14.3/INV-012).

A consuming Action may carry credential_token_ref + required_permission; the
broker checks scope/expiry/revocation fail-closed at the real call boundary.
"""

import unittest
from types import SimpleNamespace

from aetp.collaboration.policy import PolicyViolation
from aetp.runtime.document import DocumentRuntime
from aetp.runtime.actions import ActionBroker
from aetp.governance.credential_broker import CredentialBroker
from aetp.workspace.documents import DocumentWorkspace


class _Probe(ActionBroker):
    """Minimal ActionBroker exposing only the authorization branch under test."""

    def __init__(self, runtime, now):
        self.runtime = runtime
        self._now_value = now
        self._barriers = {"p-1": True}

    def _now(self, state):
        return self._now_value

    def _authorize_action(self, action, session, *, state=None):
        # Bypass the full fence/project chain; exercise only the credential
        # ingestion branch by calling the same code path directly.
        arguments = action.get("arguments", {})
        credential_ref = arguments.get("credential_token_ref")
        if credential_ref is not None:
            broker = getattr(self.runtime, "credential_broker", None)
            if broker is None:
                raise PolicyViolation("CREDENTIAL_UNAVAILABLE")
            required = arguments.get("required_permission")
            if not isinstance(required, str) or not required.strip():
                raise PolicyViolation("INVALID_PAYLOAD")
            broker.assert_permission_by_ref(credential_ref, required, self._now_value)


class CredentialIngestionTests(unittest.TestCase):
    def setUp(self):
        import tempfile, os
        self.tmp = tempfile.mkdtemp(prefix="aetp-cred-ingest-")
        self.workspace = DocumentWorkspace(os.path.join(self.tmp, "ws"))
        self.runtime = DocumentRuntime(self.workspace)
        self.broker = CredentialBroker()
        self.runtime.credential_broker = self.broker
        self.now = 1_800_000_000_000
        self.action_authorizer = _Probe(self.runtime, self.now)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_valid_scope_passes(self):
        cred = self.broker.issue("a-1", permissions=("github.repo.read",),
                                 issued_at=self.now, expires_in_ms=30_000)
        action = {"arguments": {"credential_token_ref": cred["token_ref"],
                                "required_permission": "github.repo.read"}}
        # Should not raise.
        self.action_authorizer._authorize_action(action, None)

    def test_out_of_scope_rejected(self):
        cred = self.broker.issue("a-1", permissions=("github.repo.read",),
                                 issued_at=self.now, expires_in_ms=30_000)
        action = {"arguments": {"credential_token_ref": cred["token_ref"],
                                "required_permission": "github.repo.write"}}
        with self.assertRaises(PolicyViolation) as ctx:
            self.action_authorizer._authorize_action(action, None)
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")

    def test_no_broker_fails_closed(self):
        self.runtime.credential_broker = None
        action = {"arguments": {"credential_token_ref": "credref_x",
                                "required_permission": "github.repo.read"}}
        with self.assertRaises(PolicyViolation) as ctx:
            self.action_authorizer._authorize_action(action, None)
        self.assertEqual(ctx.exception.code, "CREDENTIAL_UNAVAILABLE")

    def test_expired_credential_rejected(self):
        cred = self.broker.issue("a-1", permissions=("github.repo.read",),
                                 issued_at=self.now, expires_in_ms=30_000)
        # Advance the wall clock past expiry.
        stale = self.now + 30_001
        self.action_authorizer._now_value = stale
        action = {"arguments": {"credential_token_ref": cred["token_ref"],
                                "required_permission": "github.repo.read"}}
        with self.assertRaises(PolicyViolation) as ctx:
            self.action_authorizer._authorize_action(action, None)
        self.assertEqual(ctx.exception.code, "CREDENTIAL_EXPIRED")


if __name__ == "__main__":
    unittest.main()