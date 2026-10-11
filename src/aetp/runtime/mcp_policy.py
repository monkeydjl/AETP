"""Trusted MCP server/tool registrations for AETP default-deny policy."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple

from aetp.collaboration.policy import PolicyViolation


@dataclass(frozen=True)
class MCPToolRegistration:
    server_id: str
    tool_name: str
    risk_level: str
    schema_digest: str


class MCPToolRegistry:
    """Host-supplied allowlist; remote tools/list never grants permission."""

    def __init__(self):
        self._entries: Dict[Tuple[str, str], MCPToolRegistration] = {}

    def register(self, registration: MCPToolRegistration) -> None:
        if not isinstance(registration, MCPToolRegistration):
            raise TypeError("MCPToolRegistration required")
        self._entries[(registration.server_id, registration.tool_name)] = registration

    def resolve(self, server_id: str, tool_name: str) -> MCPToolRegistration:
        try:
            return self._entries[(server_id, tool_name)]
        except KeyError as exc:
            # Default-deny is a protocol policy decision; it must surface as a
            # PolicyViolation so the AETP execution boundary can reject the
            # Command instead of leaking an adapter-only exception.
            raise PolicyViolation("MCP_TOOL_NOT_REGISTERED") from exc
