"""Pure execution facts. No clocks, files, Sessions or dispatch are invoked."""

import copy
from types import SimpleNamespace

from aetp.collaboration.messages import participant
from aetp.collaboration.policy import PolicyViolation, canonical_json, text
from aetp.domain.models import ModelValidationError
from aetp.runtime.contracts import (
    COMMAND_AGGREGATES,
    LEASE_MS,
    POLICY_VERSION,
    RUNTIME_ID,
    SESSION_MS,
    UNSETTLED,
    child_id,
)
from aetp.runtime.policy import governance, natural, observed_time
from aetp.runtime.records import action_intent, checkpoint_intent, receipt


def require(condition, message):
    if not condition:
        raise ModelValidationError(message)


def task_metadata(payload, state):
    project = state.get(f"project:{payload['project_id']}")
    require(project is not None and project.get("execution_policy_version") == POLICY_VERSION,
            "execution Task requires a configured Project")
    require(payload.get("execution_policy_version") == POLICY_VERSION
            and payload.get("workspace_provider_id") == project["workspace_provider_id"],
            "execution Task scope does not match Project")
    return {"execution_policy_version": POLICY_VERSION,
            "workspace_provider_id": project["workspace_provider_id"], "lease_epoch": 0,
            "current_binding_id": None, "lease": None, "bindings": {}}


def current_fence(task, payload, project, at):
    lease = task.get("lease")
    require(lease is not None and not lease["revoked"] and lease["expires_at_governance_ms"] > governance(project, at),
            "execution Event has no live Lease")
    require(payload.get("actor_id") == task["owner_id"]
            and payload.get("binding_id") == task["current_binding_id"]
            and type(payload.get("lease_epoch")) is int and payload["lease_epoch"] == task["lease_epoch"],
            "execution Event has a stale or mismatched Binding")
    return task["bindings"][task["current_binding_id"]]


def reduce_record(event, previous, state):
    project = state.get(f"project:{event.project_id}", {})
    if event.type != "project.execution_configured" and (
        project.get("execution_policy_version") != POLICY_VERSION
        or (event.aggregate_type == "task" and (previous or {}).get("execution_policy_version") != POLICY_VERSION)
    ):
        raise ModelValidationError(f"unsupported execution Event for legacy scope: {event.type}")
    try:
        return _reduce(event, previous, state)
    except (PolicyViolation, KeyError, TypeError) as exc:
        raise ModelValidationError(f"invalid execution Event: {event.type}") from exc


def _reduce(event, previous, state):
    payload = event.payload
    at = observed_time(state, payload.get("observed_at_ms"))
    actor = text(payload.get("actor_id"), identifier=True)
    project = state.get(f"project:{event.project_id}")
    require(project is not None, "execution Event needs its Project")
    if event.aggregate_type == "action":
        return _action(event, previous, state, project, at, actor)
    if event.aggregate_type == "checkpoint":
        return _checkpoint(event, previous, state, project, at, actor)
    require(previous is not None and event.aggregate_revision == previous["revision"] + 1,
            "execution Event revision gap")
    updated = copy.deepcopy(previous)
    updated.update(revision=event.aggregate_revision, observed_at_ms=at)

    if event.type == "project.execution_configured":
        require(actor == "bootstrap" and "execution_clock" not in previous
                and previous.get("status") in {"planning", "active"}, "invalid execution configuration")
        require(payload.get("policy_version") == POLICY_VERSION, "unknown execution Policy")
        provider = text(payload.get("workspace_provider_id"), identifier=True)
        updated.update(execution_policy_version=POLICY_VERSION, workspace_provider_id=provider,
                       execution_clock={"elapsed_ms": 0, "wall_anchor_ms": at})
        return updated

    require(project.get("execution_policy_version") == POLICY_VERSION, "missing execution Policy")
    elapsed = governance(project, at)
    if event.type in {"project.paused", "project.resumed"}:
        require(actor == "bootstrap", "project control requires trusted bootstrap")
        if event.type == "project.paused":
            require(previous["status"] in {"planning", "active"}, "cannot pause current Project state")
            updated.update(status="paused", paused_from=previous["status"])
        else:
            require(previous["status"] == "paused", "resume requires paused Project")
            require(payload.get("status") == previous["paused_from"], "resume target changed")
            updated.update(status=previous["paused_from"])
        require(payload.get("elapsed_ms") == elapsed, "governance clock disagrees with facts")
        updated["execution_clock"] = {"elapsed_ms": elapsed, "wall_anchor_ms": at}
        return updated

    require(event.aggregate_type == "task" and previous.get("execution_policy_version") == POLICY_VERSION,
            "event needs an execution Task")
    require(previous.get("workspace_provider_id") == project["workspace_provider_id"], "Task workspace mismatch")
    require(previous["status"] not in {"completed", "cancelled", "failed"},
            "terminal Task cannot regain execution authority or change through legacy execution facts")
    if event.type == "task.claimed":
        require(project["status"] in {"planning", "active"} and participant(state, actor), "claim permission denied")
        require(previous["status"] == "pending" and previous["owner_id"] is None, "Task is not claimable")
        epoch = natural(payload.get("lease_epoch"))
        binding = copy.deepcopy(payload["binding"])
        lease = copy.deepcopy(payload["lease"])
        require(epoch == previous["lease_epoch"] + 1 and binding["id"] not in previous["bindings"],
                "claim must allocate a new Binding and epoch")
        require(binding["id"] == child_id("binding", event.project_id, event.causation_id), "Binding identity is not allocated by its Command")
        require(binding == {"id": payload["binding_id"], "agent_id": actor, "lease_epoch": epoch,
                "runtime_id": RUNTIME_ID, "workspace_provider_id": project["workspace_provider_id"],
                "status": "assigned", "session": None, "resume_checkpoint_id": binding.get("resume_checkpoint_id")},
                "invalid Binding descriptor")
        checkpoint = binding["resume_checkpoint_id"]
        if checkpoint is not None:
            source = state.get(f"checkpoint:{checkpoint}")
            require(source is not None and source["task_id"] == previous["id"], "Checkpoint belongs to another Task")
        require(lease == {"owner_id": actor, "binding_id": binding["id"], "lease_epoch": epoch,
                          "expires_at_governance_ms": elapsed + LEASE_MS, "revoked": False}, "invalid Lease")
        updated["bindings"][binding["id"]] = binding
        updated.update(status="assigned", owner_id=actor, current_binding_id=binding["id"],
                       lease_epoch=epoch, lease=lease)
        return updated

    if event.type == "lease.revoked":
        lease = previous["lease"]
        require(lease is not None and not lease["revoked"]
                and payload.get("binding_id") == previous["current_binding_id"]
                and payload.get("lease_epoch") == previous["lease_epoch"], "invalid revocation")
        reason = payload.get("reason")
        require((reason == "handoff" and actor == previous["owner_id"])
                or (reason == "expired" and actor == "bootstrap" and lease["expires_at_governance_ms"] <= elapsed),
                "invalid Lease revocation authority")
        updated["lease"]["revoked"] = True
        updated["bindings"][previous["current_binding_id"]]["status"] = "revoked"
        updated.update(status="blocked", blocked_from=previous["status"], blocked_reason="lease_revoked")
        return updated

    if event.type == "task.requeued":
        require(previous["lease"] is not None and previous["lease"]["revoked"]
                and actor in {"bootstrap", previous["owner_id"]}, "requeue requires revoked Lease")
        require(not any(key.startswith("action:") and value["task_id"] == previous["id"]
                        and value["status"] in UNSETTLED for key, value in state.items()), "unreconciled Task actions")
        updated.update(status="pending", owner_id=None, current_binding_id=None, lease=None)
        updated.pop("blocked_from", None)
        updated.pop("blocked_reason", None)
        return updated

    if event.type == "execution.reported" and project["status"] == "paused" and project.get("governance"):
        require(participant(state, actor) and payload.get("while_paused") is True, "paused report is observation only")
        binding = current_fence(previous, payload, project, at)
        require(binding["session"] is not None and binding["session"]["expires_at_wall_ms"] > at,
                "paused observation requires current authenticated Session")
        updated["last_execution_report"] = {"binding_id": binding["id"], "lease_epoch": previous["lease_epoch"],
            "summary": text(payload.get("summary")), "authority": "observation_only", "while_paused": True}
        return updated
    require(project["status"] in {"planning", "active"} and participant(state, actor), "execution permission denied")
    binding = current_fence(previous, payload, project, at)
    if event.type == "lease.renewed":
        require(binding["session"] is None or binding["session"]["expires_at_wall_ms"] > at,
                "cannot renew from expired Session")
        require(payload.get("expires_at_governance_ms") == elapsed + LEASE_MS, "invalid Lease renewal")
        updated["lease"]["expires_at_governance_ms"] = elapsed + LEASE_MS
    elif event.type == "task.started":
        require(previous["status"] == "assigned" and binding["session"] is None, "Binding already started")
        descriptor = payload["session"]
        require(descriptor == {"id": descriptor["id"], "project_id": event.project_id, "task_id": previous["id"],
                "actor_id": actor, "binding_id": binding["id"], "lease_epoch": previous["lease_epoch"],
                "expires_at_wall_ms": at + SESSION_MS}, "invalid Session descriptor")
        text(descriptor["id"], identifier=True)
        updated["bindings"][binding["id"]].update(session=copy.deepcopy(descriptor), status="running")
        updated["status"] = "in_progress"
    elif event.type == "execution.reported":
        updated["last_execution_report"] = {"binding_id": binding["id"], "lease_epoch": previous["lease_epoch"],
                                             "summary": text(payload.get("summary")), "authority": "observation_only"}
    else:
        raise ModelValidationError(f"unimplemented execution Event: {event.type}")
    return updated


def action_is_current(action, state, project, at):
    task = state.get(f"task:{action['task_id']}")
    if task is None or task.get("current_binding_id") != action["binding_id"] or task.get("lease_epoch") != action["lease_epoch"]:
        return False
    lease = task.get("lease")
    if lease is None or lease["revoked"] or lease["expires_at_governance_ms"] <= governance(project, at):
        return False
    if project.get("governance") or action.get("authorization"):
        from aetp.governance.execution import authorize_action
        try:
            authorize_action(action, state, at)
        except PolicyViolation:
            return False
    descriptor = task["bindings"][action["binding_id"]]["session"]
    return bool(descriptor and descriptor["id"] == action["session_id"] and descriptor["expires_at_wall_ms"] > at)


def _action(event, previous, state, project, at, actor):
    require(project.get("execution_policy_version") == POLICY_VERSION, "Action needs fixed Project Policy")
    payload = event.payload
    if event.type == "tool.requested":
        require(previous is None and event.aggregate_revision == 0, "Action already exists")
        action = copy.deepcopy(payload["action"])
        task = state.get(f"task:{action['task_id']}")
        require(task is not None and task.get("execution_policy_version") == POLICY_VERSION
                and project["status"] in {"planning", "active"} and participant(state, actor), "Action scope denied")
        binding = current_fence(task, {**action, "actor_id": actor}, project, at)
        descriptor = binding["session"]
        require(task["status"] == "in_progress" and descriptor is not None and descriptor["id"] == action["session_id"]
                and descriptor["expires_at_wall_ms"] > at, "Action has no current Session")
        require(not any(key.startswith("action:") and value["task_id"] == task["id"]
                        and value["status"] in {"in_flight", "unknown"} for key, value in state.items()),
                "UNKNOWN must be reconciled before new intent")
        command = SimpleNamespace(id=event.causation_id, project_id=event.project_id, actor_id=actor,
            correlation_id=event.correlation_id, payload={"session_id": action["session_id"],
                "operation": action["operation"], "arguments": action["requested_arguments"]})
        if action.get("authorization"):
            command.payload.update(approval_id=action["authorization"]["approval_id"],
                                   risk_level=action["authorization"]["requested_risk"])
        require(action == action_intent(command, task, state) and action["id"] == event.aggregate_id,
                "Action identity or arguments do not match its Task")
        if project.get("governance"):
            from aetp.governance.execution import authorize_action
            authorize_action(action, state, at)
        return {**action, "revision": 0, "status": "pending", "result": None, "reason": None,
                "historical": False, "dispatch_count": 0, "query_count": 0,
                "created_sequence": event.sequence, "observed_at_ms": at}
    require(previous is not None and event.aggregate_revision == previous["revision"] + 1,
            "Action Event revision gap")
    require(actor == previous["actor_id"], "Action report attribution changed")
    require(previous["workspace_provider_id"] == project["workspace_provider_id"], "Action workspace mismatch")
    updated = copy.deepcopy(previous)
    updated.update(revision=event.aggregate_revision, observed_at_ms=at)
    if event.type == "tool.invoked":
        require(previous["status"] == "pending" and previous["dispatch_count"] == 0
                and project["status"] in {"planning", "active"} and participant(state, actor)
                and action_is_current(previous, state, project, at), "Action cannot be dispatched")
        updated.update(status="in_flight", dispatch_count=1)
    elif event.type == "tool.cancelled":
        require(previous["status"] == "pending" and not action_is_current(previous, state, project, at),
                "only a definitely undispatched stale Action may be cancelled")
        updated.update(status="cancelled", reason="EXECUTION_REVOKED", historical=True)
    else:
        require(previous["status"] in {"in_flight", "unknown"}, "Action has no unresolved external invocation")
        if event.type in {"tool.completed", "tool.reconciled"}:
            require(payload.get("result") == receipt(previous), "reported result does not bind exact Action/target/arguments")
            updated.update(status="completed", result=copy.deepcopy(payload["result"]), reason=None)
        elif event.type == "tool.outcome_unknown":
            updated.update(status="unknown", result=None, reason=text(payload.get("reason"), limit=512))
        elif event.type == "tool.failed":
            raise ModelValidationError("this provider cannot prove a failed external outcome")
        else:
            raise ModelValidationError("unsupported Action transition")
        updated["historical"] = not action_is_current(previous, state, project, at) or (
            bool(project.get("governance")) and project["status"] == "paused")
        if payload.get("queried") is True:
            updated["query_count"] += 1
    return updated


def _checkpoint(event, previous, state, project, at, actor):
    require(event.type == "checkpoint.created" and previous is None and event.aggregate_revision == 0,
            "Checkpoint is immutable")
    checkpoint = copy.deepcopy(event.payload["checkpoint"])
    task = state.get(f"task:{checkpoint['task_id']}")
    require(task is not None and task.get("execution_policy_version") == POLICY_VERSION
            and project["status"] in {"planning", "active"} and participant(state, actor), "Checkpoint scope denied")
    binding = current_fence(task, {**checkpoint, "actor_id": actor}, project, at)
    descriptor = binding["session"]
    require(task["status"] == "in_progress" and descriptor is not None
            and descriptor["id"] == checkpoint["session_id"] and descriptor["expires_at_wall_ms"] > at,
            "Checkpoint has no current Session")
    command = SimpleNamespace(id=event.causation_id, project_id=event.project_id, actor_id=actor,
        payload={"session_id": checkpoint["session_id"],
                 "context_snapshot": checkpoint["snapshot"]["context_snapshot"]["text"],
                 "remaining_work": checkpoint["snapshot"]["remaining_work"]})
    require(checkpoint == checkpoint_intent(command, task, state) and checkpoint["id"] == event.aggregate_id,
            "Checkpoint snapshot does not match current facts")
    return {**checkpoint, "revision": 0, "created_sequence": event.sequence, "observed_at_ms": at}


def validate_command_effect(event, command):
    """Verify runtime terminal facts against persisted intent, not just IDs."""
    if command.type not in COMMAND_AGGREGATES:
        return
    payload = event.payload
    require(payload.get("actor_id") == command.actor_id, "execution Event actor differs from Command")
    if command.type in {"tool.request", "checkpoint.create"}:
        record = payload["action" if command.type == "tool.request" else "checkpoint"]
        require(record["task_id"] == command.target_id, "execution child has wrong parent Task")
        for field in ("binding_id", "lease_epoch", "session_id"):
            require(canonical_json(record[field]) == canonical_json(command.payload.get(field)),
                    "execution child differs from Command fencing context")
        if command.type == "tool.request":
            require(record["requested_task_revision"] == command.expected_revision
                    and record["operation"] == command.payload.get("operation")
                    and canonical_json(record["requested_arguments"]) == canonical_json(command.payload.get("arguments")),
                    "Action does not represent the persisted Command intent")
            proof = record.get("authorization")
            if proof is not None:
                require(proof["approval_id"] == command.payload.get("approval_id")
                        and proof["requested_risk"] == command.payload.get("risk_level", "low"),
                        "Action changed its approval or requested risk")
            else:
                require("approval_id" not in command.payload, "Action omitted Command approval binding")
        else:
            snapshot = record["snapshot"]
            require(snapshot["task"]["revision"] == command.expected_revision
                    and snapshot["context_snapshot"]["text"] == command.payload.get("context_snapshot")
                    and canonical_json(snapshot["remaining_work"]) == canonical_json(command.payload.get("remaining_work")),
                    "Checkpoint does not represent the persisted Command intent")
    elif command.type in {"execution.start", "execution.report", "lease.renew", "lease.revoke"}:
        for field in ("binding_id", "lease_epoch"):
            require(canonical_json(payload.get(field)) == canonical_json(command.payload.get(field)),
                    "execution fact changed Command fencing context")
        if command.type == "execution.start":
            require(payload["session"]["id"] == child_id("session", command.project_id, command.id),
                    "Session was not allocated by its start Command")
        if command.type == "execution.report":
            require(payload["summary"] == command.payload.get("summary"), "report differs from Command")
        if command.type == "lease.revoke":
            require(payload["reason"] == command.payload.get("reason"), "revocation reason differs from Command")
    elif command.type in {"tool.report", "tool.reconcile"}:
        require(payload.get("queried") is (command.type == "tool.reconcile"), "query attribution differs from Command")
        if event.type == "tool.outcome_unknown":
            require(command.payload.get("outcome") == "unknown" and payload.get("reason") == command.payload.get("reason"),
                    "unknown report differs from Command")
        else:
            require(command.payload.get("outcome") == "completed"
                    and canonical_json(payload.get("result")) == canonical_json(command.payload.get("result")),
                    "result differs from Command")
