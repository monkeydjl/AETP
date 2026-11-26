"""Pure authority, fixed policy and live-observation checks for quality work."""

import copy

from aetp.acceptance.records import _inherit, executable_project, require
from aetp.collaboration.messages import participant
from aetp.collaboration.policy import POLICY_VERSION, canonical_json, digest_value, text
from aetp.governance.policy import current, fields, principal, revision, route
from aetp.governance.trust import source_record
from aetp.meetings.policy import natural
from aetp.quality.contracts import SCHEMA
from aetp.runtime.contracts import POLICY_VERSION as EXECUTION_POLICY
from aetp.runtime.contracts import UNSETTLED
from aetp.runtime.policy import governance


def current_policy(state, project_id):
    project = state.get(f"project:{project_id}", {})
    history = project.get("task_quality_policy")
    require(isinstance(history, dict), "TASK_QUALITY_POLICY_REQUIRED")
    version = history["current_version"]
    value = history["versions"][version]
    return {"version": version, "content_digest": value["content_digest"], "policy": copy.deepcopy(value["policy"])}


def configure(command, state, at):
    fields(command.payload, {"version", "max_evidence_age_ms", "integration_exemptions"},
           {"version", "max_evidence_age_ms", "integration_exemptions"})
    configuration, _ = current(state, command.project_id)
    require(command.actor_id == configuration["owner_id"], "PERMISSION_DENIED")
    principal(state, command.project_id, command.actor_id)
    previous = state[f"project:{command.project_id}"]
    require(command.target_id == command.project_id, "INVALID_TARGET")
    revision(command, previous)
    version = text(command.payload["version"], identifier=True)
    age = natural(command.payload["max_evidence_age_ms"], 86400000, positive=True)
    supplied = command.payload["integration_exemptions"]
    require(isinstance(supplied, list) and len(supplied) <= 64, "INVALID_PAYLOAD")
    exemptions = {}
    for entry in supplied:
        fields(entry, {"task_id", "scope", "reason"}, {"task_id", "scope", "reason"})
        identifier = text(entry["task_id"], identifier=True, limit=512)
        task = state.get(f"task:{identifier}")
        require(identifier not in exemptions and task is not None, "INVALID_REFERENCE")
        require(task.get("execution_policy_version") == EXECUTION_POLICY
                and task.get("policy_version") == POLICY_VERSION and task.get("owner_id") is not None,
                "INVALID_TARGET")
        require(entry["scope"] == "standalone_fixed_json_document", "INTEGRATION_SCOPE_UNSUPPORTED")
        exemptions[identifier] = {"task_id": identifier, "scope": entry["scope"],
            "reason": text(entry["reason"], limit=2048), "criteria_digest": task["criteria_digest"],
            "owner_id": task["owner_id"], "binding_id": task["current_binding_id"], "lease_epoch": task["lease_epoch"],
            "workspace_provider_id": task["workspace_provider_id"], "declared_by": command.actor_id,
            "command_id": command.id, "basis": "explicit_human_owner_task_scope"}
    history = copy.deepcopy(previous.get("task_quality_policy", {"versions": {}}))
    require(version not in history["versions"], "POLICY_VERSION_CONFLICT")
    value = {"schema": SCHEMA, "version": version, "max_evidence_age_ms": age,
             "integration_exemptions": exemptions}
    history["versions"][version] = {"policy": value, "content_digest": digest_value(value),
                                    "configured_by": command.actor_id, "command_id": command.id, "observed_at_ms": at}
    history["current_version"] = version
    return {**copy.deepcopy(previous), "revision": previous["revision"] + 1,
            "observed_at_ms": at, "task_quality_policy": history}


def execution_context(state, task, at):
    project = executable_project(state, task["project_id"])
    require(task.get("execution_policy_version") == EXECUTION_POLICY, "POLICY_UNAVAILABLE")
    require(task.get("status") not in {"completed", "cancelled", "failed"}, "INVALID_TRANSITION")
    owner = task.get("owner_id")
    require(isinstance(owner, str) and participant(state, owner), "PERMISSION_DENIED")
    lease = task.get("lease")
    require(lease is not None and not lease["revoked"]
            and lease["expires_at_governance_ms"] > governance(project, at), "STALE_EXECUTION")
    identifier = task.get("current_binding_id")
    binding = task.get("bindings", {}).get(identifier)
    require(binding is not None and binding["status"] == "running" and binding["session"] is not None,
            "SESSION_INVALID")
    session = binding["session"]
    require(session["expires_at_wall_ms"] > at, "SESSION_EXPIRED")
    require(task["workspace_provider_id"] == project["workspace_provider_id"], "WORKSPACE_MISMATCH")
    require(lease["owner_id"] == owner and lease["binding_id"] == identifier
            and lease["lease_epoch"] == task["lease_epoch"]
            and binding["agent_id"] == owner and binding["lease_epoch"] == task["lease_epoch"], "STALE_EXECUTION")
    require(session["actor_id"] == owner and session["project_id"] == task["project_id"]
            and session["task_id"] == task["id"] and session["binding_id"] == identifier
            and session["lease_epoch"] == task["lease_epoch"], "SESSION_INVALID")
    return {"owner_id": owner, "binding_id": identifier, "lease_epoch": task["lease_epoch"],
            "session_id": session["id"], "session": copy.deepcopy(session),
            "lease_expires_at": lease["expires_at_governance_ms"], "workspace_provider_id": project["workspace_provider_id"]}


def observed_live(value, execution):
    require(isinstance(value, dict), "ENFORCEMENT_UNAVAILABLE")
    fields(value, {"session", "workspace_provider_id", "barrier_open"},
           {"session", "workspace_provider_id", "barrier_open"})
    require(canonical_json(value["session"]) == canonical_json(execution["session"]), "SESSION_INVALID")
    require(value["workspace_provider_id"] == execution["workspace_provider_id"], "WORKSPACE_MISMATCH")
    require(value["barrier_open"] is True, "RECOVERY_REQUIRED")


def author(command, state, task, at, context):
    require(command.actor_id == task.get("owner_id"), "PERMISSION_DENIED")
    execution = execution_context(state, task, at)
    require(type(command.payload.get("lease_epoch")) is int
            and all(command.payload.get(key) == execution[key] for key in ("binding_id", "lease_epoch", "session_id")),
            "STALE_EXECUTION")
    observed_live(context.get("requester_live"), execution)
    return execution


def authorize(command, state, context, action, sources=()):
    configuration, policy = current(state, command.project_id)
    principal(state, command.project_id, command.actor_id)
    source = source_record(command, context, configuration.get("input_authority_id"))
    for kind, identifier, provenance, digest in sources:
        _inherit(source, kind, identifier, provenance, digest)
    routing = route(policy, action, "low", source["untrusted_input"])
    require(routing["risk_level"] == "low" and routing["mode"] == "auto", "APPROVAL_REQUIRED")
    return {"governance_version": configuration["current_version"], "governance_digest": digest_value(policy),
            "action": action, "source": source, "routing": routing}


def no_unsettled(state, task_id, *, target_verifications=True):
    for key, value in state.items():
        if key.startswith("action:") and value["task_id"] == task_id:
            require(value["status"] not in UNSETTLED, "RECONCILIATION_REQUIRED")
        if key.startswith("verification:") and value.get("grant"):
            relevant = value["grant"]["execution"]["exec_task_id"] == task_id
            relevant |= target_verifications and value["task_id"] == task_id
            if relevant:
                require(value["action"]["status"] not in {"pending", "in_flight", "unknown"}, "RECONCILIATION_REQUIRED")
