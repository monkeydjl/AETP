"""Pure Approval transitions. Time and ingress attestations are recorded inputs."""

import copy

from aetp.collaboration.policy import (
    PolicyViolation,
    canonical_json,
    digest_value,
    text,
)
from aetp.governance.contracts import system_actor
from aetp.governance.policy import current, fields, has_role, principal, revision, route
from aetp.governance.snapshots import arguments, target_record
from aetp.governance.trust import inherit_document_sources, source_record
from aetp.meetings.policy import natural, projected_time
from aetp.runtime.contracts import child_id


def request(command, state, at, context):
    fields(command.payload, {"target", "action", "arguments", "ttl_ms", "risk_level", "on_expire", "renew_limit"},
           {"target", "action", "arguments", "ttl_ms"})
    if f"approval:{command.target_id}" in state:
        raise PolicyViolation("REVISION_CONFLICT")
    revision(command, None)
    governance, value = current(state, command.project_id)
    requester = principal(state, command.project_id, command.actor_id)
    target = command.payload["target"]
    record = target_record(state, target)
    normalized = arguments(state, target, command.payload["action"], command.payload["arguments"], command.actor_id)
    if target["type"] == "decision" and record["status"] not in {"pending_approval", "approved"}:
        raise PolicyViolation("DECISION_NOT_READY")
    source = source_record(command, context, governance["input_authority_id"])
    if target["type"] == "task":
        source = inherit_document_sources(source, normalized, state)
    if target["type"] == "decision" and record.get("untrusted_input", True):
        source["untrusted_input"] = True
        source["target_source"] = {"type": "decision", "id": record["id"], "source_digest": record["source_digest"],
                                    "untrusted_input": True}
    declared = command.payload.get("risk_level", "low")
    if target["type"] == "decision":
        from aetp.governance.contracts import RISKS
        if declared not in RISKS:
            raise PolicyViolation("INVALID_PAYLOAD")
        declared = RISKS[max(RISKS.index(declared), RISKS.index(record["risk_level"]))]
    routing = route(value, command.payload["action"], declared, source["untrusted_input"])
    if routing["mode"] == "delegated":
        delegate = routing["rule"]["delegate"]
        if delegate == command.actor_id or (target["type"] == "decision" and delegate == record["proposed_by"]):
            raise PolicyViolation("SELF_APPROVAL")
    ttl = natural(command.payload["ttl_ms"], value["max_ttl_ms"], positive=True)
    renew_limit = natural(command.payload.get("renew_limit", value["max_renewals"]), value["max_renewals"])
    on_expire = command.payload.get("on_expire", "escalate")
    if on_expire not in {"escalate", "reject", "renew"}:
        raise PolicyViolation("INVALID_PAYLOAD")
    elapsed = projected_time(state[f"project:{command.project_id}"], at)
    result = {"id": command.target_id, "project_id": command.project_id, "revision": 0, "status": "pending",
        "validity": "current", "target": copy.deepcopy(target), "scope": {"action": command.payload["action"],
        "arguments_digest": digest_value(normalized)}, "arguments": normalized, "requested_arguments": copy.deepcopy(command.payload["arguments"]),
        "policy_version": value["version"], "policy_digest": governance["versions"][value["version"]]["content_digest"],
        "requested_by": requester, "executor": copy.deepcopy(requester), "approver": None, "approved_by": None,
        "authority": {"type": "system" if routing["mode"] == "auto" else ("human" if routing["required_role"].startswith("human_") else "agent"),
                      "required_role": routing["required_role"]},
        "routing": routing, "risk_level": routing["risk_level"], "declared_risk": declared,
        "delegated_to": None, "revocable_until": None, "source": source, "ttl_ms": ttl,
        "requested_at": elapsed, "expires_at": elapsed + ttl, "on_expire": on_expire,
        "renew_limit": renew_limit, "renewal_count": 0, "renewed_from": None,
        "origin_command_id": command.id, "observed_at_ms": at, "last_actor_id": command.actor_id}
    result["request_digest"] = digest_value(result)
    return result


def valid_snapshot(record, state, at, *, require_approved=False):
    governance, value = current(state, record["project_id"])
    if (record["validity"] != "current" or record["policy_version"] != value["version"]
            or record["policy_digest"] != governance["versions"][value["version"]]["content_digest"]):
        raise PolicyViolation("APPROVAL_STALE")
    if record["status"] not in ({"approved"} if require_approved else {"pending", "approved"}):
        raise PolicyViolation("APPROVAL_FINAL" if not require_approved else "APPROVAL_REQUIRED")
    if projected_time(state[f"project:{record['project_id']}"], at) >= record["expires_at"]:
        raise PolicyViolation("APPROVAL_EXPIRED")
    target_record(state, record["target"])
    principal(state, record["project_id"], record["requested_by"]["id"])
    return value


def authorize(identifier, target, action, normalized, actor, state, at):
    """Live authorization, never inferred from an earlier Command result."""
    record = state.get(f"approval:{identifier}")
    if record is None:
        raise PolicyViolation("APPROVAL_REQUIRED")
    if record["executor"]["id"] != actor:
        raise PolicyViolation("PERMISSION_DENIED")
    if (canonical_json(record["target"]) != canonical_json(target) or record["scope"]["action"] != action
            or record["scope"]["arguments_digest"] != digest_value(normalized)
            or canonical_json(record["arguments"]) != canonical_json(normalized)):
        raise PolicyViolation("APPROVAL_STALE")
    valid_snapshot(record, state, at, require_approved=True)
    return record


def impact(previous, state, reason):
    target = previous["target"]
    actions = [{"id": value["id"], "status": value["status"], "result": copy.deepcopy(value.get("result"))}
               for key, value in state.items() if key.startswith("action:")
               and value.get("authorization", {}).get("approval_id") == previous["id"]]
    return {"reason": reason, "target": copy.deepcopy(target), "actions": actions,
            "external_effects_undone": False, "replanning_required": True,
            "followup": "new_review_and_approval; reconcile_unknown_actions"}


def expiration_resolution(previous, state):
    route_kind = previous["on_expire"]
    reason = "deadline_reached"
    if route_kind == "renew":
        if previous["renewal_count"] >= previous["renew_limit"]:
            route_kind, reason = "escalate", "renewal_limit"
        else:
            try:
                governance, value = current(state, previous["project_id"])
                if previous["validity"] != "current" or previous["policy_version"] != value["version"]:
                    raise PolicyViolation("APPROVAL_STALE")
                target_record(state, previous["target"])
                principal(state, previous["project_id"], previous["requested_by"]["id"])
            except PolicyViolation:
                route_kind, reason = "escalate", "snapshot_stale"
    resolution = {"kind": route_kind, "reason": reason}
    if route_kind == "renew":
        resolution["next_approval_id"] = child_id("approval-renewal", previous["project_id"], previous["id"])
    return resolution


def renew(command, state, at):
    fields(command.payload, {"previous_id", "previous_revision"}, {"previous_id", "previous_revision"})
    if f"approval:{command.target_id}" in state:
        raise PolicyViolation("REVISION_CONFLICT")
    revision(command, None)
    previous = state.get(f"approval:{command.payload['previous_id']}")
    if (previous is None or previous["revision"] != command.payload["previous_revision"] or previous["status"] != "expired"
            or previous.get("expiration_resolution", {}).get("next_approval_id") != command.target_id
            or expiration_resolution(previous, state)["kind"] != "renew"):
        raise PolicyViolation("APPROVAL_STALE")
    elapsed = projected_time(state[f"project:{command.project_id}"], at)
    updated = copy.deepcopy(previous)
    for field in ("request_digest", "expiration_resolution", "impact", "escalation", "decision_reason", "decided_by"):
        updated.pop(field, None)
    updated.update(id=command.target_id, revision=0, status="pending", validity="current", approver=None, approved_by=None,
                   delegated_to=None, revocable_until=None, requested_at=elapsed, expires_at=elapsed + previous["ttl_ms"],
                   renewal_count=previous["renewal_count"] + 1, renewed_from=previous["id"],
                   original_request_command_id=previous.get("original_request_command_id", previous["origin_command_id"]),
                   origin_command_id=command.id, observed_at_ms=at, last_actor_id=command.actor_id)
    updated["request_digest"] = digest_value(updated)
    return updated


def _grant_authority(command, previous, state, value, context):
    actor = principal(state, command.project_id, command.actor_id, internal=context.get("internal") is True)
    target = target_record(state, previous["target"])
    if command.actor_id == previous["requested_by"]["id"] or (
            previous["target"]["type"] == "decision" and command.actor_id == target["proposed_by"]):
        raise PolicyViolation("SELF_APPROVAL")
    mode = previous["routing"]["mode"]
    if mode == "auto":
        if actor != {"type": "system", "id": system_actor(command.project_id)} or previous["source"]["untrusted_input"]:
            raise PolicyViolation("PERMISSION_DENIED")
    elif previous["delegated_to"]:
        if actor != previous["delegated_to"] or not has_role(value, command.actor_id, previous["authority"]["required_role"]):
            raise PolicyViolation("PERMISSION_DENIED")
    elif not (has_role(value, command.actor_id, previous["authority"]["required_role"])
              or (previous["authority"]["required_role"] == "agent_reviewer" and actor["type"] == "human"
                  and has_role(value, command.actor_id, "human_collaborator"))):
        raise PolicyViolation("PERMISSION_DENIED")
    return actor


def transition(command, previous, state, at, context):
    if command.type == "approval.request":
        return "approval.requested", request(command, state, at, context)
    if command.type == "approval.renew":
        return "approval.requested", renew(command, state, at)
    if previous is None:
        raise PolicyViolation("INVALID_TARGET")
    revision(command, previous)
    updated = copy.deepcopy(previous)
    updated.update(revision=previous["revision"] + 1, observed_at_ms=at, last_actor_id=command.actor_id)
    if command.type == "approval.expire":
        fields(command.payload, set())
        if previous["status"] not in {"pending", "approved"}:
            raise PolicyViolation("APPROVAL_FINAL")
        if projected_time(state[f"project:{command.project_id}"], at) < previous["expires_at"]:
            raise PolicyViolation("APPROVAL_NOT_EXPIRED")
        updated.update(status="expired", expiration_resolution=expiration_resolution(previous, state),
                       impact=impact(previous, state, "approval_expired"))
        return "approval.expired", updated
    if command.type == "approval.escalate":
        fields(command.payload, {"reason"}, {"reason"})
        if previous.get("escalation") or not (previous["status"] == "revoked" or (
                previous["status"] == "expired" and previous["expiration_resolution"]["kind"] == "escalate")):
            raise PolicyViolation("INVALID_TRANSITION")
        governance, value = current(state, command.project_id)
        updated["escalation"] = {"reason": text(command.payload["reason"]), "notification_level": "urgent",
                                 "route": {"type": "human", "required_role": "human_owner", "id": governance["owner_id"]}}
        return "approval.escalated", updated
    if command.type == "approval.revoke":
        fields(command.payload, {"reason", "mode"}, {"reason", "mode"})
        governance, value = current(state, command.project_id)
        if command.actor_id != governance["owner_id"]:
            raise PolicyViolation("PERMISSION_DENIED")
        if previous["status"] not in {"pending", "approved"}:
            raise PolicyViolation("APPROVAL_FINAL")
        if command.payload["mode"] not in {"veto", "safety"}:
            raise PolicyViolation("INVALID_PAYLOAD")
        if command.payload["mode"] == "veto" and (previous["delegated_to"] is None
                or previous["revocable_until"] is None
                or projected_time(state[f"project:{command.project_id}"], at) >= previous["revocable_until"]):
            raise PolicyViolation("VETO_WINDOW_CLOSED")
        updated.update(status="revoked", revocation={"by": {"type": "human", "id": command.actor_id},
                       "reason": text(command.payload["reason"]), "mode": command.payload["mode"]},
                       impact=impact(previous, state, "approval_revoked"))
        return "approval.revoked", updated
    if command.type == "approval.delegate":
        fields(command.payload, set())
        if previous["status"] != "pending" or previous["routing"]["mode"] != "delegated" or previous["delegated_to"] is not None:
            raise PolicyViolation("APPROVAL_FINAL")
        governance, value = current(state, command.project_id)
        delegate = previous["routing"]["rule"]["delegate"]
        updated["delegated_to"] = principal(state, command.project_id, delegate)
        updated["approver"] = {"type": "human", "id": governance["owner_id"]}
        return "approval.delegated", updated
    if command.type == "approval.invalidate":
        fields(command.payload, {"reason"}, {"reason"})
        governance, value = current(state, command.project_id)
        if previous["policy_version"] == value["version"] or previous["validity"] != "current":
            raise PolicyViolation("INVALID_TRANSITION")
        updated.update(validity="invalidated", invalidated_reason=text(command.payload["reason"]),
                       reassessed_policy_version=value["version"], reapply_required=True)
        return "approval.invalidated", updated
    if command.type in {"approval.grant", "approval.deny"}:
        fields(command.payload, {"reason"}, {"reason"})
        text(command.payload["reason"])
        if previous["status"] != "pending":
            raise PolicyViolation("APPROVAL_FINAL")
        value = valid_snapshot(previous, state, at)
        actor = _grant_authority(command, previous, state, value, context)
        if command.type == "approval.grant" and previous["target"]["type"] == "task" and state[f"project:{command.project_id}"]["status"] == "paused":
            raise PolicyViolation("PROJECT_PAUSED")
        updated.update(status="approved" if command.type == "approval.grant" else "rejected",
                       approved_by=actor if command.type == "approval.grant" else None,
                       decided_by=actor, decision_reason=command.payload["reason"])
        if previous["delegated_to"] is None:
            updated["approver"] = actor
        if previous["delegated_to"] and command.type == "approval.grant":
            updated["revocable_until"] = projected_time(state[f"project:{command.project_id}"], at) + previous["routing"]["rule"]["revocable_within_ms"]
        return "approval.granted" if command.type == "approval.grant" else "approval.denied", updated
    raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
