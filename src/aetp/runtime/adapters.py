"""AETP Runtime Adapter Contract and capability declarations.

Specification source: Docs/AETP-设计方案.md §§13.9, 5.13, 6.4, INV-001, INV-011.
External execution agents interface with AETP through structured Runtime Adapters.
"""

from __future__ import annotations

import abc
import copy
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


class AdapterSecurityError(PermissionError):
    """Raised when an unapproved or bypassed tool action is intercepted."""
    def __init__(self, code: str, message: str = ""):
        super().__init__(f"[{code}] {message}" if message else code)
        self.code = code


@dataclass(frozen=True)
class RuntimeEnforcement:
    mode: str  # "mediated" | "observation_only"
    authenticated_actor: bool = True
    pre_tool_authorization: bool = True
    credential_isolation: bool = True
    workspace_isolation: str = "working_copy"  # "working_copy" | "os_sandbox"
    network_egress: str = "disabled"  # "unrestricted" | "allowlist" | "disabled"
    pause_control: str = "controlled_execution"  # "controlled_execution" | "dispatch_only"


@dataclass(frozen=True)
class RuntimeCapability:
    adapter_id: str
    version: str
    task_capabilities: tuple[str, ...] = ("assign", "cancel", "pause")
    workspace_capabilities: tuple[str, ...] = ("working_copy", "filesystem")
    execution_capabilities: tuple[str, ...] = ("shell", "filesystem")
    streaming_capabilities: tuple[str, ...] = ("stdout", "progress")
    enforcement: RuntimeEnforcement = field(default_factory=lambda: RuntimeEnforcement(mode="mediated"))

    def is_eligible_for_high_risk(self) -> bool:
        """High-risk tasks strictly require mediated mode with pre-tool checks."""
        return (
            self.enforcement.mode == "mediated"
            and self.enforcement.pre_tool_authorization
            and self.enforcement.authenticated_actor
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "version": self.version,
            "task_capabilities": list(self.task_capabilities),
            "workspace_capabilities": list(self.workspace_capabilities),
            "execution_capabilities": list(self.execution_capabilities),
            "streaming_capabilities": list(self.streaming_capabilities),
            "enforcement": asdict(self.enforcement),
        }


class RuntimeAdapter(abc.ABC):
    """Abstract interface defining AETP -> Runtime control surface (§13.9)."""

    def __init__(self, capability: RuntimeCapability):
        self._capability = capability
        self._paused = False

    @property
    def capability(self) -> RuntimeCapability:
        return self._capability

    @property
    def is_paused(self) -> bool:
        return self._paused

    def pause(self) -> None:
        """Pause runtime execution and intercept further actions."""
        self._paused = True

    def resume(self) -> None:
        """Resume runtime execution."""
        self._paused = False

    @abc.abstractmethod
    def start_session(self, session_id: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Start a managed execution session."""
        pass

    @abc.abstractmethod
    def stop_session(self, session_id: str, reason: str) -> Dict[str, Any]:
        """Terminate a managed execution session."""
        pass

    @abc.abstractmethod
    def execute_tool(
        self,
        session_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        *,
        authorization_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Execute a tool with pre-tool authorization checks."""
        pass
