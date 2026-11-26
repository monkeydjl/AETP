"""AETP Model Context Protocol (MCP) client adapter and governance boundary.

Specification source: Docs/AETP-设计方案.md §§2.1, 2.2, 13.9, INV-006, INV-013.
Encapsulates MCP JSON-RPC 2.0 communication with pre-tool governance verification,
ensuring all external MCP tool calls remain within AETP authority boundaries.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional, Set

from aetp.runtime.adapters import AdapterSecurityError
from aetp.runtime.mcp_policy import MCPToolRegistry


class MCPServerInterface:
    """Simulated or transport-backed MCP Server implementing JSON-RPC 2.0 methods."""

    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Process a JSON-RPC 2.0 request and return a response."""
        raise NotImplementedError

    def declared_tool_schema_digest(self, tool_name: str) -> str:
        """Locally declared input schema digest for a tool, without any wire request."""
        raise NotImplementedError


class LocalMemoryMCPServer(MCPServerInterface):
    """In-memory MCP Server fixture providing standard tools and resources."""

    def __init__(self, server_id: str = "mock-mcp-server"):
        self.server_id = server_id
        self._tools: Dict[str, Dict[str, Any]] = {
            "fetch_context": {
                "name": "fetch_context",
                "description": "Fetch project context document",
                "inputSchema": {"type": "object", "properties": {"doc_id": {"type": "string"}}},
                "risk_level": "low",
            },
            "deploy_artifact": {
                "name": "deploy_artifact",
                "description": "Deploy artifact to remote environment",
                "inputSchema": {"type": "object", "properties": {"target": {"type": "string"}}},
                "risk_level": "high",
            },
        }
        self._resources: Dict[str, Dict[str, Any]] = {
            "repo://main/config": {
                "uri": "repo://main/config",
                "name": "Configuration Manifest",
                "mimeType": "application/json",
                "content": json.dumps({"env": "production"}),
            }
        }

    def declared_tool_schema_digest(self, tool_name: str) -> str:
        tool = self._tools.get(tool_name)
        if tool is None:
            raise AdapterSecurityError("MCP_TOOL_NOT_REGISTERED", f"unknown declared tool {tool_name}")
        content = json.dumps(tool["inputSchema"], ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()

    def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params", {})

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": list(self._tools.values())},
            }
        elif method == "resources/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"resources": list(self._resources.values())},
            }
        elif method == "resources/read":
            uri = params.get("uri")
            if uri in self._resources:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"contents": [self._resources[uri]]},
                }
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32602, "message": f"Resource not found: {uri}"},
            }
        elif method == "tools/call":
            name = params.get("name")
            args = params.get("arguments", {})
            if name == "fetch_context":
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": f"Context for {args.get('doc_id')}"}]},
                }
            elif name == "deploy_artifact":
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": f"Deployed to {args.get('target')}"}]},
                }
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "error": {"code": -32601, "message": f"Tool not found: {name}"},
            }

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not supported: {method}"},
        }


class MCPClientAdapter:
    """AETP governed MCP Client Adapter (§2.1 / §13.9).

    Wraps external MCP connections with pre-tool authorization, actor/binding verification,
    and governance barriers before delegating JSON-RPC requests.
    """

    def __init__(
        self,
        server: MCPServerInterface,
        *,
        high_risk_tools: Optional[Set[str]] = None,
        registry: Optional[MCPToolRegistry] = None,
    ):
        self.server = server
        self.high_risk_tools = high_risk_tools or {"deploy_artifact", "delete_resource"}
        self.registry = registry or MCPToolRegistry()
        self._paused = False
        self._request_counter = 0

    @property
    def is_paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        """Enforce pause barrier."""
        self._paused = True

    def resume(self) -> None:
        """Lift pause barrier."""
        self._paused = False

    def _next_id(self) -> int:
        self._request_counter += 1
        return self._request_counter

    @staticmethod
    def _validate_response(request: Dict[str, Any], response: Any) -> Dict[str, Any]:
        """Fail closed unless response is a matching JSON-RPC 2.0 response envelope."""
        valid = isinstance(response, dict) and response.get("jsonrpc") == "2.0"
        if valid:
            response_id = response.get("id")
            request_id = request["id"]
            # Python considers bool an int subtype (True == 1); JSON-RPC IDs
            # must match both value and JSON scalar type.
            valid = type(response_id) is type(request_id) and response_id == request_id
        if valid:
            valid = ("result" in response) != ("error" in response)
        if valid and "error" in response:
            error = response["error"]
            valid = (
                isinstance(error, dict)
                and isinstance(error.get("code"), int)
                and not isinstance(error.get("code"), bool)
                and isinstance(error.get("message"), str)
            )
        if not valid:
            raise AdapterSecurityError("MCP_INVALID_RESPONSE", "Malformed or mismatched JSON-RPC 2.0 response")
        return response

    def _send_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        response = self.server.handle_request(request)
        return self._validate_response(request, response)

    def list_tools(self) -> List[Dict[str, Any]]:
        """Query available tools via MCP tools/list."""
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/list",
            "params": {},
        }
        resp = self._send_request(req)
        result = resp.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("tools"), list):
            raise AdapterSecurityError("MCP_INVALID_RESPONSE", "tools/list result must contain a tools array")
        return result["tools"]

    def list_resources(self) -> List[Dict[str, Any]]:
        """Query available resources via MCP resources/list."""
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "resources/list",
            "params": {},
        }
        resp = self._send_request(req)
        result = resp.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("resources"), list):
            raise AdapterSecurityError("MCP_INVALID_RESPONSE", "resources/list result must contain a resources array")
        return result["resources"]

    def read_resource(self, uri: str) -> Dict[str, Any]:
        """Read resource content via MCP resources/read."""
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "resources/read",
            "params": {"uri": uri},
        }
        resp = self._send_request(req)
        if "error" in resp:
            raise RuntimeError(f"MCP error: {resp['error']}")
        result = resp.get("result")
        if not isinstance(result, dict) or not isinstance(result.get("contents"), list):
            raise AdapterSecurityError("MCP_INVALID_RESPONSE", "resources/read result must contain a contents array")
        return result

    def call_registered_tool(
        self,
        session_context: Dict[str, Any],
        server_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        authorization_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Trusted-config entry: default-deny before any MCP transport request."""
        registration = self.registry.resolve(server_id, tool_name)
        declared_server = getattr(self.server, "server_id", server_id)
        if declared_server != registration.server_id:
            raise AdapterSecurityError("MCP_SERVER_MISMATCH", f"{declared_server} != {registration.server_id}")
        declared_digest = self.server.declared_tool_schema_digest(tool_name)
        if declared_digest != registration.schema_digest:
            raise AdapterSecurityError("MCP_SCHEMA_DRIFT", f"{tool_name} schema changed after registration")
        if registration.risk_level == "high" and (
                not authorization_context or not authorization_context.get("approval_id")):
            raise AdapterSecurityError(
                "PRE_TOOL_UNAUTHORIZED", f"High risk MCP tool '{tool_name}' requires valid approval token")
        return self.call_tool(session_context, tool_name, arguments, authorization_context=authorization_context)

    def write(self, action, authorize):
        """Effect provider interface matching the document provider's signature."""
        from aetp.runtime.records import receipt

        authorize()
        registration = self.registry.resolve(action["arguments"]["server_id"], action["arguments"]["tool_name"])
        response = self.call_registered_tool(
            {"actor_id": action["actor_id"], "lease_epoch": action["lease_epoch"]},
            action["arguments"]["server_id"],
            action["arguments"]["tool_name"],
            action["arguments"]["tool_arguments"],
            authorization_context={"authenticated_actor_id": action["actor_id"], "lease_epoch": action["lease_epoch"]},
        )
        if response.get("status") != "success":
            raise AdapterSecurityError("MCP_TOOL_ERROR", f"{registration.tool_name} returned an error")
        return receipt(action)

    def query(self, action):
        """Conservative reconciliation: no replay of a possibly-applied tool call."""

        return {"status": "unknown", "reason": "MCP_CALL_NOT_QUERYABLE"}

    def call_tool(
        self,
        session_context: Dict[str, Any],
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        authorization_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute tool call with strict pre-tool interception boundaries (§13.9)."""
        # 1. Pause Barrier
        if self._paused:
            raise AdapterSecurityError("PROJECT_PAUSED", "MCP execution is paused")

        # 2. Binding and Actor Alignment
        expected_actor = session_context.get("actor_id")
        auth_actor = authorization_context.get("authenticated_actor_id") if authorization_context else None
        if expected_actor:
            if not auth_actor:
                raise AdapterSecurityError("AUTHENTICATED_ACTOR_REQUIRED", "Bound session requires an authenticated actor")
            if expected_actor != auth_actor:
                raise AdapterSecurityError("ACTOR_MISMATCH", f"Actor {auth_actor} does not match session binding {expected_actor}")

        # 3. Lease Epoch Alignment
        expected_epoch = session_context.get("lease_epoch")
        provided_epoch = authorization_context.get("lease_epoch") if authorization_context else None
        if expected_epoch is not None:
            if provided_epoch is None:
                raise AdapterSecurityError("LEASE_EPOCH_REQUIRED", "Bound session requires a lease epoch")
            if expected_epoch != provided_epoch:
                raise AdapterSecurityError("LEASE_EXPIRED", "Provided lease epoch does not match active binding")

        # 4. High-risk Tool Pre-Authorization and Argument Anti-Tampering Check
        if tool_name in self.high_risk_tools:
            if not authorization_context or not authorization_context.get("approval_id"):
                raise AdapterSecurityError("PRE_TOOL_UNAUTHORIZED", f"High risk MCP tool '{tool_name}' requires valid approval token")
            if "expected_arguments_digest" in authorization_context:
                actual_digest = "sha256:" + hashlib.sha256(
                    json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                if actual_digest != authorization_context["expected_arguments_digest"]:
                    raise AdapterSecurityError("APPROVAL_STALE", "Arguments tampered after approval grant")

        # 5. Dispatch JSON-RPC request to target MCP Server
        req = {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }
        resp = self._send_request(req)
        if "error" in resp:
            return {"status": "error", "error": resp["error"]}
        result = resp.get("result")
        if not isinstance(result, dict):
            raise AdapterSecurityError("MCP_INVALID_RESPONSE", "tools/call result must be an object")

        return {"status": "success", "result": result}
