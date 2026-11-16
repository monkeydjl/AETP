"""Credential checks through real Command -> Event -> Projection -> dispatch.

The local MCP server is an effect probe, not a replacement for authorization.
No test overrides ActionBroker or edits durable state directly.
"""

import json
import unittest

from aetp.collaboration.policy import PolicyViolation
from aetp.core.projection import Projection
from aetp.governance.credential_broker import CredentialBroker
from aetp.runtime.mcp import LocalMemoryMCPServer, MCPClientAdapter
from aetp.runtime.mcp_policy import MCPToolRegistration, MCPToolRegistry
from tests.m1 import execution_support


class CountingServer(LocalMemoryMCPServer):
    def __init__(self):
        super().__init__(server_id="credential-test-server")
        self.requests = []

    def handle_request(self, request):
        self.requests.append(request)
        return super().handle_request(request)


class CredentialIngestionTests(unittest.TestCase):
    def setUp(self):
        self.case = execution_support.ExecutionCase("runTest")
        self.addCleanup(self.case.doCleanups)
        self.case.setUp()
        self.broker = CredentialBroker()
        self.case.runtime.credential_broker = self.broker
        self.server = CountingServer()
        registry = MCPToolRegistry()
        registry.register(MCPToolRegistration(
            server_id=self.server.server_id,
            tool_name="fetch_context",
            risk_level="low",
            schema_digest=self.server.declared_tool_schema_digest("fetch_context"),
        ))
        self.case.runtime.mcp_provider = MCPClientAdapter(self.server, registry=registry)
        self.case.claim()
        self.case.start()

    def _issue(self, *, permissions=("github.repo.read",), agent="a-1"):
        return self.broker.issue(agent, permissions=permissions,
                                 issued_at=self.case.clock(), expires_in_ms=30_000)

    def _request(self, token_ref, permission="github.repo.read"):
        return self.case.request(operation="mcp.call", arguments={
            "server_id": self.server.server_id,
            "tool_name": "fetch_context",
            "tool_arguments": {"doc_id": "architecture"},
            "credential_token_ref": token_ref,
            "required_permission": permission,
        })

    def _assert_dispatch_rejected(self, action, code):
        events_before = self.case.store.read_events("p-1")
        with self.assertRaises(PolicyViolation) as ctx:
            self.case.dispatch(action)
        self.assertEqual(ctx.exception.code, code)
        self.assertEqual(self.server.requests, [])
        self.assertEqual(self.case.state()[f"action:{action['id']}"]["status"], "pending")
        self.assertEqual(self.case.store.read_events("p-1"), events_before)
        self.assertEqual(Projection.rebuild(events_before), self.case.state())

    def test_valid_scope_dispatches_once_and_replays_without_secrets(self):
        credential = self._issue()
        action = self._request(credential["token_ref"])
        self.assertEqual(action["arguments"]["credential_token_ref"], credential["token_ref"])
        self.assertEqual(action["arguments"]["required_permission"], "github.repo.read")
        self.assertEqual(self.case.dispatch(action)["status"], "completed")
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(self.server.requests[0]["params"]["arguments"], {"doc_id": "architecture"})
        events = self.case.store.read_events("p-1")
        self.assertNotIn(credential["token"], json.dumps([e.to_dict() for e in events]))
        self.assertEqual(Projection.rebuild(events), self.case.state())
        # A terminal Action never reruns; a Projection rebuild never dispatches.
        self.assertEqual(len(self.server.requests), 1, "pure replay must not call the Provider")
        self.assertEqual(self.case.dispatch(action)["status"], "completed")
        self.assertEqual(len(self.server.requests), 1, "completed Action must not run twice")

    def test_out_of_scope_rejected_before_provider_call(self):
        credential = self._issue()
        action = self._request(credential["token_ref"], "github.repo.write")
        self._assert_dispatch_rejected(action, "PERMISSION_DENIED")

    def test_missing_broker_rejected_before_provider_call(self):
        credential = self._issue()
        action = self._request(credential["token_ref"])
        self.case.runtime.credential_broker = None
        self._assert_dispatch_rejected(action, "CREDENTIAL_UNAVAILABLE")

    def test_expired_after_request_rejected_before_provider_call(self):
        credential = self._issue()
        action = self._request(credential["token_ref"])
        self.case.clock.advance(30_000)
        self._assert_dispatch_rejected(action, "CREDENTIAL_EXPIRED")

    def test_revoked_after_request_rejected_before_provider_call(self):
        credential = self._issue()
        action = self._request(credential["token_ref"])
        self.broker.revoke_by_ref(credential["token_ref"], actor="a-1")
        self._assert_dispatch_rejected(action, "CREDENTIAL_REVOKED")

    def test_unknown_ref_rejected_before_provider_call(self):
        action = self._request("credref_unknown")
        self._assert_dispatch_rejected(action, "CREDENTIAL_UNKNOWN")

    def test_document_action_preserves_credential_metadata(self):
        credential = self._issue()
        action = self.case.request(arguments={
            "content": "Overview\nFailure case\n",
            "credential_token_ref": credential["token_ref"],
            "required_permission": "github.repo.read",
        })
        self.assertEqual(action["arguments"]["credential_token_ref"], credential["token_ref"])
        self.assertEqual(action["arguments"]["required_permission"], "github.repo.read")
        self.assertEqual(self.case.dispatch(action)["status"], "completed")
        self.assertEqual(Projection.rebuild(self.case.store.read_events("p-1")), self.case.state())

    def test_malformed_credential_metadata_rejected_at_command_boundary(self):
        credential = self._issue()
        base = {"server_id": self.server.server_id, "tool_name": "fetch_context",
                "tool_arguments": {"doc_id": "architecture"}}
        for metadata in (
            {"credential_token_ref": credential["token_ref"]},
            {"required_permission": "github.repo.read"},
            {"credential_token_ref": None, "required_permission": "github.repo.read"},
            {"credential_token_ref": credential["token_ref"], "required_permission": ""},
        ):
            with self.subTest(metadata=metadata):
                self.case.reject(self.case.command("tool.request", "t-1", {
                    **self.case.fence(), "operation": "mcp.call", "arguments": {**base, **metadata},
                }), "INVALID_PAYLOAD", session=self.case.session)
        self.assertEqual(self.server.requests, [])
        self.assertFalse(any(key.startswith("action:") for key in self.case.state()))


if __name__ == "__main__":
    unittest.main()
