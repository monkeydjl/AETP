"""Deterministic Verification transitions. No Runtime activation or Runner IO."""

import copy

from aetp.acceptance.contracts import (
    MAX_CASE_BYTES,
    MAX_CASES,
    MAX_DEPTH,
    MAX_DOCUMENT_BYTES,
    MAX_PATH,
    RUNNER_ID,
    SCHEMA,
    report_id,
    system_actor,
)
from aetp.acceptance.runner import normalize_cases
from aetp.collaboration.messages import participant
from aetp.collaboration.policy import (
    POLICY_VERSION,
    PolicyViolation,
    canonical_json,
    digest_text,
    digest_value,
    text,
)
from aetp.collaboration.records import Artifact
from aetp.governance.policy import current, fields, principal, revision, route
from aetp.governance.trust import source_record
from aetp.meetings.policy import natural
from aetp.planning.guards import candidate_scope
from aetp.runtime.contracts import POLICY_VERSION as EXECUTION_POLICY
from aetp.runtime.contracts import child_id
from aetp.runtime.policy import governance, observed_time
from aetp.runtime.records import receipt


def require(condition, code):
    if not condition:
        raise PolicyViolation(code)


def executable_project(state, project_id):
    project = state.get(f"project:{project_id}")
    require(project is not None, "INVALID_TARGET")
    require(not candidate_scope(state, project_id), "PLANNING_NOT_ACTIVE")
    require(project["status"] != "paused", "PROJECT_PAUSED")
    require(project["status"] in {"planning", "active"}, "PROJECT_INACTIVE")
    require(project.get("execution_policy_version") == EXECUTION_POLICY, "POLICY_UNAVAILABLE")
    return project


def execution_snapshot(state, project_id, task_id, actor, fence, at):
    """Durable half of the fence; the service also validates live object identity."""
    project = executable_project(state, project_id)
    task = state.get(f"task:{task_id}")
    require(task is not None and task.get("execution_policy_version") == EXECUTION_POLICY, "INVALID_TARGET")
    require(task.get("status") == "in_progress", "TASK_NOT_EXECUTING")
    require(task.get("owner_id") == actor and participant(state, actor), "PERMISSION_DENIED")
    lease = task.get("lease")
    require(type(fence.get("lease_epoch")) is int and lease is not None and not lease["revoked"]
            and lease["expires_at_governance_ms"] > governance(project, at)
            and fence.get("lease_epoch") == task["lease_epoch"]
            and fence.get("binding_id") == task["current_binding_id"], "STALE_EXECUTION")
    binding = task["bindings"][task["current_binding_id"]]
    descriptor = binding.get("session")
    require(binding["status"] == "running" and descriptor is not None
            and fence.get("session_id") == descriptor["id"], "SESSION_INVALID")
    require(descriptor["expires_at_wall_ms"] > at, "SESSION_EXPIRED")
    require(task["workspace_provider_id"] == project["workspace_provider_id"], "WORKSPACE_MISMATCH")
    return {"exec_task_id": task_id, "actor_id": actor, "task_revision": task["revision"],
            "binding_id": binding["id"], "lease_epoch": task["lease_epoch"], "session_id": descriptor["id"],
            "session": copy.deepcopy(descriptor), "workspace_provider_id": project["workspace_provider_id"],
            "lease_expires_at": lease["expires_at_governance_ms"]}


def _quality(state, project_id):
    project = state.get(f"project:{project_id}", {})
    quality = project.get("quality")
    require(quality is not None, "QUALITY_POLICY_REQUIRED")
    generation = quality["generation"]
    version = quality["versions"][str(generation)]
    return {"generation": generation, "policy": copy.deepcopy(version["policy"]),
            "content_digest": version["content_digest"]}


def configure(command, state, at):
    fields(command.payload, {"grant_ttl_ms"}, {"grant_ttl_ms"})
    governance_config, _ = current(state, command.project_id)
    require(command.actor_id == governance_config["owner_id"], "PERMISSION_DENIED")
    principal(state, command.project_id, command.actor_id)
    previous = state[f"project:{command.project_id}"]
    require(command.target_id == command.project_id, "INVALID_TARGET")
    revision(command, previous)
    ttl = natural(command.payload["grant_ttl_ms"], 60000, positive=True)
    value = {"runner_id": RUNNER_ID, "grant_ttl_ms": ttl, "max_cases": MAX_CASES,
             "max_case_bytes": MAX_CASE_BYTES, "max_document_bytes": MAX_DOCUMENT_BYTES,
             "max_depth": MAX_DEPTH, "max_path": MAX_PATH, "independent_authors_required": True}
    quality = copy.deepcopy(previous.get("quality", {"generation": 0, "versions": {}}))
    quality["generation"] += 1
    quality["versions"][str(quality["generation"])] = {
        "policy": value, "content_digest": digest_value(value), "configured_by": command.actor_id,
        "command_id": command.id, "observed_at_ms": at}
    return {**copy.deepcopy(previous), "revision": previous["revision"] + 1, "quality": quality, "observed_at_ms": at}


def _inherit(source, kind, identifier, provenance, content_digest):
    provenance = copy.deepcopy(provenance or {"untrusted_input": True, "exposure": "unknown"})
    marked = provenance.get("untrusted_input") is not False
    source.setdefault("derived_sources", []).append({"type": kind, "id": identifier,
        "content_digest": content_digest, "source_digest": digest_value(provenance),
        "source": provenance, "untrusted_input": marked})
    source["untrusted_input"] |= marked
    return source


def capture(command, state, at, context):
    fields(command.payload, {"source_action_id", "binding_id", "lease_epoch", "session_id"},
           {"source_action_id", "binding_id", "lease_epoch", "session_id"})
    require(f"artifact:{command.target_id}" not in state, "REVISION_CONFLICT")
    revision(command, None)
    governance_config, _ = current(state, command.project_id)
    require(principal(state, command.project_id, command.actor_id)["type"] == "agent", "PERMISSION_DENIED")
    source_id = text(command.payload["source_action_id"], identifier=True, limit=512)
    action = state.get(f"action:{source_id}")
    require(action is not None and action["operation"] == "document.write", "INVALID_REFERENCE")
    require(action["status"] == "completed" and action["historical"] is False, "SOURCE_UNVERIFIED")
    require(action["actor_id"] == command.actor_id, "PERMISSION_DENIED")
    execution_snapshot(state, command.project_id, action["task_id"], command.actor_id, command.payload, at)
    task = state[f"task:{action['task_id']}"]
    require(action["requested_task_revision"] == task["revision"], "EVIDENCE_STALE")
    require(all(action[key] == command.payload[key] for key in ("binding_id", "lease_epoch", "session_id")), "STALE_EXECUTION")
    require(action["arguments_digest"] == digest_value(action["arguments"])
            and canonical_json(action["result"]) == canonical_json(receipt(action)), "SOURCE_UNVERIFIED")
    source = source_record(command, context, governance_config.get("input_authority_id"))
    _inherit(source, "action", source_id, action.get("authorization", {}).get("source"), action["result"]["envelope_digest"])
    source.update(kind="runtime_document_capture", command_id=command.id, source_action_id=source_id,
                  action_revision=action["revision"], arguments_digest=action["arguments_digest"],
                  result_digest=digest_value(action["result"]), authorization=copy.deepcopy(action.get("authorization")),
                  execution_authority="captured_document_bytes_only")
    artifact = Artifact(command.target_id, command.project_id, task["id"], action["actor_id"], "document",
        action["arguments"]["content"], action["result"]["content_digest"], task["revision"],
        tuple(task["acceptance_criteria"]), task["criteria_digest"], POLICY_VERSION, source)
    return {**artifact.to_dict(), "capture_origin": {"schema": SCHEMA, "command_id": command.id,
             "command_digest": command.digest(), "action_id": source_id, "action_revision": action["revision"]}}


def observe(command, state, at, context):
    """Record an Agent's own document observation as an immutable Artifact.

    Bootstrap evidence has to exist before any Runtime Task or Session does, so
    it cannot be captured. It must still be a real fact: the observer is the
    authenticated Agent, the content digest is recomputed here, and the payload
    cannot name the author, a Task, a source or a digest.
    """
    fields(command.payload, {"content", "observer_note"}, {"content", "observer_note"})
    require(f"artifact:{command.target_id}" not in state, "REVISION_CONFLICT")
    revision(command, None)
    governance_config, _ = current(state, command.project_id)
    require(principal(state, command.project_id, command.actor_id)["type"] == "agent", "PERMISSION_DENIED")
    require(context.get("channel") == "agent", "ENFORCEMENT_UNAVAILABLE")
    content = text(command.payload["content"], limit=MAX_DOCUMENT_BYTES)
    note = text(command.payload["observer_note"], limit=1024)
    digest = digest_text(content)
    source = source_record(command, context, governance_config.get("input_authority_id"))
    source.update(kind="agent_observation", command_id=command.id, observer_note=note,
                  observed_at_ms=at, content_digest=digest)
    return {"id": command.target_id, "project_id": command.project_id, "task_id": None,
            "created_by": command.actor_id, "type": "document", "content": content,
            "content_digest": digest, "task_revision": 0, "criteria": [],
            "criteria_digest": digest_value([]), "policy_version": POLICY_VERSION, "source": source,
            "derived_from": [], "supersedes": None, "data_classification": "internal", "revision": 0,
            "digest": digest_value(content),
            "origin": {"kind": "agent_observation", "command_id": command.id}}


def target_snapshot(state, identifier, claimed_digest=None):
    artifact = state.get(f"artifact:{identifier}")
    require(artifact is not None and artifact["type"] == "document", "INVALID_TARGET")
    task = state.get(f"task:{artifact['task_id']}")
    require(task is not None and task["status"] not in {"completed", "failed", "cancelled"}, "EVIDENCE_STALE")
    quality_cycle_id = None
    if task.get("quality_cycle") is not None:
        from aetp.quality.evidence import target_binding
        quality_cycle_id = target_binding(state, artifact)
    else:
        require(artifact["task_revision"] == task["revision"], "EVIDENCE_STALE")
    require(artifact["criteria_digest"] == task["criteria_digest"]
            and artifact["policy_version"] == task.get("policy_version") == POLICY_VERSION
            and artifact["content_digest"] == digest_text(artifact["content"])
            and artifact["criteria_digest"] == digest_value(artifact["criteria"])
            and (claimed_digest is None or claimed_digest == artifact["content_digest"]), "EVIDENCE_STALE")
    snapshot = {"artifact_id": identifier, "artifact_digest": artifact["content_digest"], "task_id": task["id"],
            "task_revision": artifact["task_revision"], "criteria_digest": artifact["criteria_digest"],
            "criteria": copy.deepcopy(artifact["criteria"]), "artifact_author_id": artifact["created_by"],
            "source_digest": digest_value(artifact["source"]),
            "capture_origin_digest": digest_value(artifact.get("capture_origin"))}
    if quality_cycle_id is not None:
        snapshot["quality_cycle_id"] = quality_cycle_id
    return snapshot


def _runner_descriptor(value):
    fields(value, {"id", "version", "method", "implementation_digest", "sources", "environment", "invocation"},
           {"id", "version", "method", "implementation_digest", "sources", "environment", "invocation"})
    require(value["id"] == RUNNER_ID and type(value["version"]) is int and value["version"] == 1
            and value["method"] == "strict_json_path_equals"
            and value["invocation"] == "FixedJsonRunner.run(immutable_content, immutable_cases)", "RUNNER_UNAVAILABLE")
    fields(value["sources"], {"runner.py", "contracts.py"}, {"runner.py", "contracts.py"})
    for digest in value["sources"].values():
        require(isinstance(digest, str) and digest.startswith("sha256:") and len(digest) == 71
                and all(c in "0123456789abcdef" for c in digest[7:]), "RUNNER_UNAVAILABLE")
    require(value["implementation_digest"] == digest_value(value["sources"]), "RUNNER_UNAVAILABLE")
    fields(value["environment"], {"implementation", "python_version"}, {"implementation", "python_version"})
    for entry in value["environment"].values():
        text(entry, limit=128)
    return copy.deepcopy(value)


def request(command, state, at, context):
    fields(command.payload, {"artifact_id", "artifact_digest", "exec_task_id", "binding_id", "lease_epoch",
                            "session_id", "cases", "risk_level", "approval_required"},
           {"artifact_id", "artifact_digest", "exec_task_id", "binding_id", "lease_epoch", "session_id", "cases"})
    require(f"verification:{command.target_id}" not in state, "REVISION_CONFLICT")
    revision(command, None)
    require(f"artifact:{report_id(command.project_id, command.target_id)}" not in state, "REPORT_ID_CONFLICT")
    executable_project(state, command.project_id)
    governance_config, value = current(state, command.project_id)
    require(principal(state, command.project_id, command.actor_id)["type"] == "agent", "PERMISSION_DENIED")
    identifier = text(command.payload["artifact_id"], identifier=True, limit=512)
    text(command.payload["artifact_digest"], identifier=True, limit=71)
    target = target_snapshot(state, identifier, command.payload["artifact_digest"])
    if state[f"task:{target['task_id']}"].get("quality_contract") is not None:
        from aetp.quality.evidence import verification_allowed
        verification_allowed(state, identifier, command.actor_id)
    require(target["artifact_author_id"] != command.actor_id, "INDEPENDENCE_REQUIRED")
    exec_task_id = text(command.payload["exec_task_id"], identifier=True, limit=512)
    require(exec_task_id != target["task_id"], "INDEPENDENT_EXECUTION_TASK_REQUIRED")
    cases = normalize_cases(copy.deepcopy(command.payload["cases"]), target["criteria"])
    execution = execution_snapshot(state, command.project_id, exec_task_id, command.actor_id, command.payload, at)
    _live(context, execution)
    source = source_record(command, context, governance_config.get("input_authority_id"))
    _inherit(source, "artifact", identifier, state[f"artifact:{identifier}"]["source"], target["artifact_digest"])
    risk = command.payload.get("risk_level", "low")
    require(type(command.payload.get("approval_required", False)) is bool, "INVALID_PAYLOAD")
    routing = route(value, "verification.execute", risk, source["untrusted_input"])
    require(not command.payload.get("approval_required", False) and routing["risk_level"] == "low"
            and routing["mode"] == "auto", "APPROVAL_REQUIRED")
    # Only the new reducer produces this top-level proof. Legacy Artifact
    # models reject extra top-level fields even if their extensible source
    # mapping has been resealed with an invented kind or clean flag.
    origin = state[f"artifact:{identifier}"].get("capture_origin")
    require(isinstance(origin, dict) and origin.get("schema") == SCHEMA, "SOURCE_UNVERIFIED")
    quality = _quality(state, command.project_id)
    runner = _runner_descriptor(context.get("runner"))
    grant = {"id": child_id("verification-grant", command.project_id, command.id), "revoked": False,
             "issued_at_ms": at, "expires_at_ms": at + quality["policy"]["grant_ttl_ms"],
             "governance_version": governance_config["current_version"], "governance_digest": digest_value(value),
             "quality": quality, "execution": execution, "source": source, "routing": routing,
             "requested_risk": risk}
    action = {"id": child_id("verification-action", command.project_id, command.id), "status": "pending",
              "dispatch_count": 0, "request_command_id": command.id, "dispatch_command_id": None,
              "finish_command_id": None, "started_at_ms": None, "finished_at_ms": None}
    return {"schema": SCHEMA, "id": command.target_id, "project_id": command.project_id, "revision": 0,
            "task_id": target["task_id"], "artifact_id": identifier, "artifact_digest": target["artifact_digest"],
            "verifier_id": command.actor_id, "input": target, "runner": runner,
            "case_set": {"author_id": command.actor_id, "cases": cases, "content_digest": digest_value(cases)},
            "grant": grant, "action": action, "status": "pending", "result": None, "reason": None,
            "evidence_id": None, "evidence_digest": None, "observed_at_ms": at}


def _live(context, execution):
    observation = context.get("live")
    require(isinstance(observation, dict), "ENFORCEMENT_UNAVAILABLE")
    fields(observation, {"session", "workspace_provider_id", "barrier_open"},
           {"session", "workspace_provider_id", "barrier_open"})
    require(canonical_json(observation["session"]) == canonical_json(execution["session"]), "SESSION_INVALID")
    require(observation["workspace_provider_id"] == execution["workspace_provider_id"], "WORKSPACE_MISMATCH")
    require(observation["barrier_open"] is True, "RECOVERY_REQUIRED")


def authorization_error(record, state, at, context):
    """Recheck permission at invocation and recording; no historical truth rewrite."""
    try:
        executable_project(state, record["project_id"])
        grant = record["grant"]
        require(not grant["revoked"], "GRANT_REVOKED")
        require(at < grant["expires_at_ms"], "GRANT_EXPIRED")
        governance_config, value = current(state, record["project_id"])
        require(governance_config["current_version"] == grant["governance_version"]
                and digest_value(value) == grant["governance_digest"], "GOVERNANCE_CHANGED")
        require(canonical_json(_quality(state, record["project_id"])) == canonical_json(grant["quality"]), "QUALITY_POLICY_CHANGED")
        require(principal(state, record["project_id"], record["verifier_id"])["type"] == "agent", "PERMISSION_DENIED")
        target = target_snapshot(state, record["artifact_id"], record["artifact_digest"])
        require(canonical_json(target) == canonical_json(record["input"]), "EVIDENCE_STALE")
        routing = route(value, "verification.execute", grant["requested_risk"], grant["source"]["untrusted_input"])
        require(canonical_json(routing) == canonical_json(grant["routing"]) and routing["mode"] == "auto"
                and routing["risk_level"] == "low", "APPROVAL_REQUIRED")
        execution = execution_snapshot(state, record["project_id"], grant["execution"]["exec_task_id"],
                                       record["verifier_id"], grant["execution"], at)
        require(canonical_json(execution) == canonical_json(grant["execution"]), "EXECUTION_CHANGED")
        _live(context, execution)
        require(canonical_json(_runner_descriptor(context.get("runner"))) == canonical_json(record["runner"]), "RUNNER_CHANGED")
        return None
    except PolicyViolation as exc:
        return exc.code


def _observation(value, cases):
    fields(value, {"observed_result", "checks", "diagnostic"}, {"observed_result", "checks", "diagnostic"})
    require(value["observed_result"] in {"PASSED", "FAILED"} and isinstance(value["checks"], list), "INVALID_RUNNER_RESULT")
    if value["diagnostic"] == "INVALID_DOCUMENT":
        require(value["observed_result"] == "FAILED" and not value["checks"], "INVALID_RUNNER_RESULT")
        return copy.deepcopy(value)
    require(len(value["checks"]) == len(cases), "INVALID_RUNNER_RESULT")
    for check, case in zip(value["checks"], cases):
        fields(check, {"criterion", "path", "matched", "observed_type", "observed_digest", "diagnostic"},
               {"criterion", "path", "matched", "observed_type", "observed_digest", "diagnostic"})
        require(check["criterion"] == case["criterion"] and canonical_json(check["path"]) == canonical_json(case["path"])
                and type(check["matched"]) is bool, "INVALID_RUNNER_RESULT")
        missing = check["observed_type"] == "missing"
        require(check["observed_type"] in {"missing", "null", "boolean", "integer", "number", "string", "array", "object"},
                "INVALID_RUNNER_RESULT")
        digest = check["observed_digest"]
        require((missing and digest is None and not check["matched"]) or (not missing and isinstance(digest, str)
                and digest.startswith("sha256:") and len(digest) == 71
                and all(c in "0123456789abcdef" for c in digest[7:])), "INVALID_RUNNER_RESULT")
        require(check["diagnostic"] == ("MATCH" if check["matched"] else "MISSING_PATH" if missing else "NOT_EQUAL"),
                "INVALID_RUNNER_RESULT")
    passed = all(check["matched"] for check in value["checks"])
    require(value["observed_result"] == ("PASSED" if passed else "FAILED")
            and value["diagnostic"] == ("ALL_CHECKS_MATCHED" if passed else "CHECKS_FAILED"), "INVALID_RUNNER_RESULT")
    return copy.deepcopy(value)


def finish(command, previous, state, at, context):
    fields(command.payload, {"execution_outcome", "observation"}, {"execution_outcome", "observation"})
    require(previous["status"] != "finished", "VERIFICATION_FINAL")
    outcome = command.payload["execution_outcome"]
    require(outcome in {"completed", "not_executed", "runner_error", "recovered"}, "INVALID_PAYLOAD")
    observation = command.payload["observation"]
    error = authorization_error(previous, state, at, context)
    if outcome == "recovered":
        require(context.get("channel") == "recovery" and context.get("termination") == "exclusive_gate_fixed_memory_runner_exited"
                and previous["action"]["status"] == "in_flight" and observation is None, "RECOVERY_REQUIRED")
        reason, result, action_status = "RESULT_LOST_RECOVERY_NO_RERUN", "INCONCLUSIVE", "abandoned"
    elif outcome == "not_executed":
        require(context.get("channel") == "host" and previous["action"]["status"] in {"pending", "in_flight"}
                and observation is None and error is not None, "INVALID_RUNNER_RESULT")
        reason, result, action_status = error, "INCONCLUSIVE", "cancelled"
    else:
        require(context.get("channel") == "host" and previous["action"]["status"] == "in_flight", "INVALID_RUNNER_RESULT")
        if outcome == "completed":
            observation = _observation(observation, previous["case_set"]["cases"])
            reason, result = error or observation["diagnostic"], "INCONCLUSIVE" if error else observation["observed_result"]
            action_status = "completed"
        else:
            require(observation is None, "INVALID_RUNNER_RESULT")
            reason, result, action_status = error or "RUNNER_ERROR", "INCONCLUSIVE", "abandoned"
    report = {"schema": SCHEMA, "verification_id": previous["id"], "project_id": previous["project_id"],
              "action_id": previous["action"]["id"], "grant_id": previous["grant"]["id"],
              "request_command_id": previous["action"]["request_command_id"],
              "dispatch_command_id": previous["action"]["dispatch_command_id"], "record_command_id": command.id,
              "input": copy.deepcopy(previous["input"]), "runner": copy.deepcopy(previous["runner"]),
              "case_set": copy.deepcopy(previous["case_set"]), "grant": copy.deepcopy(previous["grant"]),
              "execution_outcome": outcome, "observation": observation, "result": result, "reason": reason,
              "started_at_ms": previous["action"]["started_at_ms"], "finished_at_ms": at,
              "termination": context.get("termination"),
              "scope": "fixed_checks_only_no_task_or_mission_acceptance"}
    content = canonical_json(report)
    identifier = report_id(command.project_id, previous["id"])
    # Reports can exceed ordinary candidate text size because they pin sources;
    # the new schema validates their generated content instead of coercing it.
    source = {"kind": "trusted_fixed_verification", "command_id": command.id,
              "verification_id": previous["id"], "action_id": previous["action"]["id"],
              "untrusted_input": previous["grant"]["source"]["untrusted_input"],
              "input_source": copy.deepcopy(previous["grant"]["source"]), "execution_authority": "fixed_single_use_grant"}
    evidence = {"schema_version": "0.1", "id": identifier, "project_id": command.project_id,
                "task_id": previous["task_id"], "created_by": system_actor(command.project_id), "type": "report",
                "content": content, "content_digest": digest_text(content),
                "task_revision": previous["input"]["task_revision"], "criteria": previous["input"]["criteria"],
                "criteria_digest": previous["input"]["criteria_digest"], "policy_version": POLICY_VERSION,
                "source": source, "derived_from": [previous["artifact_id"]], "supersedes": None,
                "data_classification": state[f"artifact:{previous['artifact_id']}"]["data_classification"], "revision": 0}
    record = copy.deepcopy(previous)
    record.update(revision=previous["revision"] + 1, observed_at_ms=at, status="finished", result=result, reason=reason,
                  evidence_id=identifier, evidence_digest=evidence["content_digest"])
    record["action"].update(status=action_status, finish_command_id=command.id, finished_at_ms=at)
    return evidence, record


def evaluate(command, state, at, context):
    """Returns the full list of deterministic effects for a validated Command."""
    require(observed_time(state, at) == at, "INVALID_TIME")
    text(command.target_id, identifier=True, limit=512)
    fields(context, {"channel", "live", "runner", "input_proof", "termination"}, {"channel"})
    require(context["channel"] in {"agent", "host", "recovery"}, "ENFORCEMENT_UNAVAILABLE")
    if command.type == "project.quality.configure":
        record = configure(command, state, at)
        return [("project.quality_configured", "project", command.target_id, record)]
    if command.type == "artifact.capture":
        record = capture(command, state, at, context)
        execution = execution_snapshot(state, command.project_id, record["task_id"], command.actor_id, command.payload, at)
        _live(context, execution)
        return [("artifact.captured", "artifact", command.target_id, record)]
    if command.type == "artifact.observe":
        return [("artifact.observed", "artifact", command.target_id, observe(command, state, at, context))]
    if command.type == "verification.request":
        record = request(command, state, at, context)
        return [("verification.requested", "verification", command.target_id, record)]
    previous = state.get(f"verification:{command.target_id}")
    require(previous is not None and previous.get("schema") == SCHEMA, "INVALID_TARGET")
    revision(command, previous)
    require(previous["status"] != "finished", "VERIFICATION_FINAL")
    if command.type == "verification.revoke":
        fields(command.payload, {"reason"}, {"reason"})
        governance_config, _ = current(state, command.project_id)
        require(command.actor_id in {previous["verifier_id"], governance_config["owner_id"]}, "PERMISSION_DENIED")
        principal(state, command.project_id, command.actor_id)
        require(not previous["grant"]["revoked"], "GRANT_REVOKED")
        record = copy.deepcopy(previous)
        record.update(revision=previous["revision"] + 1, observed_at_ms=at)
        record["grant"].update(revoked=True, revoked_by=command.actor_id, revoked_at_ms=at,
                               revocation_command_id=command.id, revocation_reason=text(command.payload["reason"], limit=512))
        return [("verification.revoked", "verification", command.target_id, record)]
    require(context["channel"] in {"host", "recovery"} and command.actor_id == system_actor(command.project_id),
            "ENFORCEMENT_UNAVAILABLE")
    principal(state, command.project_id, command.actor_id, internal=True)
    if command.type == "verification.dispatch":
        fields(command.payload, {"action_id", "grant_id"}, {"action_id", "grant_id"})
        require(context["channel"] == "host" and previous["action"]["status"] == "pending"
                and previous["action"]["dispatch_count"] == 0, "ACTION_NOT_PENDING")
        require(command.payload["action_id"] == previous["action"]["id"]
                and command.payload["grant_id"] == previous["grant"]["id"], "INVALID_REFERENCE")
        error = authorization_error(previous, state, at, context)
        require(error is None, error)
        record = copy.deepcopy(previous)
        record.update(revision=previous["revision"] + 1, observed_at_ms=at, status="running")
        record["action"].update(status="in_flight", dispatch_count=1, started_at_ms=at, dispatch_command_id=command.id)
        return [("verification.dispatched", "verification", command.target_id, record)]
    require(command.type == "verification.record", "UNSUPPORTED_COMMAND")
    evidence, record = finish(command, previous, state, at, context)
    return [("artifact.verification_reported", "artifact", evidence["id"], evidence),
            ("verification.finished", "verification", command.target_id, record)]
