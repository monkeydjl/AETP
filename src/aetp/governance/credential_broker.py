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
        # Tokens minted for a Command whose Event has not committed yet. Only
        # these may be discarded; a committed credential belongs to the
        # Projection, which is the authority on whether it is still live.
        self._pending: set = set()

    def issue(self, agent: str, *, permissions, issued_at: int, expires_in_ms: int,
              pending: bool = False) -> Dict:
        """Mint a credential.

        `pending` is set only by the governance path, for a token whose Event
        has not committed yet: such a token may be discarded if the Command
        fails. Everything else is committed on arrival, because a caller that
        mints directly has no cleanup step and a permanent pending entry would
        leak for the process lifetime.
        """
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
        if pending:
            self._pending.add(token)
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

    def revoke(self, token: str, *, actor: str) -> None:
        """Revoke an issued credential; subsequent resolutions are rejected.

        `actor` is mandatory: revocation is an authorized act, so the caller
        must name itself and the Broker checks it owns the credential. Only
        the owning Agent can revoke, matching the Command-side rule.

        Migration note: `actor` was added as a required keyword-only argument,
        so any caller written against the older two-argument form fails loudly
        with TypeError instead of revoking anonymously. Passing it is not
        optional and has no default: an unnamed revoke would have to skip the
        ownership check, which is the loophole this signature closes.
        """
        credential = self._credentials.get(token)
        if credential is None:
            raise CredentialBrokerError("CREDENTIAL_UNKNOWN")
        if not isinstance(actor, str) or not actor.strip():
            raise CredentialBrokerError("INVALID_AGENT")
        if actor != credential.agent:
            raise CredentialBrokerError("PERMISSION_DENIED")
        self._credentials[token] = _Credential(
            agent=credential.agent,
            permissions=credential.permissions,
            issued_at_ms=credential.issued_at_ms,
            expires_at_ms=credential.expires_at_ms,
            revoked=True,
        )

    def revoke_by_ref(self, token_ref: str, *, actor: str) -> None:
        """Revoke an issued credential by its persistable ref."""
        token = self._ref_to_token.get(token_ref)
        if token is None:
            raise CredentialBrokerError("CREDENTIAL_UNKNOWN")
        self.revoke(token, actor=actor)

    def _discard(self, token: str) -> None:
        """Drop a credential minted for a Command that never committed.

        Not a revocation: no authorisation is involved, because the credential
        was never observable. Revocation needs a Projection record to travel
        through, so a token whose Event never landed could not be revoked by
        anyone for the rest of its TTL. Un-minting it is the only way back.

        Only a token still pending its commit may be dropped. Once the Event
        committed, the Projection is the authority on whether the credential
        is live: discarding it here would leave a record saying "not revoked"
        while the token silently stopped resolving.
        """
        if not isinstance(token, str):
            return
        if token not in self._pending:
            raise CredentialBrokerError("CREDENTIAL_COMMITTED")
        self._pending.discard(token)
        if self._credentials.pop(token, None) is None:
            return
        for ref, body in list(self._ref_to_token.items()):
            if body == token:
                del self._ref_to_token[ref]
                return

    def _confirm(self, token: str) -> None:
        """Record that the token's Event committed; it is no longer discardable."""
        if isinstance(token, str):
            self._pending.discard(token)
