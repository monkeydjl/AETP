"""Unit tests for MCPClientAdapter, LocalMemoryMCPServer, and governance boundaries."""

import hashlib
import json
import unittest

from aetp.runtime.adapters import AdapterSecurityError
from aetp.runtime.mcp import LocalMemoryMCPServer, MCPClientAdapter


class StaticResponseMCPServer:
    """Returns a fixed malformed JSON-RPC response for adapter boundary tests."""
    def __init__(self, response):
        self.response = response
        self.requests = []

    def handle_request(self, request):
        self.requests.append(request)
        return self.response


class MCPAdapterTests(unittest.TestCase):
    def setUp(self):
        self.server = LocalMemoryMCPServer()
        self.adapter = MCPClientAdapter(self.server, high_risk_tools={"deploy_artifact"})
        self.session_context = {
            "task_id": "task-mcp-1",
            "actor_id": "agent-mcp-worker",
            "lease_epoch": 2,
        }

    def test_malformed_json_rpc_responses_fail_closed(self):
        """Wrong version/id and invalid result/error envelopes never become success."""
        malformed_responses = [
            {"jsonrpc": "1.0", "id": 1, "result": {"tools": []}},
            {"jsonrpc": "2.0", "id": True, "result": {"tools": []}},
            {"jsonrpc": "2.0", "id": 999, "result": {"tools": []}},
            {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}, "error": {"code": -1, "message": "bad"}},
            {"jsonrpc": "2.0", "id": 1},
        ]
        for response in malformed_responses:
            with self.subTest(response=response):
                server = StaticResponseMCPServer(response)
                adapter = MCPClientAdapter(server)
                with self.assertRaises(AdapterSecurityError) as ctx:
                    adapter.list_tools()
                self.assertEqual(ctx.exception.code, "MCP_INVALID_RESPONSE")

    def test_malformed_json_rpc_tool_response_is_not_reported_as_success(self):
        """A call_tool response with a mismatched JSON-RPC id fails closed."""
        server = StaticResponseMCPServer({
            "jsonrpc": "2.0",
            "id": 999,
            "result": {"content": [{"type": "text", "text": "forged"}]},
        })
        adapter = MCPClientAdapter(server)
        with self.assertRaises(AdapterSecurityError) as ctx:
            adapter.call_tool(
                self.session_context,
                "fetch_context",
                {"doc_id": "architecture-spec"},
                authorization_context={"authenticated_actor_id": "agent-mcp-worker", "lease_epoch": 2},
            )
        self.assertEqual(ctx.exception.code, "MCP_INVALID_RESPONSE")
        self.assertEqual(len(server.requests), 1)

    def test_tools_and_resources_discovery(self):
        """MCP tools/list and resources/list discovery."""
        tools = self.adapter.list_tools()
        self.assertEqual(len(tools), 2)
        tool_names = {t["name"] for t in tools}
        self.assertIn("fetch_context", tool_names)
        self.assertIn("deploy_artifact", tool_names)

        resources = self.adapter.list_resources()
        self.assertEqual(len(resources), 1)
        self.assertEqual(resources[0]["uri"], "repo://main/config")

        content = self.adapter.read_resource("repo://main/config")
        self.assertIn("contents", content)
        manifest = json.loads(content["contents"][0]["content"])
        self.assertEqual(manifest["env"], "production")

    def test_low_risk_tool_call_success(self):
        """Low risk MCP tool call executes without approval token."""
        res = self.adapter.call_tool(
            self.session_context,
            "fetch_context",
            {"doc_id": "architecture-spec"},
            authorization_context={"authenticated_actor_id": "agent-mcp-worker", "lease_epoch": 2},
        )
        self.assertEqual(res["status"], "success")
        self.assertIn("Context for architecture-spec", res["result"]["content"][0]["text"])

    def test_high_risk_tool_requires_approval(self):
        """High risk MCP tool without approval_id is blocked."""
        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.call_tool(
                self.session_context,
                "deploy_artifact",
                {"target": "production-cluster"},
                authorization_context={"authenticated_actor_id": "agent-mcp-worker", "lease_epoch": 2},
            )
        self.assertEqual(ctx.exception.code, "PRE_TOOL_UNAUTHORIZED")

    def test_high_risk_tool_authorized_success(self):
        """High risk MCP tool with valid approval token succeeds."""
        auth_ctx = {
            "authenticated_actor_id": "agent-mcp-worker",
            "lease_epoch": 2,
            "approval_id": "app-mcp-99",
        }
        res = self.adapter.call_tool(
            self.session_context,
            "deploy_artifact",
            {"target": "production-cluster"},
            authorization_context=auth_ctx,
        )
        self.assertEqual(res["status"], "success")
        self.assertIn("Deployed to production-cluster", res["result"]["content"][0]["text"])

    def test_actor_mismatch_blocked_before_json_rpc_dispatch(self):
        """Mismatched authenticated actor is blocked before MCP Server sees any request."""
        calls = []
        original_handle = self.server.handle_request

        def counting_handle(request):
            calls.append(request)
            return original_handle(request)

        self.server.handle_request = counting_handle
        auth_ctx = {
            "authenticated_actor_id": "malicious-intruder",
            "lease_epoch": 2,
            "approval_id": "app-mcp-99",
        }
        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.call_tool(
                self.session_context,
                "deploy_artifact",
                {"target": "production-cluster"},
                authorization_context=auth_ctx,
            )
        self.assertEqual(ctx.exception.code, "ACTOR_MISMATCH")
        self.assertEqual(calls, [], "unauthorized request leaked to MCP Server")

    def test_missing_approval_blocked_before_json_rpc_dispatch(self):
        """High-risk call with no approval is intercepted before Server dispatch."""
        calls = []
        original_handle = self.server.handle_request

        def counting_handle(request):
            calls.append(request)
            return original_handle(request)

        self.server.handle_request = counting_handle
        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.call_tool(
                self.session_context,
                "deploy_artifact",
                {"target": "production-cluster"},
                authorization_context={"authenticated_actor_id": "agent-mcp-worker", "lease_epoch": 2},
            )
        self.assertEqual(ctx.exception.code, "PRE_TOOL_UNAUTHORIZED")
        self.assertEqual(calls, [], "unapproved request leaked to MCP Server")

    def test_missing_authenticated_actor_rejected_before_json_rpc_dispatch(self):
        """A bound session requires an authenticated actor, even for low-risk tools."""
        calls = []
        original_handle = self.server.handle_request

        def counting_handle(request):
            calls.append(request)
            return original_handle(request)

        self.server.handle_request = counting_handle
        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.call_tool(
                self.session_context,
                "fetch_context",
                {"doc_id": "architecture-spec"},
                authorization_context={"lease_epoch": 2},
            )
        self.assertEqual(ctx.exception.code, "AUTHENTICATED_ACTOR_REQUIRED")
        self.assertEqual(calls, [], "request with missing actor leaked to MCP Server")

    def test_missing_lease_epoch_rejected_before_json_rpc_dispatch(self):
        """A leased session requires an epoch, even when the authenticated actor matches."""
        calls = []
        original_handle = self.server.handle_request

        def counting_handle(request):
            calls.append(request)
            return original_handle(request)

        self.server.handle_request = counting_handle
        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.call_tool(
                self.session_context,
                "fetch_context",
                {"doc_id": "architecture-spec"},
                authorization_context={"authenticated_actor_id": "agent-mcp-worker"},
            )
        self.assertEqual(ctx.exception.code, "LEASE_EPOCH_REQUIRED")
        self.assertEqual(calls, [], "request with missing lease epoch leaked to MCP Server")

    def test_lease_epoch_mismatch_blocked(self):
        """Stale lease epoch is blocked before JSON-RPC dispatch."""
        auth_ctx = {
            "authenticated_actor_id": "agent-mcp-worker",
            "lease_epoch": 1,  # Stale, session is epoch 2
            "approval_id": "app-mcp-99",
        }
        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.call_tool(
                self.session_context,
                "deploy_artifact",
                {"target": "production-cluster"},
                authorization_context=auth_ctx,
            )
        self.assertEqual(ctx.exception.code, "LEASE_EXPIRED")

    def test_tampered_arguments_blocked(self):
        """Tampering with approved arguments is blocked by digest check."""
        args = {"target": "production-cluster"}
        expected_digest = "sha256:" + hashlib.sha256(
            json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        auth_ctx = {
            "authenticated_actor_id": "agent-mcp-worker",
            "lease_epoch": 2,
            "approval_id": "app-mcp-99",
            "expected_arguments_digest": expected_digest,
        }

        # Submit tampered arguments
        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.call_tool(
                self.session_context,
                "deploy_artifact",
                {"target": "tampered-destination"},
                authorization_context=auth_ctx,
            )
        self.assertEqual(ctx.exception.code, "APPROVAL_STALE")

    def test_pause_barrier_blocks_mcp_call(self):
        """PAUSED state completely halts MCP tool dispatch."""
        self.adapter.pause()
        self.assertTrue(self.adapter.is_paused)

        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.call_tool(
                self.session_context,
                "fetch_context",
                {"doc_id": "test"},
                authorization_context={"authenticated_actor_id": "agent-mcp-worker", "lease_epoch": 2},
            )
        self.assertEqual(ctx.exception.code, "PROJECT_PAUSED")

        self.adapter.resume()
        self.assertFalse(self.adapter.is_paused)
        res = self.adapter.call_tool(
            self.session_context,
            "fetch_context",
            {"doc_id": "test"},
            authorization_context={"authenticated_actor_id": "agent-mcp-worker", "lease_epoch": 2},
        )
        self.assertEqual(res["status"], "success")
