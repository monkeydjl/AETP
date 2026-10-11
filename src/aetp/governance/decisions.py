"""Governance status of an immutable proposal; content versions never drift."""

import copy

from aetp.collaboration.policy import PolicyViolation, text
from aetp.governance.approvals import authorize
from aetp.governance.policy import current, fields, has_role, revision
from aetp.governance.snapshots import snapshot


def transition(command, previous, state, at, context):
    if previous is None:
        raise PolicyViolation("INVALID_TARGET")
    revision(command, previous)
    governance, value = current(state, command.project_id)
    updated = copy.deepcopy(previous)
    updated.update(revision=previous["revision"] + 1, observed_at_ms=at, last_actor_id=command.actor_id,
                   proposal_revision=previous.get("proposal_revision", previous["revision"]))
    if command.type == "decision.review":
        fields(command.payload, {"feedback"}, {"feedback"})
        if command.actor_id == previous["proposed_by"]:
            raise PolicyViolation("SELF_REVIEW")
        if not (has_role(value, command.actor_id, "independent_reviewer") or has_role(value, command.actor_id, "human_collaborator")):
            raise PolicyViolation("PERMISSION_DENIED")
        if previous["status"] not in {"proposed", "reviewing"}:
            raise PolicyViolation("INVALID_TRANSITION")
        updated.update(status="reviewing", governance_review={"reviewer_id": command.actor_id,
                       "feedback": text(command.payload["feedback"]), "command_id": command.id,
                       "proposal_digest": previous["content_digest"], "untrusted_input": previous["untrusted_input"]})
        return "decision.reviewing", updated
    if command.type == "decision.submit":
        fields(command.payload, set())
        if previous["status"] != "reviewing" or not previous.get("governance_review"):
            raise PolicyViolation("INVALID_TRANSITION")
        if command.actor_id != previous["proposed_by"]:
            raise PolicyViolation("PERMISSION_DENIED")
        updated["status"] = "pending_approval"
        return "decision.pending_approval", updated
    if command.type in {"decision.approve", "decision.activate"}:
        fields(command.payload, {"approval_id", "arguments"}, {"approval_id", "arguments"})
        required = {"pending_approval", "approved"} if command.type == "decision.approve" else {"approved"}
        if previous["status"] not in required:
            raise PolicyViolation("INVALID_TRANSITION")
        if state[f"project:{command.project_id}"]["status"] == "paused" and command.type == "decision.activate":
            raise PolicyViolation("PROJECT_PAUSED")
        target = snapshot(state, "decision", previous["id"])
        approval = authorize(command.payload["approval_id"], target, "decision.activate", command.payload["arguments"],
                             command.actor_id, state, at)
        if command.type == "decision.activate" and previous.get("approval_id") != approval["id"]:
            raise PolicyViolation("APPROVAL_STALE")
        updated.update(status="approved" if command.type == "decision.approve" else "active", approval_id=approval["id"],
                       authorization_status="current", authority="governed_decision_only")
        return "decision.approved" if command.type == "decision.approve" else "decision.activated", updated
    if command.type == "decision.invalidate":
        fields(command.payload, {"approval_id", "reason"}, {"approval_id", "reason"})
        approval = state.get(f"approval:{command.payload['approval_id']}")
        if approval is None or approval["target"]["type"] != "decision" or approval["target"]["id"] != previous["id"]:
            raise PolicyViolation("INVALID_REFERENCE")
        reason = command.payload["reason"]
        expected = {"approval_denied": "rejected", "approval_revoked": "revoked", "approval_expired": "expired"}
        if reason == "policy_changed":
            if approval["validity"] != "invalidated":
                raise PolicyViolation("INVALID_TRANSITION")
        elif expected.get(reason) != approval["status"]:
            raise PolicyViolation("INVALID_TRANSITION")
        updated.update(authorization_status=approval["status"] if reason != "policy_changed" else "invalidated",
                       authorization_impact={"approval_id": approval["id"], "reason": reason, "replanning_required": True})
        if previous["status"] != "active":
            if reason == "approval_denied":
                updated["status"] = "rejected"
            elif reason != "approval_expired" or approval["expiration_resolution"]["kind"] == "reject":
                updated["status"] = "reviewing"
        return "decision.rejected" if updated["status"] == "rejected" else "decision.invalidated", updated
    raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
