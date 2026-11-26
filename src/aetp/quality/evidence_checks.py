"""Validate stored Verification evidence for use, separately from dispatch grants."""

import json

from aetp.acceptance.contracts import SCHEMA as ACCEPTANCE_SCHEMA
from aetp.acceptance.contracts import report_id, system_actor
from aetp.acceptance.records import (
    _observation,
    _quality,
    _runner_descriptor,
    require,
    target_snapshot,
)
from aetp.acceptance.runner import normalize_cases
from aetp.collaboration.policy import (
    POLICY_VERSION,
    canonical_json,
    digest_text,
    digest_value,
)
from aetp.governance.policy import current, principal, route


def verification_use(record, state, task, cycle, at, context):
    require(record.get("schema") == ACCEPTANCE_SCHEMA
            and record["project_id"] == task["project_id"] and record["task_id"] == task["id"], "EVIDENCE_STALE")
    target = target_snapshot(state, record["artifact_id"], record["artifact_digest"])
    require(canonical_json(target) == canonical_json(record["input"]), "EVIDENCE_STALE")
    reviewer = state[f"review:{cycle['reviews'][record['artifact_id']]}"]["reviewer_id"]
    require(record["verifier_id"] == reviewer and reviewer != task["owner_id"], "REVIEWER_MISMATCH")
    require(principal(state, task["project_id"], reviewer)["type"] == "agent", "PERMISSION_DENIED")
    grant, action = record["grant"], record["action"]
    require(grant["revoked"] is False, "GRANT_REVOKED")
    governance, policy = current(state, task["project_id"])
    require(governance["current_version"] == grant["governance_version"]
            and digest_value(policy) == grant["governance_digest"], "GOVERNANCE_CHANGED")
    require(canonical_json(_quality(state, task["project_id"])) == canonical_json(grant["quality"]), "QUALITY_POLICY_CHANGED")
    require(grant["source"]["untrusted_input"] is False, "SOURCE_UNVERIFIED")
    source = state[f"artifact:{record['artifact_id']}"]["source"]
    inherited = [entry for entry in grant["source"].get("derived_sources", [])
                 if entry.get("type") == "artifact" and entry.get("id") == record["artifact_id"]]
    require(len(inherited) == 1 and inherited[0]["content_digest"] == record["artifact_digest"]
            and inherited[0]["source_digest"] == digest_value(source)
            and canonical_json(inherited[0]["source"]) == canonical_json(source), "SOURCE_UNVERIFIED")
    routing = route(policy, "verification.execute", grant["requested_risk"], grant["source"]["untrusted_input"])
    require(routing["risk_level"] == "low" and routing["mode"] == "auto"
            and canonical_json(routing) == canonical_json(grant["routing"]), "APPROVAL_REQUIRED")
    require(canonical_json(_runner_descriptor(context.get("runner"))) == canonical_json(record["runner"]), "RUNNER_CHANGED")
    cases = normalize_cases(record["case_set"]["cases"], target["criteria"])
    require(record["case_set"]["author_id"] == reviewer and record["case_set"]["content_digest"] == digest_value(cases),
            "EVIDENCE_STALE")
    execution, session = grant["execution"], grant["execution"]["session"]
    require(execution["exec_task_id"] != task["id"] and execution["actor_id"] == reviewer
            and session["actor_id"] == reviewer and session["project_id"] == task["project_id"]
            and session["task_id"] == execution["exec_task_id"] and session["id"] == execution["session_id"]
            and session["binding_id"] == execution["binding_id"] and session["lease_epoch"] == execution["lease_epoch"]
            and execution["workspace_provider_id"] == cycle["execution"]["workspace_provider_id"], "EVIDENCE_STALE")
    require(type(action["dispatch_count"]) is int and action["dispatch_count"] in {0, 1}, "EVIDENCE_STALE")
    if record["status"] != "finished":
        require(record["status"] in {"pending", "running"} and action["status"] in {"pending", "in_flight"}
                and record["result"] is None and record["evidence_id"] is None, "EVIDENCE_STALE")
        require(at < grant["expires_at_ms"], "GRANT_EXPIRED")
        return {"id": record["id"], "record_digest": digest_value(record), "result": "INCONCLUSIVE",
                "action_status": action["status"], "evidence_id": None, "evidence_digest": None}
    _historical_report(record, state)
    finished = action["finished_at_ms"]
    require(type(finished) is int and grant["issued_at_ms"] <= finished <= at, "EVIDENCE_STALE")
    require(at - finished <= cycle["policy"]["policy"]["max_evidence_age_ms"], "EVIDENCE_EXPIRED")
    if record["result"] in {"PASSED", "FAILED"}:
        require(action["status"] == "completed" and action["dispatch_count"] == 1
                and type(action["started_at_ms"]) is int
                and grant["issued_at_ms"] <= action["started_at_ms"] <= finished
                and finished < grant["expires_at_ms"] and finished < session["expires_at_wall_ms"], "EVIDENCE_STALE")
    # Current QA Session, Task status and dispatch TTL are intentionally not
    # consulted here. Their original authorization was committed with the run.
    return {"id": record["id"], "record_digest": digest_value(record), "result": record["result"],
            "action_status": action["status"], "evidence_id": record["evidence_id"],
            "evidence_digest": record["evidence_digest"], "finished_at_ms": finished,
            "age_ms": at - finished, "runner_digest": digest_value(record["runner"]),
            "case_set_digest": record["case_set"]["content_digest"], "execution": execution}


def _historical_report(record, state):
    action = record["action"]
    identifier = report_id(record["project_id"], record["id"])
    evidence = state.get(f"artifact:{identifier}")
    require(evidence is not None and record["evidence_id"] == identifier
            and evidence["content_digest"] == record["evidence_digest"] == digest_text(evidence["content"]), "EVIDENCE_STALE")
    report = json.loads(evidence["content"])
    expected = {"schema": ACCEPTANCE_SCHEMA, "verification_id": record["id"], "project_id": record["project_id"],
        "action_id": action["id"], "grant_id": record["grant"]["id"], "request_command_id": action["request_command_id"],
        "dispatch_command_id": action["dispatch_command_id"], "record_command_id": action["finish_command_id"],
        "input": record["input"], "runner": record["runner"], "case_set": record["case_set"], "grant": record["grant"],
        "execution_outcome": report.get("execution_outcome"), "observation": report.get("observation"),
        "result": record["result"], "reason": record["reason"], "started_at_ms": action["started_at_ms"],
        "finished_at_ms": action["finished_at_ms"], "termination": report.get("termination"),
        "scope": "fixed_checks_only_no_task_or_mission_acceptance"}
    require(canonical_json(expected) == evidence["content"], "EVIDENCE_STALE")
    source = {"kind": "trusted_fixed_verification", "command_id": action["finish_command_id"],
        "verification_id": record["id"], "action_id": action["id"],
        "untrusted_input": record["grant"]["source"]["untrusted_input"], "input_source": record["grant"]["source"],
        "execution_authority": "fixed_single_use_grant"}
    expected_evidence = {"schema_version": "0.1", "id": identifier, "project_id": record["project_id"],
        "task_id": record["task_id"], "created_by": system_actor(record["project_id"]), "type": "report",
        "content": evidence["content"], "content_digest": evidence["content_digest"],
        "task_revision": record["input"]["task_revision"], "criteria": record["input"]["criteria"],
        "criteria_digest": record["input"]["criteria_digest"], "policy_version": POLICY_VERSION, "source": source,
        "derived_from": [record["artifact_id"]], "supersedes": None,
        "data_classification": state[f"artifact:{record['artifact_id']}"]["data_classification"], "revision": 0}
    require(canonical_json(evidence) == canonical_json(expected_evidence), "EVIDENCE_STALE")
    outcome, observation = report["execution_outcome"], report["observation"]
    require(outcome in {"completed", "not_executed", "runner_error", "recovered"}
            and record["result"] in {"PASSED", "FAILED", "INCONCLUSIVE"}, "EVIDENCE_STALE")
    if outcome == "completed":
        value = _observation(observation, record["case_set"]["cases"])
        require(action["status"] == "completed" and action["dispatch_count"] == 1, "EVIDENCE_STALE")
        if record["result"] != "INCONCLUSIVE":
            require(record["result"] == value["observed_result"] and record["reason"] == value["diagnostic"], "EVIDENCE_STALE")
    else:
        require(observation is None and record["result"] == "INCONCLUSIVE"
                and action["status"] == ("cancelled" if outcome == "not_executed" else "abandoned"), "EVIDENCE_STALE")
        if outcome == "recovered":
            require(report["termination"] == "exclusive_gate_fixed_memory_runner_exited", "EVIDENCE_STALE")
