"""Explicit, same-project references to immutable proposal versions."""

import copy

from aetp.collaboration.policy import PolicyViolation, canonical_json, text
from aetp.governance.policy import fields
from aetp.meetings.policy import natural
from aetp.planning.contracts import AGGREGATES


def reference(candidate):
    return {"type": candidate["type"], "id": candidate["id"], "version": candidate["version"],
            "content_digest": candidate["content_digest"]}


def resolve(value, state, project_id, kind, *, latest=True):
    fields(value, {"type", "id", "version", "content_digest"}, {"type", "id", "version", "content_digest"})
    if value["type"] != kind or kind not in AGGREGATES:
        raise PolicyViolation("INVALID_REFERENCE")
    identifier = text(value["id"], identifier=True, limit=512)
    version = natural(value["version"], positive=True)
    record = state.get(f"{kind}:{identifier}")
    if record is None or record["project_id"] != project_id:
        raise PolicyViolation("INVALID_REFERENCE")
    candidate = record["versions"].get(str(version))
    if (candidate is None or canonical_json(reference(candidate)) != canonical_json(value)
            or (latest and version != record["latest_proposal_version"])):
        raise PolicyViolation("REFERENCE_STALE")
    return copy.deepcopy(candidate)


def decisions(values, state, project_id):
    if not isinstance(values, (list, tuple)) or len(values) > 32:
        raise PolicyViolation("INVALID_REFERENCE")
    result, seen = [], set()
    for value in values:
        fields(value, {"type", "id", "revision", "content_digest"}, {"type", "id", "revision", "content_digest"})
        if value["type"] != "decision":
            raise PolicyViolation("INVALID_REFERENCE")
        identifier = text(value["id"], identifier=True, limit=512)
        natural(value["revision"])
        record = state.get(f"decision:{identifier}")
        if record is None or record["project_id"] != project_id or identifier in seen:
            raise PolicyViolation("INVALID_REFERENCE")
        if (value["revision"] != record.get("proposal_revision", 0)
                or value["content_digest"] != record["content_digest"]):
            raise PolicyViolation("REFERENCE_STALE")
        seen.add(identifier)
        result.append({"reference": copy.deepcopy(value), "origin_command_id": record["origin_command_id"],
                       "source_digest": record["source_digest"], "untrusted_input": True,
                       "authority": "proposal_only"})
    return result
