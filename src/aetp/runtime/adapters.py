"""AETP Runtime Adapter Contract and capability declarations.

Specification source: Docs/AETP-设计方案.md §§13.9, 5.13, 6.4, INV-001, INV-011.
External execution agents interface with AETP through structured Runtime Adapters.
"""

from __future__ import annotations

import abc
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, Optional


class AdapterSecurityError(PermissionError):
    """Raised when an unapproved or bypassed tool action is intercepted."""
    def __init__(self, code: str, message: str = ""):
        super().__init__(f"[{code}] {message}" if message else code)
        self.code = code


# §13.9: "capability declarations are not a security proof". Only these two
# isolation levels have a meaning AETP can act on; anything else is an
# unrecognised claim and is treated as unverified rather than honoured.
WORKSPACE_ISOLATION_LEVELS = ("working_copy", "os_sandbox")
# §13.9: the isolation level an adapter may declare as SATISFIED without
# evidence. working_copy is the honest floor - it says only "a separate working
# copy", which is exactly what GitWorktree/Local FS providers provide. A
# declaration of os_sandbox has to be measured (see Conformance/host probe)
# before the qualification gate may treat it as met; this is the fail-closed
# half of "claiming a control you cannot prove" (§13.9 anti-bypass).
VERIFIED_WORKSPACE_ISOLATION = ("working_copy",)


@dataclass(frozen=True)
class RuntimeEnforcement:
    mode: str  # "mediated" | "observation_only"
    authenticated_actor: bool = True
    pre_tool_authorization: bool = True
    credential_isolation: bool = True
    workspace_isolation: str = "working_copy"  # see WORKSPACE_ISOLATION_LEVELS
    network_egress: str = "disabled"  # "unrestricted" | "allowlist" | "disabled"
    pause_control: str = "controlled_execution"  # "controlled_execution" | "dispatch_only"


def verified_workspace_isolation(enforcement: RuntimeEnforcement) -> bool:
    """True only when the declared isolation level is one AETP has measured."""
    return enforcement.workspace_isolation in VERIFIED_WORKSPACE_ISOLATION


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
        """High-risk tasks require mediated mode, pre-tool checks, verified isolation."""
        return (
            self.enforcement.mode == "mediated"
            and self.enforcement.pre_tool_authorization
            and self.enforcement.authenticated_actor
            and verified_workspace_isolation(self.enforcement)
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
