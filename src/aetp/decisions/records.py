"""Deterministic proposal assembly, never automated technical decision-making."""

import copy

from aetp.collaboration.policy import PolicyViolation, canonical_json, digest_value, strings, text
from aetp.meetings.contracts import POLICY_VERSION
from aetp.meetings.policy import evidence_refs, natural, payload
from aetp.meetings.records import Contribution, require_member, summarize, validate_checkpoint_prefixes


def source_reference(value, state, actor):
    if not isinstance(value, dict) or set(value) != {"kind", "id", "revision"}:
        raise PolicyViolation("INVALID_REFERENCE")
    if value["kind"] not in {"discussion", "meeting"}:
        raise PolicyViolation("INVALID_REFERENCE")
    text(value["id"], identifier=True)
    natural(value["revision"])
    source = state.get(f"{value['kind']}:{value['id']}")
    if not source or actor not in source["participants"]:
        raise PolicyViolation("INVALID_REFERENCE")
    # Readiness is checked before revisions so failures never expose private material.
    if source["status"] not in {"synthesizing", "synthesis"}:
        raise PolicyViolation("SOURCE_NOT_READY")
    if source["revision"] != value["revision"]:
        raise PolicyViolation("REVISION_CONFLICT")
    return source


def freeze_source(source, rows, state):
    """Validate the complete fixed material and retain all authenticated attributions."""
    seen, calls = {}, set()
    last_time = 0
    for row in rows:
        fields = {field: row[field] for field in Contribution.__dataclass_fields__}
        entry = Contribution.from_dict(fields)
        receipt = row["receipt"]
        if (set(row) != set(fields) | {"semantic_digest", "phase", "round", "observed_at_ms", "untrusted_input", "receipt"}
                or entry.project_id != source["project_id"] or entry.conversation_type != source["kind"]
                or entry.conversation_id != source["id"] or entry.author_id not in source["participants"]
                or entry.id in seen or row["semantic_digest"] != entry.digest() or row["untrusted_input"] is not True):
            raise PolicyViolation("INVALID_SOURCE")
        if (not isinstance(receipt, dict) or set(receipt) != {"receipt_id", "source_id", "call_id", "subject_digest", "tokens", "purpose", "unit"}
                or receipt["subject_digest"] != entry.digest() or receipt["source_id"] != source["meter_source"]
                or receipt["purpose"] != "process_admission" or receipt["unit"] != "token"):
            raise PolicyViolation("INVALID_SOURCE")
        for field in ("receipt_id", "source_id", "call_id"):
            text(receipt[field], identifier=True, limit=512)
        natural(receipt["tokens"], 1000000, positive=True)
        call = (receipt["source_id"], receipt["call_id"])
        if call in calls:
            raise PolicyViolation("INVALID_SOURCE")
        calls.add(call)
        at, round_number = natural(row["observed_at_ms"]), natural(row["round"])
        if not last_time <= at <= source["observed_at_ms"] or round_number > source["round"]:
            raise PolicyViolation("INVALID_SOURCE")
        last_time = at
        phase = row["phase"]
        if source["kind"] == "discussion":
            if phase != "open" or round_number != 0:
                raise PolicyViolation("INVALID_SOURCE")
        elif phase not in {"individual_analysis", "debate"}:
            raise PolicyViolation("INVALID_SOURCE")
        elif phase == "individual_analysis" and (entry.category != "analysis" or round_number != 0 or any(
                old["author_id"] == entry.author_id and old["phase"] == phase for old in seen.values())):
            raise PolicyViolation("INVALID_SOURCE")
        elif phase == "debate" and round_number < 1:
            raise PolicyViolation("INVALID_SOURCE")
        for ref in entry.references:
            if ref not in seen or (phase == "individual_analysis" and seen[ref]["author_id"] != entry.author_id):
                raise PolicyViolation("INVALID_SOURCE")
        evidence_refs(entry.evidence, state)
        seen[entry.id] = row
    validate_checkpoint_prefixes(source, rows)
    if summarize(rows, source["participants"]) != source["checkpoint"]:
        raise PolicyViolation("PROCESS_UNRECONCILED")
    return {"kind": source["kind"], "id": source["id"], "revision": source["revision"],
            "participants": copy.deepcopy(source["participants"]), "checkpoint": copy.deepcopy(source["checkpoint"]),
            "termination_reason": source["termination_reason"], "records": copy.deepcopy(rows),
            "untrusted_input": True, "metering_scope": "process_admission"}


def assemble(command, state, snapshot):
    require_member(state, command.project_id, command.actor_id)
    if f"decision:{command.target_id}" in state or command.expected_revision not in (None, 0):
        raise PolicyViolation("REVISION_CONFLICT")
    payload(command.payload, {"title", "choice", "alternatives", "reasoning", "risk_level", "source", "supersedes"})
    title = text(command.payload.get("title"), limit=512)
    choice = text(command.payload.get("choice"), limit=512)
    alternatives = strings(command.payload.get("alternatives"), required=True)
    if choice not in alternatives:
        raise PolicyViolation("INVALID_PAYLOAD")
    reasoning = text(command.payload.get("reasoning"))
    risk = command.payload.get("risk_level", "low")
    if risk not in {"low", "medium", "high", "critical"}:
        raise PolicyViolation("INVALID_PAYLOAD")
    requested_source = command.payload.get("source")
    if requested_source is not None:
        source = source_reference(requested_source, state, command.actor_id)
        if not isinstance(snapshot, dict):
            raise PolicyViolation("INVALID_SOURCE")
        expected = freeze_source(source, snapshot.get("records", []), state)
        if canonical_json(expected) != canonical_json(snapshot):
            raise PolicyViolation("INVALID_SOURCE")
    elif snapshot is not None:
        raise PolicyViolation("INVALID_SOURCE")
    supersedes = command.payload.get("supersedes")
    if supersedes is not None:
        if not isinstance(supersedes, dict) or set(supersedes) != {"id", "digest"}:
            raise PolicyViolation("INVALID_REFERENCE")
        old = state.get(f"decision:{text(supersedes['id'], identifier=True)}")
        if old is None or supersedes["digest"] != old["content_digest"]:
            raise PolicyViolation("INVALID_REFERENCE")
    rows = snapshot["records"] if snapshot else []
    participants = snapshot["participants"] if snapshot else []
    positions = {}
    for row in rows:
        if row["position"] is not None:
            positions[row["author_id"]] = row["position"]
    supporting = sorted(actor for actor in participants if positions.get(actor) == choice)
    dissent = [row for row in rows if (row["position"] is not None and row["position"] != choice)
               or row["category"] in {"disagreement", "challenge"}]
    missing = sorted(set(participants) - {row["author_id"] for row in rows})
    unexpressed = sorted(set(participants) - positions.keys())
    record = {"id": command.target_id, "project_id": command.project_id, "revision": 0,
              "status": "proposed", "title": title, "choice": choice, "alternatives": alternatives,
              "reasoning": reasoning, "risk_level": risk, "proposed_by": command.actor_id,
              "origin_command_id": command.id, "policy_version": POLICY_VERSION,
              "authority": "proposal_only", "untrusted_input": True,
              "proposal_metering": "outside_process_admission", "source": copy.deepcopy(snapshot),
              "source_digest": digest_value(snapshot), "supersedes": copy.deepcopy(supersedes),
              "supporting_agents": supporting, "minority_opinions": copy.deepcopy(dissent),
              "missing_participants": missing, "unexpressed_participants": unexpressed,
              "concerns": copy.deepcopy([row for row in rows if row["category"] in {"disagreement", "challenge"}]),
              "unresolved": copy.deepcopy([row for row in rows if row["category"] in {"question", "challenge"}]),
              "consensus_level": len(supporting) / len(participants) if participants else None,
              "escalation": ["independent_review", "human_governance"] if (dissent or missing or unexpressed or risk != "low")
                            else ["independent_review"]}
    record["content_digest"] = digest_value(record)
    return record
