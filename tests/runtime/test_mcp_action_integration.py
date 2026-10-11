"""MCP to existing Action/Event integration tests."""

import hashlib
import json
import unittest

from aetp.core.projection import Projection
from aetp.runtime.adapters import AdapterSecurityError
from aetp.runtime.mcp import LocalMemoryMCPServer, MCPClientAdapter
from aetp.runtime.mcp_policy import MCPToolRegistration, MCPToolRegistry


class CountingMCPServer(LocalMemoryMCPServer):
    def __init__(self):
        super().__init__(server_id="trusted-server")
        self.requests = []

    def handle_request(self, request):
        self.requests.append(request)
        return super().handle_request(request)


class MCPActionLifecycleTests(unittest.TestCase):
    """End-to-end: a registered mcp.call Action uses the existing Action chain."""

    def setUp(self):
        from tests.m1.execution_support import ExecutionCase

        self.case = ExecutionCase("runTest")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.store = self.case.store
        self.server = CountingMCPServer()
        registry = MCPToolRegistry()
        for tool_name in ("fetch_context", "deploy_artifact"):
            registry.register(MCPToolRegistration(
                server_id="trusted-server",
                tool_name=tool_name,
                risk_level="low",
                schema_digest=self.server.declared_tool_schema_digest(tool_name),
            ))
        self.adapter = MCPClientAdapter(self.server, registry=registry)
        self.case.runtime.mcp_provider = self.adapter
        self.case.claim()
        self.case.start()

    def _mcp_request(self, tool_name="fetch_context", tool_arguments=None):
        return self.case.command("tool.request", "t-1", {
            **self.case.fence(),
            "operation": "mcp.call",
            "arguments": {"server_id": "trusted-server", "tool_name": tool_name,
                          "tool_arguments": tool_arguments or {"doc_id": "architecture"}},
        })

    def test_registered_call_persists_action_events_and_replays(self):
        result = self.case.accept(self._mcp_request(), session=self.case.session)
        state = self.case.state()
        action = next(value for key, value in state.items() if key.startswith("action:"))
        dispatched = self.case.dispatch(action)
        self.assertEqual(dispatched["status"], "completed")
        self.assertEqual(len(self.server.requests), 1)
        self.assertEqual(self.server.requests[0]["method"], "tools/call")

        event_types = [event.type for event in self.store.read_events("p-1")]
        self.assertIn("tool.requested", event_types)
        self.assertIn("tool.invoked", event_types)
        self.assertIn("tool.completed", event_types)
        self.assertEqual(Projection.rebuild(self.store.read_events("p-1")), self.store.read_projection("p-1"))

    def test_mcp_call_does_not_need_document_content_envelope(self):
        """The generic channel must complete without any document content field."""
        self.case.accept(self._mcp_request(tool_arguments={}), session=self.case.session)
        action = next(value for key, value in self.case.state().items() if key.startswith("action:"))
        self.assertNotIn("content", action["arguments"])
        dispatched = self.case.dispatch(action)
        self.assertEqual(dispatched["status"], "completed")


    def test_pause_blocks_mcp_dispatch_before_any_server_request(self):
        """PAUSED Project rejects the tool channel without contacting MCP."""
        from aetp.collaboration.policy import PolicyViolation

        self.case.accept(self._mcp_request(), session=self.case.session)
        action = next(value for key, value in self.case.state().items() if key.startswith("action:"))
        self.case.accept(self.case.command("project.pause", "p-1", {}, actor="bootstrap"))
        with self.assertRaises(PolicyViolation):
            self.case.dispatch(action)
        self.assertEqual(self.server.requests, [])
        self.assertEqual(self.case.state()[f"action:{action['id']}"]["status"], "pending")

    def test_server_identity_mismatch_is_clean_policy_rejection_not_unknown(self):
        """A mismatched server identity must be rejected before dispatch, not logged as UNKNOWN."""
        from aetp.collaboration.policy import PolicyViolation

        registry = MCPToolRegistry()
        registry.register(MCPToolRegistration(
            server_id="trusted-server",
            tool_name="fetch_context",
            risk_level="low",
            schema_digest=self.server.declared_tool_schema_digest("fetch_context"),
        ))
        self.adapter.registry = registry
        # Server transport claims a different identity than the trusted registration.
        self.adapter.server = CountingMCPServer()  # server_id defaults to "trusted-server"
        self.adapter.server.server_id = "evil-server"

        self.case.accept(self._mcp_request(), session=self.case.session)
        action = next(value for key, value in self.case.state().items() if key.startswith("action:"))
        with self.assertRaises(PolicyViolation) as ctx:
            self.case.dispatch(action)
        self.assertEqual(ctx.exception.code, "MCP_SERVER_MISMATCH")
        self.assertEqual(self.server.requests, [])
        self.assertEqual(self.case.state()[f"action:{action['id']}"]["status"], "pending")

    def test_reconcile_routes_mcp_action_to_mcp_provider_not_workspace(self):
        """reconcile of an mcp.call Action must query the MCP provider, not workspace."""
        class BrokenMCPServer(CountingMCPServer):
            def handle_request(self, request):
                self.requests.append(request)
                raise ConnectionError("mcp transport lost after dispatch")

        broken = BrokenMCPServer()
        registry = MCPToolRegistry()
        registry.register(MCPToolRegistration(
            server_id="trusted-server", tool_name="fetch_context", risk_level="low",
            schema_digest=broken.declared_tool_schema_digest("fetch_context")))
        self.adapter.registry = registry
        self.adapter.server = broken
        self.case.runtime.mcp_provider = self.adapter

        self.case.accept(self._mcp_request(), session=self.case.session)
        action = next(value for key, value in self.case.state().items() if key.startswith("action:"))
        first = self.case.dispatch(action)
        self.assertEqual(first["status"], "unknown")

        workspace_queries = []
        mcp_queries = []
        real_workspace_query = self.case.service.runtime.workspace.query
        real_mcp_query = self.adapter.query

        def spy_workspace_query(a):
            workspace_queries.append(a)
            return real_workspace_query(a)

        def spy_mcp_query(a):
            mcp_queries.append(a)
            return real_mcp_query(a)

        self.case.service.runtime.workspace.query = spy_workspace_query
        self.adapter.query = spy_mcp_query
        try:
            reconciled = self.case.service.reconcile("p-1", action["id"])
        finally:
            self.case.service.runtime.workspace.query = real_workspace_query
            self.adapter.query = real_mcp_query

        self.assertEqual(reconciled["status"], "unknown")
        self.assertEqual([a["id"] for a in mcp_queries], [action["id"]],
                         "reconcile did not route to the MCP provider")
        self.assertEqual(workspace_queries, [], "reconcile wrongly used the document workspace provider for an mcp.call")

    def test_high_risk_mcp_tool_without_authorization_is_rejected(self):
        """A high-risk registration must not run without an approval binding."""
        from aetp.collaboration.policy import PolicyViolation

        high = MCPToolRegistry()
        high.register(MCPToolRegistration(
            server_id="trusted-server", tool_name="deploy_artifact", risk_level="high",
            schema_digest=self.server.declared_tool_schema_digest("deploy_artifact")))
        self.adapter.registry = high
        self.case.accept(self._mcp_request("deploy_artifact", {"target": "prod"}), session=self.case.session)
        action = next(value for key, value in self.case.state().items() if key.startswith("action:"))
        with self.assertRaises(PolicyViolation):
            self.case.dispatch(action)
        self.assertEqual(self.server.requests, [])

    def test_uncertain_mcp_outcome_stays_unknown_and_reconciles_without_second_call(self):
        """Transport uncertainty must not be reported as success or retried."""
        class BrokenMCPServer(CountingMCPServer):
            def handle_request(self, request):
                self.requests.append(request)
                raise ConnectionError("mcp transport lost after dispatch")

        broken = BrokenMCPServer()
        registry = MCPToolRegistry()
        registry.register(MCPToolRegistration(
            server_id="trusted-server", tool_name="fetch_context", risk_level="low",
            schema_digest=broken.declared_tool_schema_digest("fetch_context")))
        self.adapter.registry = registry
        self.adapter.server = broken
        self.case.runtime.mcp_provider = self.adapter

        self.case.accept(self._mcp_request(), session=self.case.session)
        action = next(value for key, value in self.case.state().items() if key.startswith("action:"))
        first = self.case.dispatch(action)
        self.assertEqual(first["status"], "unknown")
        self.assertEqual(len(broken.requests), 1)

        reconciled = self.case.service.reconcile("p-1", action["id"])
        self.assertEqual(reconciled["id"], action["id"])
        self.assertEqual(reconciled["status"], "unknown")
        # A destructive tool call is never replayed by reconciliation.
        self.assertEqual(len(broken.requests), 1)

    def test_replay_never_contacts_the_mcp_server(self):
        """Pure Replay rebuilds from Events without executing the tool channel."""
        self.case.accept(self._mcp_request(), session=self.case.session)
        action = next(value for key, value in self.case.state().items() if key.startswith("action:"))
        self.case.dispatch(action)
        requests_after_dispatch = len(self.server.requests)

        rebuilt = Projection.rebuild(self.store.read_events("p-1"))
        self.assertEqual(rebuilt, self.store.read_projection("p-1"))
        self.assertEqual(len(self.server.requests), requests_after_dispatch)


class MCPActionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.server = CountingMCPServer()
        self.registry = MCPToolRegistry()
        self.adapter = MCPClientAdapter(self.server, registry=self.registry)

    def test_unregistered_tool_rejected_before_server_dispatch(self):
        """Default deny: unknown server/tool never reaches MCP transport."""
        from aetp.collaboration.policy import PolicyViolation

        with self.assertRaises(PolicyViolation) as ctx:
            self.adapter.call_registered_tool(
                {"actor_id": "a-1", "lease_epoch": 1},
                "trusted-server",
                "fetch_context",
                {"doc_id": "architecture"},
                authorization_context={"authenticated_actor_id": "a-1", "lease_epoch": 1},
            )
        self.assertEqual(ctx.exception.code, "MCP_TOOL_NOT_REGISTERED")
        self.assertEqual(self.server.requests, [])

    def test_mcp_call_operation_normalizes_without_document_keys(self):
        """Action contract: mcp.call is a first-class operation, not a document write."""
        from aetp.runtime.records import normalize_arguments

        task = {"id": "t-1", "current_binding_id": "b-1", "bindings": {"b-1": {}}}
        normalized = normalize_arguments(
            "mcp.call",
            {"server_id": "trusted-server", "tool_name": "fetch_context", "tool_arguments": {"doc_id": "x"}},
            task,
            {},
        )
        self.assertEqual(normalized["server_id"], "trusted-server")
        self.assertEqual(normalized["tool_name"], "fetch_context")
        self.assertEqual(normalized["tool_arguments"], {"doc_id": "x"})

    def test_mcp_call_rejects_document_keys_and_path_scope(self):
        """The generic tool channel rejects document top-level keys and path scope."""
        from aetp.collaboration.policy import PolicyViolation
        from aetp.runtime.records import normalize_arguments

        task = {"id": "t-1", "current_binding_id": "b-1", "bindings": {"b-1": {}}}
        for payload in (
            # Document-style top-level key must not be borrowed by the tool channel.
            {"content": "x"},
            {"server_id": "s", "tool_name": "t", "tool_arguments": {}, "content": "x"},
            # Missing required tool identity.
            {"tool_name": "t", "tool_arguments": {}},
            # Path scope cannot be smuggled inside tool arguments.
            {"server_id": "s", "tool_name": "t", "tool_arguments": {"path": "secret.txt"}},
            {"server_id": "s", "tool_name": "t", "tool_arguments": {"workspace": "other"}},
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(PolicyViolation):
                    normalize_arguments("mcp.call", payload, task, {})

    def test_mcp_call_allows_tool_owned_arguments(self):
        """Tool-owned arguments such as an empty set or a 'content' field are allowed."""
        from aetp.runtime.records import normalize_arguments

        task = {"id": "t-1", "current_binding_id": "b-1", "bindings": {"b-1": {}}}
        empty = normalize_arguments(
            "mcp.call", {"server_id": "s", "tool_name": "t", "tool_arguments": {}}, task, {})
        self.assertEqual(empty["tool_arguments"], {})
        with_content = normalize_arguments(
            "mcp.call", {"server_id": "s", "tool_name": "t", "tool_arguments": {"content": "x"}}, task, {})
        self.assertEqual(with_content["tool_arguments"], {"content": "x"})

    def test_document_operation_still_rejects_mcp_payload(self):
        """Document operations keep their fixed allowlist; mcp keys are not borrowed."""
        from aetp.collaboration.policy import PolicyViolation
        from aetp.runtime.records import normalize_arguments

        task = {"id": "t-1", "current_binding_id": "b-1", "bindings": {"b-1": {}}}
        with self.assertRaises(PolicyViolation):
            normalize_arguments(
                "document.write",
                {"server_id": "s", "tool_name": "t", "tool_arguments": {}},
                task,
                {},
            )

    def test_registered_tool_requires_matching_schema_digest(self):
        """A trusted registration must match the server-declared schema digest."""
        self.registry.register(MCPToolRegistration(
            server_id="trusted-server",
            tool_name="fetch_context",
            risk_level="low",
            schema_digest="sha256:expected-schema",
        ))
        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.call_registered_tool(
                {"actor_id": "a-1", "lease_epoch": 1},
                "trusted-server",
                "fetch_context",
                {"doc_id": "architecture"},
                authorization_context={"authenticated_actor_id": "a-1", "lease_epoch": 1},
            )
        self.assertEqual(ctx.exception.code, "MCP_SCHEMA_DRIFT")
        self.assertEqual(self.server.requests, [])
