"""Credential transitions (spec 14.3 / INV-012): scoped, wall-clock-TTL issue.

Only the token reference and scope/expiry metadata enter the Projection. The
opaque token body lives in the trusted Broker and is never stored here.
"""

from __future__ import annotations

from aetp.collaboration.policy import PolicyViolation
from aetp.governance.policy import principal, revision


# Fixed allowlist of service-scoped permissions available to Agents. A request
# outside this set is refused, never widened.
SCOPE_WHITELIST = frozenset({
    "github.repo.read",
    "github.repo.write",
    "browser.read_only",
})


def issue(command, state, at, context):
    """Validate and reduce a credential.request into a credential.issued record."""
    from aetp.domain.models import Command
    if not isinstance(command, Command):
        raise PolicyViolation("INVALID_PAYLOAD")
    principal_type = principal(state, command.project_id, command.actor_id)["type"]
    if principal_type != "agent":
        raise PolicyViolation("PERMISSION_DENIED")

    # One target holds exactly one live credential. Overwriting the token_ref
    # while the old token is still usable would leave that token live until it
    # expired with no record left to revoke it through: an orphan made by the
    # Command path. Once the previous credential is revoked or expired there is
    # nothing left to strand, so re-issuing the same target is ordinary
    # rotation and stays allowed.
    existing = state.get(f"credential:{command.target_id}")
    revision(command, existing)
    if (existing is not None and not existing.get("revoked")
            and at < existing.get("expires_at_ms", 0)):
        # A distinct code from REVISION_CONFLICT: the caller should wait for the
        # live credential to be revoked or to expire, not re-read and retry a
        # revision. Sharing one code made the two causes indistinguishable in
        # evidence and in the caller's control flow.
        raise PolicyViolation("CREDENTIAL_STILL_LIVE")

    permissions = command.payload.get("permissions")
    ttl_ms = command.payload.get("ttl_ms")
    if not isinstance(permissions, (list, tuple)) or not permissions or not isinstance(ttl_ms, int) or ttl_ms <= 0:
        raise PolicyViolation("INVALID_PAYLOAD")
    unknown = set(permissions) - SCOPE_WHITELIST
    if unknown:
        raise PolicyViolation("PERMISSION_DENIED")

    token_ref = context.get("broker_token_ref")
    if not isinstance(token_ref, str) or not token_ref:
        raise PolicyViolation("CREDENTIAL_UNAVAILABLE")

    return "credential.issued", {
        "id": command.target_id,
        "project_id": command.project_id,
        # A re-issue continues the record it replaces instead of restarting it.
        # Hard-coding revision 1 would move the aggregate backwards after a
        # revocation, so a stale expected_revision would be accepted and the
        # stored revoked=True fact would be overwritten.
        "revised": existing is not None,
        "revision": (existing["revision"] if existing is not None else 0) + 1,
        "token_ref": token_ref,
        # Ownership is recorded so revocation can tell the owning Agent from
        # any other Agent; without it the revoke check has nothing to compare.
        "owner_id": command.actor_id,
        "permissions": list(permissions),
        "issued_at_ms": at,
        "expires_at_ms": at + ttl_ms,
        "revoked": False,
    }


def revoke(command, previous, state, at, context):
    """Mark a credential revoked; no token body materializes."""
    if previous is None:
        raise PolicyViolation("INVALID_TARGET")
    from aetp.governance.policy import principal
    principal_type = principal(state, command.project_id, command.actor_id)["type"]
    if principal_type not in {"human", "agent"}:  # humans or the owning Agent may revoke
        raise PolicyViolation("PERMISSION_DENIED")
    # A human may revoke any credential in the project; an Agent only its own.
    # Records predating ownership persistence carry no owner and stay revocable
    # by humans only, never by an arbitrary Agent.
    if principal_type == "agent" and previous.get("owner_id") != command.actor_id:
        raise PolicyViolation("PERMISSION_DENIED")
    revision(command, previous)
    record = dict(previous)
    record["revoked"] = True
    record.pop("token", None)
    record.pop("secret", None)
    record["revision"] = previous["revision"] + 1
    return "credential.revoked", record


def transition(command, previous, state, at, context):
    if command.type == "credential.request":
        return issue(command, state, at, context)
    if command.type == "credential.revoke":
        return revoke(command, previous, state, at, context)
    raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")