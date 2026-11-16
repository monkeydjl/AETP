"""End-to-end: every permission the issuers admit must be consumable by a real Action.

Spec 14.3 / INV-012: the Broker issues short-term scoped credentials. The point
of a scope is that a consuming Action can present it. The Runtime's tool channel
(`mcp.call`) carries `required_permission`. If the issue-time whitelist admits a
permission the tool channel can never require, that entry is decorative: an
Agent that requested it holds a credential it can never use.

This closes a coverage hole found while reviewing the credential chain. The
command path validates requests against SCOPE_WHITELIST, the broker path accepts
any non-empty permission tuple, and the only end-to-end tests exercised a single
permission string (`github.repo.read`). A whitelist entry that no channel
accepts, or a broker that drops an entry on the way through, would have gone
unnoticed.

A green test here means the whole chain agrees: whitelist entry -> issued
credential -> broker resolution -> action dispatch -> provider call.
"""

import unittest

from aetp.governance.credential_broker import CredentialBroker
from aetp.governance.credentials import SCOPE_WHITELIST
from aetp.runtime.mcp import LocalMemoryMCPServer, MCPClientAdapter
from aetp.runtime.mcp_policy import MCPToolRegistration, MCPToolRegistry
from tests.m1 import execution_support


class CountingServer(LocalMemoryMCPServer):
    def __init__(self):
        super().__init__(server_id="scope-coverage-server")
        self.requests = []

    def handle_request(self, request):
        self.requests.append(request)
        return super().handle_request(request)


class CredentialScopeCoverageTests(unittest.TestCase):
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

    def _action(self, token_ref, permission):
        return self.case.request(operation="mcp.call", arguments={
            "server_id": self.server.server_id,
            "tool_name": "fetch_context",
            "tool_arguments": {"doc_id": "architecture"},
            "credential_token_ref": token_ref,
            "required_permission": permission,
        })

    def test_every_whitelisted_permission_is_consumable_by_a_real_action(self):
        """No whitelist entry may be decorative.

        Each permission is issued to the Broker and presented to a real Action.
        A permission that cannot be consumed end to end is a credentialed dead
        end: the Agent was told it holds a capability it can never exercise.
        """
        self.assertTrue(SCOPE_WHITELIST, "an empty whitelist would make this vacuous")

        for permission in sorted(SCOPE_WHITELIST):
            with self.subTest(permission=permission):
                before = len(self.server.requests)
                credential = self.broker.issue(
                    "a-1", permissions=[permission],
                    issued_at=self.case.clock(), expires_in_ms=30_000)
                self.assertEqual(credential["permissions"], [permission],
                                 "the broker altered the granted scope")
                action = self._action(credential["token_ref"], permission)
                self.assertEqual(self.case.dispatch(action)["status"], "completed",
                                 f"{permission} was issued but cannot be consumed")
                self.assertEqual(len(self.server.requests), before + 1,
                                 "the provider was not reached for a consumable scope")

    def test_a_permission_outside_the_whitelist_is_refused_by_the_broker_consumer(self):
        """The consuming side must not widen what the issuing side refused.

        This is the counterpart to the command-path check: the broker is the
        last line, and it must reject a permission that was never granted even
        when the Action presents a valid token.
        """
        from aetp.collaboration.policy import PolicyViolation

        credential = self.broker.issue(
            "a-1", permissions=["github.repo.read"],
            issued_at=self.case.clock(), expires_in_ms=30_000)
        action = self._action(credential["token_ref"], "github.repo.write")
        with self.assertRaises(PolicyViolation) as ctx:
            self.case.dispatch(action)
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")
        self.assertEqual(self.server.requests, [], "a refused scope must not reach the provider")


if __name__ == "__main__":
    unittest.main()
