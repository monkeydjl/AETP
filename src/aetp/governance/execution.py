"""Pure approval binding for the fixed document Runtime's real call boundary."""

import copy

from aetp.collaboration.policy import PolicyViolation, canonical_json
from aetp.governance.approvals import authorize
from aetp.governance.contracts import RISKS
from aetp.governance.snapshots import snapshot


def authorization_record(identifier, state, requested_risk="low"):
    approval = state.get(f"approval:{identifier}") if isinstance(identifier, str) else None
    if approval is None:
        raise PolicyViolation("APPROVAL_REQUIRED")
    if requested_risk not in RISKS:
        raise PolicyViolation("INVALID_PAYLOAD")
    return {"approval_id": approval["id"], "request_digest": approval["request_digest"],
            "policy_version": approval["policy_version"], "source": copy.deepcopy(approval["source"]),
            "requested_risk": requested_risk}


def authorize_action(action, state, at):
    project = state[f"project:{action['project_id']}"]
    proof = action.get("authorization")
    if not project.get("governance"):
        if proof is not None:
            raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
        return
    if not isinstance(proof, dict):
        raise PolicyViolation("APPROVAL_REQUIRED")
    expected = authorization_record(proof.get("approval_id"), state, proof.get("requested_risk"))
    if canonical_json(proof) != canonical_json(expected):
        raise PolicyViolation("APPROVAL_STALE")
    approval = state[f"approval:{proof['approval_id']}"]
    if RISKS.index(proof["requested_risk"]) > RISKS.index(approval["risk_level"]):
        raise PolicyViolation("APPROVAL_REQUIRED")
    normalized = {"operation": action["operation"], "arguments": action["arguments"],
                  "binding_id": action["binding_id"], "lease_epoch": action["lease_epoch"], "session_id": action["session_id"]}
    target = snapshot(state, "task", action["task_id"])
    authorize(proof["approval_id"], target, action["operation"], normalized, action["actor_id"], state, at)
