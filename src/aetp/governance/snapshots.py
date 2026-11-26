"""Two explicit target adapters; no arbitrary target or external execution grant."""

import copy

from aetp.collaboration.policy import (
    PolicyViolation,
    canonical_json,
    digest_value,
    text,
)
from aetp.governance.contracts import TARGET_TYPES
from aetp.governance.policy import fields
from aetp.meetings.policy import natural


def snapshot(state, kind, identifier):
    if not isinstance(kind, str) or kind not in TARGET_TYPES:
        raise PolicyViolation("INVALID_TARGET_TYPE")
    if kind not in {"decision", "task"}:
        raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
    text(identifier, identifier=True)
    record = state.get(f"{kind}:{identifier}")
    if record is None:
        raise PolicyViolation("INVALID_TARGET")
    if kind == "decision":
        version = record.get("proposal_revision", record["revision"])
        digest = record["content_digest"]
    else:
        if not record.get("execution_policy_version") or not record.get("current_binding_id"):
            raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
        version, digest = record["revision"], digest_value(record)
    return {"type": kind, "id": identifier, "revision": version, "content_digest": digest,
            "revision_kind": "proposal" if kind == "decision" else "aggregate"}


def target_record(state, target):
    fields(target, {"type", "id", "revision", "content_digest", "revision_kind"},
           {"type", "id", "revision", "content_digest", "revision_kind"})
    expected = snapshot(state, target["type"], target["id"])
    if canonical_json(expected) != canonical_json(target):
        raise PolicyViolation("APPROVAL_STALE")
    return state[f"{target['type']}:{target['id']}"]


def arguments(state, target, action, value, actor):
    record = target_record(state, target)
    if target["type"] == "decision":
        if action != "decision.activate":
            raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
        fields(value, {"choice"}, {"choice"})
        if value["choice"] != record["choice"]:
            raise PolicyViolation("APPROVAL_STALE")
        return copy.deepcopy(value)
    if action not in {"document.write", "document.append", "document.restore"}:
        raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
    fields(value, {"document", "binding_id", "lease_epoch", "session_id"},
           {"document", "binding_id", "lease_epoch", "session_id"})
    natural(value["lease_epoch"])
    if record.get("owner_id") != actor:
        raise PolicyViolation("PERMISSION_DENIED")
    binding = record["bindings"].get(record["current_binding_id"], {})
    session = binding.get("session")
    if (record["status"] != "in_progress" or record["lease"] is None or record["lease"]["revoked"]
            or session is None or value["binding_id"] != record["current_binding_id"]
            or value["lease_epoch"] != record["lease_epoch"] or value["session_id"] != session["id"]):
        raise PolicyViolation("STALE_EXECUTION")
    from aetp.runtime.records import normalize_arguments
    normalized = normalize_arguments(action, value["document"], record, state)
    return {"operation": action, "arguments": normalized, "binding_id": value["binding_id"],
            "lease_epoch": value["lease_epoch"], "session_id": value["session_id"]}
