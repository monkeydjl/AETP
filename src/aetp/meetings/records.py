"""Immutable process inputs; lifecycle snapshots are validated by the pure reducer."""

import copy
import re
from dataclasses import dataclass

from aetp.collaboration.messages import participant
from aetp.collaboration.policy import PolicyViolation, digest_value, strings, text
from aetp.domain.models import ModelValidationError, VersionedModel, _freeze_json_value
from aetp.meetings.contracts import POLICY_VERSION
from aetp.meetings.policy import evidence_refs, natural, payload, policy, termination


@dataclass(frozen=True, slots=True)
class Contribution(VersionedModel):
    id: str
    project_id: str
    conversation_type: str
    conversation_id: str
    author_id: str
    category: str
    content: str
    position: str | None = None
    references: tuple = ()
    evidence: tuple = ()
    context: str = ""

    def __post_init__(self):
        try:
            for field in ("id", "project_id", "conversation_id", "author_id"):
                text(getattr(self, field), identifier=True, limit=512)
            if self.conversation_type not in {"discussion", "meeting"} or self.category not in {
                "analysis", "opinion", "evidence", "inference", "recommendation", "question",
                "challenge", "agreement", "disagreement", "clarification",
            }:
                raise PolicyViolation("INVALID_PAYLOAD")
            text(self.content)
            if self.position is not None:
                text(self.position, limit=512)
            object.__setattr__(self, "references", tuple(strings(self.references)))
            if not isinstance(self.evidence, (tuple, list)) or len(self.evidence) > 32:
                raise PolicyViolation("INVALID_PAYLOAD")
            object.__setattr__(self, "evidence", tuple(_freeze_json_value(ref) for ref in self.evidence))
            if not isinstance(self.context, str) or len(self.context.encode("utf-8")) > 65536:
                raise PolicyViolation("INVALID_PAYLOAD")
        except (PolicyViolation, UnicodeError, TypeError) as exc:
            raise ModelValidationError("invalid Contribution") from exc

    def digest(self):
        return digest_value(self.to_versioned_dict())


def summarize(rows, participants):
    positions, evidence = {}, []
    for row in rows:
        if row["position"] is not None:
            positions[row["author_id"]] = row["position"]
        for ref in row["evidence"]:
            if ref not in evidence:
                evidence.append(ref)
    peak = max((list(positions.values()).count(choice) for choice in positions.values()), default=0)
    return {"messages": len(rows), "tokens": sum(row["receipt"]["tokens"] for row in rows),
            "digest": digest_value(rows),
            "analysis_authors": sorted({row["author_id"] for row in rows if row["category"] == "analysis"}),
            "evidence": evidence, "consensus_peak": peak / len(participants)}


def validate_checkpoint_prefixes(record, rows):
    """Reconcile material against every commitment derived from lifecycle facts."""
    history = record.get("checkpoint_history")
    if not isinstance(history, list) or not history or history[-1] != record["checkpoint"]:
        raise PolicyViolation("PROCESS_UNRECONCILED")
    for checkpoint in history:
        count = checkpoint["messages"]
        if count > len(rows) or summarize(rows[:count], record["participants"]) != checkpoint:
            raise PolicyViolation("PROCESS_UNRECONCILED")


def validate_checkpoint(stats, previous, participants, budget, state):
    if not isinstance(stats, dict) or set(stats) != {
            "messages", "tokens", "digest", "analysis_authors", "evidence", "consensus_peak"}:
        raise PolicyViolation("INVALID_CHECKPOINT")
    messages, tokens = natural(stats["messages"]), natural(stats["tokens"])
    if not messages <= tokens <= budget or (messages == 0) != (tokens == 0):
        raise PolicyViolation("INVALID_CHECKPOINT")
    if not isinstance(stats["digest"], str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", stats["digest"]):
        raise PolicyViolation("INVALID_CHECKPOINT")
    authors = strings(stats["analysis_authors"])
    if authors != sorted(authors) or not set(authors) <= set(participants) or len(authors) > messages:
        raise PolicyViolation("INVALID_CHECKPOINT")
    # The 32-reference cap applies per Contribution, not to the whole process.
    evidence = stats["evidence"]
    if (not isinstance(evidence, (list, tuple)) or len(evidence) > 32 * messages
            or len({digest_value(ref) for ref in evidence}) != len(evidence)):
        raise PolicyViolation("INVALID_CHECKPOINT")
    for ref in evidence:
        evidence_refs([ref], state)
    peak = stats["consensus_peak"]
    if (type(peak) not in {float, int}
            or peak not in {count / len(participants) for count in range(min(messages, len(participants)) + 1)}):
        raise PolicyViolation("INVALID_CHECKPOINT")
    if messages == 0 and stats != summarize([], participants):
        raise PolicyViolation("INVALID_CHECKPOINT")
    if previous:
        if messages < previous["messages"] or tokens < previous["tokens"]:
            raise PolicyViolation("INVALID_CHECKPOINT")
        if messages == previous["messages"] and stats != previous:
            raise PolicyViolation("INVALID_CHECKPOINT")
        if (not set(previous["analysis_authors"]) <= set(authors)
                or any(ref not in stats["evidence"] for ref in previous["evidence"])):
            raise PolicyViolation("INVALID_CHECKPOINT")


def require_member(state, project_id, actor):
    project = state.get(f"project:{project_id}")
    if project is None:
        raise PolicyViolation("INVALID_TARGET")
    if not participant(state, actor):
        raise PolicyViolation("PERMISSION_DENIED")
    if project.get("status") not in {"planning", "active", "paused"}:
        raise PolicyViolation("PROJECT_INACTIVE")
    return project


def create_conversation(command, state, meter_source, at, elapsed):
    kind = command.type.split(".")[0]
    project = require_member(state, command.project_id, command.actor_id)
    if project["status"] == "paused":
        raise PolicyViolation("PROJECT_PAUSED")
    if f"{kind}:{command.target_id}" in state or command.expected_revision not in (None, 0):
        raise PolicyViolation("REVISION_CONFLICT")
    payload(command.payload, {"topic", "participants", "moderator_id", "policy"} |
            ({"objective"} if kind == "meeting" else set()))
    participants = strings(command.payload.get("participants"), required=True)
    if command.actor_id not in participants or any(not participant(state, actor) for actor in participants):
        raise PolicyViolation("INVALID_PARTICIPANT")
    moderator = command.payload.get("moderator_id", command.actor_id)
    if moderator not in participants:
        raise PolicyViolation("INVALID_PARTICIPANT")
    rules = policy(command.payload.get("policy", {}), kind)
    topic = text(command.payload.get("topic"), limit=512)
    objective = text(command.payload.get("objective"), limit=4096) if kind == "meeting" else None
    if meter_source is None:
        raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
    text(meter_source, identifier=True, limit=512)
    started = elapsed if kind == "discussion" else None
    return {"id": command.target_id, "project_id": command.project_id, "kind": kind,
            "revision": 0, "status": "open" if kind == "discussion" else "created",
            "topic": topic, "objective": objective, "participants": participants,
            "moderator_id": moderator, "created_by": command.actor_id,
            "policy_version": POLICY_VERSION, "policy": rules, "meter_source": meter_source,
            "origin_command_id": command.id, "last_command_id": command.id, "last_actor_id": command.actor_id,
            "observed_at_ms": at, "governance_at_ms": elapsed, "started_at_ms": started,
            "deadline_ms": started + rules["time_budget_ms"] if started is not None else None,
            "round": 0, "completed_rounds": 0, "no_new_evidence": 0, "evidence_seen": [],
            "termination_reason": None, "decision_id": None, "checkpoint": summarize([], participants)}


def proposal_link(previous, identifier, state):
    text(identifier, identifier=True)
    decision = state.get(f"decision:{identifier}")
    source = decision.get("source") if decision else None
    if (not source or source["kind"] != previous["kind"] or source["id"] != previous["id"]
            or source["revision"] != previous["revision"]
            or source["checkpoint"] != previous["checkpoint"] or decision["status"] not in {
                "proposed", "reviewing", "pending_approval", "approved", "active", "rejected"}):
        raise PolicyViolation("INVALID_REFERENCE")
    return identifier


def step_conversation(command, previous, stats, state, at, elapsed):
    project = require_member(state, command.project_id, command.actor_id)
    if command.actor_id not in previous["participants"]:
        raise PolicyViolation("PERMISSION_DENIED")
    if command.expected_revision != previous["revision"]:
        raise PolicyViolation("REVISION_CONFLICT")
    if at < previous["observed_at_ms"] or elapsed < previous["governance_at_ms"]:
        raise PolicyViolation("CLOCK_REGRESSION")
    kind, action = command.type.split(".")
    if kind != previous["kind"]:
        raise PolicyViolation("INVALID_TARGET")
    allowed = {"reason"} if action == "synthesize" else (
        {"decision_id"} if action in {"advance", "close"} else set())
    payload(command.payload, allowed)
    validate_checkpoint(stats, previous["checkpoint"], previous["participants"],
                        previous["policy"]["token_budget"], state)
    updated = copy.deepcopy(previous)
    # This history is a Projection index of earlier Event checkpoints. Keep
    # the existing authoritative Event format; the reducer derives it again.
    updated.pop("checkpoint_history", None)
    updated.update(revision=previous["revision"] + 1, observed_at_ms=at, governance_at_ms=elapsed,
                   last_command_id=command.id, last_actor_id=command.actor_id, checkpoint=copy.deepcopy(stats))
    status = previous["status"]
    active = {"open"} if kind == "discussion" else {"open", "individual_analysis", "debate"}
    reason = termination(previous, stats, elapsed) if status in active else None
    if action in {"tick", "synthesize"}:
        if status not in active:
            raise PolicyViolation("INVALID_PHASE")
        if action == "synthesize":
            if command.actor_id != previous["moderator_id"]:
                raise PolicyViolation("PERMISSION_DENIED")
            if command.payload.get("reason") != "moderator_decision":
                raise PolicyViolation("INVALID_PAYLOAD")
            reason = reason or "moderator_decision"
        if reason is None:
            raise PolicyViolation("NO_TERMINATION_CONDITION")
    elif action == "open" and kind == "meeting":
        if status != "created":
            raise PolicyViolation("INVALID_PHASE")
        if project["status"] == "paused":
            raise PolicyViolation("PROJECT_PAUSED")
        updated.update(status="open", started_at_ms=elapsed,
                       deadline_ms=elapsed + previous["policy"]["time_budget_ms"])
    elif action == "advance" and kind == "meeting":
        if status == "synthesis":
            updated.update(status="decision_proposed", decision_id=proposal_link(previous,
                           command.payload.get("decision_id"), state))
        elif status in {"open", "individual_analysis", "debate"}:
            if command.payload:
                payload(command.payload, set())
            if not reason:
                if project["status"] == "paused":
                    raise PolicyViolation("PROJECT_PAUSED")
                if status == "open":
                    updated["status"] = "individual_analysis"
                elif status == "individual_analysis":
                    if set(stats["analysis_authors"]) != set(previous["participants"]):
                        raise PolicyViolation("ANALYSIS_INCOMPLETE")
                    updated.update(status="debate", round=1, evidence_seen=copy.deepcopy(stats["evidence"]))
                    reason = termination(updated, stats, elapsed)
                else:
                    new_evidence = any(ref not in previous["evidence_seen"] for ref in stats["evidence"])
                    updated.update(completed_rounds=previous["completed_rounds"] + 1,
                                   no_new_evidence=0 if new_evidence else previous["no_new_evidence"] + 1,
                                   evidence_seen=copy.deepcopy(stats["evidence"]))
                    reason = termination(updated, stats, elapsed)
                    if not reason:
                        updated["round"] += 1
        else:
            raise PolicyViolation("INVALID_PHASE")
    elif action == "close":
        if kind == "discussion" and status == "synthesizing":
            updated["decision_id"] = proposal_link(previous, command.payload.get("decision_id"), state)
        elif kind == "meeting" and status == "decision_proposed":
            payload(command.payload, set())
        else:
            raise PolicyViolation("INVALID_PHASE")
        updated["status"] = "closed"
    else:
        raise PolicyViolation("INVALID_PHASE")
    if reason:
        updated.update(status="synthesizing" if kind == "discussion" else "synthesis", termination_reason=reason)
    if status in {"synthesizing", "synthesis", "decision_proposed"} and stats != previous["checkpoint"]:
        raise PolicyViolation("PROCESS_UNRECONCILED")
    return updated


def event_type(command, record):
    if record["status"] in {"synthesizing", "synthesis"}:
        return f"{record['kind']}.synthesizing"
    return {"discussion.open": "discussion.started", "discussion.close": "discussion.closed",
            "meeting.create": "meeting.created", "meeting.open": "meeting.started",
            "meeting.advance": "meeting.advanced", "meeting.close": "meeting.completed"}[command.type]
