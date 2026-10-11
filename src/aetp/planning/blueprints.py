"""Blueprint and Task changes append proposals; formal apply stays unavailable."""

import copy

from aetp.collaboration.policy import PolicyViolation, text
from aetp.governance.policy import fields
from aetp.meetings.policy import natural
from aetp.planning.graphs import blueprint_content, impact
from aetp.planning.records import amount, append_version, risk
from aetp.planning.references import decisions, resolve


def transition(command, previous, state, at):
    if command.type == "blueprint.propose":
        if previous is not None:
            raise PolicyViolation("REVISION_CONFLICT")
        fields(command.payload, {"content", "source_decisions"}, {"content"})
        content, dag = blueprint_content(command.payload["content"], state, command.project_id, 1)
        sources = decisions(command.payload.get("source_decisions", []), state, command.project_id)
        record = append_version(command, None, content, at, sources=sources, details={"dag": dag, "change_request": None})
        record["change_requests"] = {}
        return "blueprint.proposed", record
    if previous is None:
        raise PolicyViolation("INVALID_TARGET")
    task_proposal = command.type == "task.propose"
    identifier_field, content_field = ("proposal_id", "task") if task_proposal else ("change_id", "content")
    required = {identifier_field, content_field, "base", "reason", "risk_level", "estimated_cost", "estimated_delay_ms"}
    fields(command.payload, required | {"source_decisions"}, required)
    old = resolve(command.payload["base"], state, command.project_id, "blueprint")
    if old["id"] != command.target_id:
        raise PolicyViolation("INVALID_REFERENCE")
    change_id = text(command.payload[identifier_field], identifier=True, limit=512)
    if change_id in previous["change_requests"]:
        raise PolicyViolation("PROPOSAL_ID_CONFLICT")
    reason = text(command.payload["reason"])
    declaration = {"risk_level": risk(command.payload["risk_level"]), "estimated_cost": amount(command.payload["estimated_cost"]),
                   "estimated_delay_ms": natural(command.payload["estimated_delay_ms"])}
    candidate_content = copy.deepcopy(old["content"]) if task_proposal else command.payload["content"]
    if task_proposal:
        candidate_content["tasks"].append(copy.deepcopy(command.payload["task"]))
    version = old["version"] + 1
    content, dag = blueprint_content(candidate_content, state, command.project_id, version)
    if content["mission"] != old["content"]["mission"]:
        raise PolicyViolation("INVALID_REFERENCE")
    sources = copy.deepcopy(old["source_decisions"])
    for source in decisions(command.payload.get("source_decisions", []), state, command.project_id):
        if source not in sources:
            sources.append(source)
    change = {"id": change_id, "kind": "task_proposal" if task_proposal else "blueprint_change_request",
              "base": copy.deepcopy(command.payload["base"]), "reason": reason, "status": "proposed",
              "route": "discussion_decision_approval", "approval_status": "not_requested",
              "impact": impact(old["content"], content, state, command.project_id, declaration)}
    record = append_version(command, previous, content, at, sources=sources,
                            details={"dag": dag, "change_request": change}, reason=reason)
    record["change_requests"][change_id] = {"version": version, "kind": change["kind"], "status": "proposed",
                                          "candidate_digest": record["versions"][str(version)]["content_digest"]}
    return "blueprint.task_proposed" if task_proposal else "blueprint.change_requested", record
