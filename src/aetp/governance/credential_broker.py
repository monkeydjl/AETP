"""Minimal Credential Broker (spec 14.3 / INV-012).

An Agent never holds long-term secrets; it requests a short-term scoped
credential bound to explicit permissions and a wall-clock expiry. Pausing a
Project must NOT extend a credential's real validity, so expiry is wall-clock
time expressed in milliseconds, compared against the caller-provided clock.

This module stores only opaque issued tokens and their scopes; it never stores
or returns a long-term secret.
"""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, Tuple

from aetp.collaboration.policy import PolicyViolation


class CredentialBrokerError(PolicyViolation):
    """Credential failures map to the protocol rejection vocabulary."""

    def __init__(self, code: str, message: str = ""):
        PolicyViolation.__init__(self, code)
        self.message = message


@dataclass(frozen=True)
class _Credential:
    agent: str
    permissions: Tuple[str, ...]
    issued_at_ms: int
    expires_at_ms: int
    revoked: bool = False


class CredentialBroker:
    """Issues and resolves short-term scoped credentials against a wall clock."""

    def __init__(self):
        self._credentials: Dict[str, _Credential] = {}
        # token_ref (the non-invertible digest) -> token body. The body is
        # memory-only and is how a consuming Tool authorizer recovers it.
        self._ref_to_token: Dict[str, str] = {}

    def issue(self, agent: str, *, permissions, issued_at: int, expires_in_ms: int) -> Dict:
        if not isinstance(agent, str) or not agent.strip():
            raise CredentialBrokerError("INVALID_AGENT")
        if not isinstance(permissions, (list, tuple)) or not permissions:
            raise CredentialBrokerError("INVALID_SCOPE")
        normalized = tuple(permissions)
        if not all(isinstance(p, str) and p.strip() for p in normalized):
            raise CredentialBrokerError("INVALID_SCOPE")
        if not isinstance(expires_in_ms, int) or expires_in_ms <= 0:
            raise CredentialBrokerError("INVALID_TTL")
        if not isinstance(issued_at, int):
            raise CredentialBrokerError("INVALID_CLOCK")

        token = "cred_" + secrets.token_hex(24)
        self._credentials[token] = _Credential(
            agent=agent,
            permissions=tuple(sorted(set(normalized))),
            issued_at_ms=issued_at,
            expires_at_ms=issued_at + expires_in_ms,
        )
        token_ref = "credref_" + hashlib.sha256(token.encode("utf-8")).hexdigest()
        self._ref_to_token[token_ref] = token
        return {
            "token": token,
            # token_ref is a non-invertible reference safe to persist in the
            # Event Store; the token body stays only in this broker's memory.
            "token_ref": token_ref,
            "permissions": list(self._credentials[token].permissions),
            "issued_at_ms": issued_at,
            "expires_at_ms": self._credentials[token].expires_at_ms,
        }

    def resolve(self, token: str, at: int) -> Dict:
        """Return the granted scope if the token is known, live and unexpired."""
        credential = self._credentials.get(token)
        if credential is None:
            raise CredentialBrokerError("CREDENTIAL_UNKNOWN")
        if credential.revoked:
            raise CredentialBrokerError("CREDENTIAL_REVOKED")
        if not isinstance(at, int):
            raise CredentialBrokerError("INVALID_CLOCK")
        if at < credential.issued_at_ms:
            raise CredentialBrokerError("CREDENTIAL_NOT_YET_VALID")
        if at >= credential.expires_at_ms:
            raise CredentialBrokerError("CREDENTIAL_EXPIRED")
        return {
            "token": token,
            "agent": credential.agent,
            "permissions": list(credential.permissions),
            "expires_at_ms": credential.expires_at_ms,
        }

    def assert_permission(self, token: str, permission: str, at: int) -> Dict:
        """Resolve then check a single permission, raising PERMISSION_DENIED."""
        if not isinstance(permission, str) or not permission.strip():
            raise CredentialBrokerError("INVALID_SCOPE")
        granted = self.resolve(token, at)
        if permission not in granted["permissions"]:
            raise CredentialBrokerError("PERMISSION_DENIED")
        return granted

    def assert_permission_by_ref(self, token_ref: str, permission: str, at: int) -> Dict:
        """Consuming Tools carry the persistable ref; the body stays in memory."""
        if not isinstance(token_ref, str) or not token_ref.strip():
            raise CredentialBrokerError("CREDENTIAL_UNKNOWN")
        token = self._ref_to_token.get(token_ref)
        if token is None:
            raise CredentialBrokerError("CREDENTIAL_UNKNOWN")
        return self.assert_permission(token, permission, at)

    def revoke(self, token: str) -> None:
        """Revoke an issued credential; subsequent resolutions are rejected."""
        credential = self._credentials.get(token)
        if credential is None:
            raise CredentialBrokerError("CREDENTIAL_UNKNOWN")
        self._credentials[token] = _Credential(
            agent=credential.agent,
            permissions=credential.permissions,
            issued_at_ms=credential.issued_at_ms,
            expires_at_ms=credential.expires_at_ms,
            revoked=True,
        )

    def revoke_by_ref(self, token_ref: str) -> None:
        """Revoke an issued credential by its persistable ref."""
        token = self._ref_to_token.get(token_ref)
        if token is None:
            raise CredentialBrokerError("CREDENTIAL_UNKNOWN")
        self.revoke(token)