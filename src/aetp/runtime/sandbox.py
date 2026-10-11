"""Safe local sandbox adapter implementation with pre-tool authorization boundaries.

Specification source: Docs/AETP-设计方案.md §§13.9, 14.4, 14.11, INV-013, INV-020.
Enforces pre-tool authorization, actor/binding verification, and pause barriers
before dispatching any local command or MCP-style tool call.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set

from aetp.runtime.adapters import (
    AdapterSecurityError,
    RuntimeAdapter,
    RuntimeCapability,
    RuntimeEnforcement,
)


class PreToolAuthorizer:
    """Evaluates whether a tool call is authorized in the current session context."""

    def __init__(
        self,
        *,
        allowed_tools: Optional[Set[str]] = None,
        high_risk_tools: Optional[Set[str]] = None,
    ):
        self.allowed_tools = allowed_tools or {"echo", "query", "fs_read", "fs_write", "shell"}
        self.high_risk_tools = high_risk_tools or {"fs_write", "shell", "deploy"}

    def authorize(
        self,
        session_context: Dict[str, Any],
        tool_name: str,
        arguments: Dict[str, Any],
        authorization_context: Optional[Dict[str, Any]],
    ) -> None:
        """Validate all pre-tool constraints before execution."""
        # 1. Tool name whitelist
        if tool_name not in self.allowed_tools:
            raise AdapterSecurityError("TOOL_NOT_PERMITTED", f"Tool '{tool_name}' is not in allowed tool set")

        # 2. Binding and actor verification
        expected_actor = session_context.get("actor_id")
        auth_actor = authorization_context.get("authenticated_actor_id") if authorization_context else None
        if expected_actor and auth_actor and expected_actor != auth_actor:
            raise AdapterSecurityError("ACTOR_MISMATCH", f"Authenticated actor {auth_actor} does not match binding actor {expected_actor}")

        # 3. Lease epoch check
        expected_epoch = session_context.get("lease_epoch")
        provided_epoch = authorization_context.get("lease_epoch") if authorization_context else None
        if expected_epoch is not None and provided_epoch is not None and expected_epoch != provided_epoch:
            raise AdapterSecurityError("LEASE_EXPIRED", "Provided lease epoch does not match active session binding")

        # 4. High-risk tool calls require explicit approval token
        if tool_name in self.high_risk_tools:
            if not authorization_context or not authorization_context.get("approval_id"):
                raise AdapterSecurityError("PRE_TOOL_UNAUTHORIZED", f"High risk tool '{tool_name}' requires valid approval authorization")
            # Verify argument digest if provided in authorization context
            if "expected_arguments_digest" in authorization_context:
                import hashlib
                import json
                actual_digest = "sha256:" + hashlib.sha256(
                    json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
                ).hexdigest()
                if actual_digest != authorization_context["expected_arguments_digest"]:
                    raise AdapterSecurityError("APPROVAL_STALE", "Arguments tampered after approval grant")


class SandboxRuntimeAdapter(RuntimeAdapter):
    """Local execution sandbox with mediated pre-tool interception (§13.9)."""

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        authorizer: Optional[PreToolAuthorizer] = None,
        capability: Optional[RuntimeCapability] = None,
    ):
        # Honest compatibility scope: the local in-process adapter enforces a
        # path-prefix boundary and pre-tool checks, but cannot claim a real OS
        # sandbox or credential/network egress isolation (§13.9 anti-bypass).
        cap = capability or RuntimeCapability(
            adapter_id="aetp-local-sandbox",
            version="0.1",
            enforcement=RuntimeEnforcement(
                mode="mediated",
                authenticated_actor=True,
                pre_tool_authorization=True,
                credential_isolation=False,
                workspace_isolation="working_copy",
            ),
        )
        super().__init__(cap)
        self.workspace_root = Path(workspace_root).resolve()
        self.authorizer = authorizer or PreToolAuthorizer()
        self.sessions: Dict[str, Dict[str, Any]] = {}

    def start_session(self, session_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        session_record = copy.deepcopy(context)
        session_record.update({
            "session_id": session_id,
            "status": "active",
            "working_directory": str(self.workspace_root),
        })
        self.sessions[session_id] = session_record
        return {"session_id": session_id, "status": "active"}

    def stop_session(self, session_id: str, reason: str) -> Dict[str, Any]:
        if session_id in self.sessions:
            self.sessions[session_id]["status"] = "stopped"
            self.sessions[session_id]["stop_reason"] = reason
        return {"session_id": session_id, "status": "stopped", "reason": reason}

    def execute_tool(
        self,
        session_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        authorization_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        # 1. Pause Barrier Check (§13.4 / §13.9)
        if self.is_paused:
            raise AdapterSecurityError("PROJECT_PAUSED", "Runtime execution is paused")

        session = self.sessions.get(session_id)
        if session is None or session.get("status") != "active":
            raise AdapterSecurityError("INVALID_SESSION", f"Session '{session_id}' is not active")

        # 2. Pre-Tool Interception (§13.9)
        self.authorizer.authorize(session, tool_name, arguments, authorization_context)

        # 3. Path boundary containment check for file tools
        if tool_name in {"fs_read", "fs_write"}:
            path_arg = arguments.get("path")
            if not path_arg:
                raise AdapterSecurityError("INVALID_ARGUMENTS", "Path argument missing")
            target_path = (self.workspace_root / path_arg).resolve()
            try:
                target_path.relative_to(self.workspace_root)
            except ValueError:
                raise AdapterSecurityError("WORKSPACE_VIOLATION", f"Path '{path_arg}' escapes workspace boundary")

        # 4. Safe Tool Execution Simulation
        if tool_name == "echo":
            return {"status": "success", "output": arguments.get("message", "")}
        elif tool_name == "query":
            return {"status": "success", "data": {"reconciled": True}}
        elif tool_name == "fs_read":
            target_path = (self.workspace_root / arguments["path"]).resolve()
            content = target_path.read_text(encoding="utf-8") if target_path.exists() else ""
            return {"status": "success", "content": content}
        elif tool_name == "fs_write":
            target_path = (self.workspace_root / arguments["path"]).resolve()
            target_path.parent.mkdir(parents=True, exist_ok=True)
            content = arguments.get("content", "")
            target_path.write_text(content, encoding="utf-8")
            return {"status": "success", "bytes_written": len(content)}
        elif tool_name == "shell":
            cmd = arguments.get("command", "")
            return {"status": "success", "command_executed": cmd, "exit_code": 0}

        return {"status": "success", "result": "ok"}
