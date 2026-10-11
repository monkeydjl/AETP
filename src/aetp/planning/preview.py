"""Pure display of candidate structure; never a dispatch/readiness authority."""

import copy

from aetp.collaboration.policy import PolicyViolation
from aetp.governance.approvals import valid_snapshot
from aetp.planning.references import decisions, resolve


def build(candidate, state, at):
    project_id = candidate["project_id"]
    blockers = ["PLANNING_NOT_ACTIVE", "BOOTSTRAP_ENFORCEMENT_UNAVAILABLE", "TARGET_APPROVAL_UNAVAILABLE"]
    if state[f"project:{project_id}"]["status"] == "paused":
        blockers.append("PROJECT_PAUSED")
    if state[f"blueprint:{candidate['id']}"]["latest_proposal_version"] != candidate["version"]:
        blockers.append("BLUEPRINT_REFERENCE_STALE")
    for kind in ("mission", "team"):
        try:
            resolve(candidate["content"][kind], state, project_id, kind)
        except PolicyViolation:
            blockers.append(f"{kind.upper()}_REFERENCE_STALE")
    dependencies = []
    for entry in candidate["dag"]["decision_dependencies"]:
        reason = None
        ref = entry["reference"]
        try:
            decisions([ref], state, project_id)
            decision = state[f"decision:{ref['id']}"]
            if decision["status"] != "active":
                raise PolicyViolation("DECISION_NOT_ACTIVE")
            if decision.get("authorization_status") != "current":
                raise PolicyViolation("DECISION_AUTHORIZATION_INVALID")
            approval = state.get(f"approval:{decision.get('approval_id')}")
            if approval is None:
                raise PolicyViolation("APPROVAL_REQUIRED")
            valid_snapshot(approval, state, at, require_approved=True)
        except PolicyViolation as exc:
            reason = exc.code
        dependencies.append({"task_id": entry["task_id"], "reference": copy.deepcopy(ref),
                             "satisfied": reason is None, "reason": reason})
    return {"blueprint_id": candidate["id"], "version": candidate["version"],
            "content_digest": candidate["content_digest"], "observed_at_ms": at,
            "layers": copy.deepcopy(candidate["dag"]["layers"]),
            "topological_order": copy.deepcopy(candidate["dag"]["topological_order"]),
            "decision_dependencies": dependencies, "blockers": blockers,
            "claimable_task_ids": [], "execution_readiness": "unavailable", "authority": "proposal_only"}
