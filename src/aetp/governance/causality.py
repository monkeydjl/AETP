"""Pure compound descriptions and causal cursors; never dispatch child Commands."""

import copy

from aetp.collaboration.policy import PolicyViolation, canonical_json, text
from aetp.domain.models import ModelValidationError
from aetp.governance.contracts import COMMAND_AGGREGATES, INTERNAL_COMMANDS, SCHEMA, system_actor
from aetp.runtime.contracts import child_id


def command_id(project_id, parent_id, kind, target):
    return child_id("governance", project_id, canonical_json([parent_id, kind, target]))


def expiry_id(project_id, approval_id, revision):
    return child_id("expiry", project_id, canonical_json([approval_id, revision]))


def validate_context(command, state, context):
    from aetp.governance.policy import fields
    allowed = {"idempotency_key"}
    required = {"idempotency_key"}
    if context.get("internal") is True:
        if command.type not in INTERNAL_COMMANDS | {"approval.grant", "task.governance.stop"}:
            raise PolicyViolation("PERMISSION_DENIED")
        if command.type == "approval.expire":
            allowed |= {"internal", "trigger"}
            required |= {"internal", "trigger"}
            previous = state.get(f"approval:{command.target_id}")
            if (context.get("trigger") != "host_tick" or previous is None
                    or command.id != expiry_id(command.project_id, previous["id"], previous["revision"])
                    or command.correlation_id != previous["origin_command_id"]):
                raise PolicyViolation("INVALID_CAUSAL_CONTEXT")
        else:
            allowed |= {"internal", "parent_command_id"}
            required |= {"internal", "parent_command_id"}
            parent = text(context.get("parent_command_id"), identifier=True)
            if command.id != command_id(command.project_id, parent, command.type, command.target_id):
                raise PolicyViolation("INVALID_CAUSAL_CONTEXT")
        if command.idempotency_key != command.id:
            raise PolicyViolation("INVALID_CAUSAL_CONTEXT")
    elif command.type in INTERNAL_COMMANDS | {"task.governance.stop"}:
        raise PolicyViolation("PERMISSION_DENIED")
    elif command.type == "project.governance.configure":
        allowed |= {"bootstrap_owner", "input_authority_id"}
        required |= {"bootstrap_owner", "input_authority_id"}
        previous = state.get(f"project:{command.project_id}", {}).get("governance")
        if previous and (context.get("bootstrap_owner") not in {None, previous["owner_id"]}
                         or context.get("input_authority_id") not in {None, previous["input_authority_id"]}):
            raise PolicyViolation("INVALID_CAUSAL_CONTEXT")
    elif command.type == "approval.request":
        allowed.add("input_proof")
    elif command.type == "credential.request":
        allowed.add("broker_token_ref")
    elif command.type == "project.resume":
        allowed.add("recovery_observations")
        required.add("recovery_observations")
    fields(context, allowed, required)
    if context["idempotency_key"] != command.idempotency_key:
        raise PolicyViolation("INVALID_CAUSAL_CONTEXT")


def continuations(command, record, state):
    """Describe the required children from this transition's original snapshot."""
    after = {**state, f"{COMMAND_AGGREGATES[command.type]}:{command.target_id}": record}
    result = []

    def add(kind, target, payload, actor=None):
        result.append({"id": command_id(command.project_id, command.id, kind, target),
                       "type": kind, "target_id": target, "payload": copy.deepcopy(payload),
                       "actor_id": actor or system_actor(command.project_id)})

    def impact(approval, reason):
        target = approval["target"]
        if target["type"] == "decision":
            decision = after[f"decision:{target['id']}"]
            if decision.get("approval_id") in {None, approval["id"]}:
                add("decision.invalidate", target["id"], {"approval_id": approval["id"], "reason": reason})
        elif (target["type"] == "task" and approval["risk_level"] in {"high", "critical"}
              and reason in {"approval_expired", "approval_revoked"}
              and after[f"task:{target['id']}"]["status"] not in {"completed", "cancelled", "failed"}):
            add("task.governance.block", target["id"], {"approval_id": approval["id"], "reason": reason})

    if command.type in {"project.pause", "project.resume"}:
        add("intervention.record", command.payload["intervention_id"], {})
    elif command.type == "intervention.apply":
        add("task.governance.stop", command.payload["target"]["id"],
            {"intervention_id": command.target_id}, command.actor_id)
    elif command.type in {"approval.request", "approval.renew"}:
        if record["routing"]["mode"] == "delegated":
            add("approval.delegate", command.target_id, {})
        elif record["routing"]["mode"] == "auto":
            add("approval.grant", command.target_id, {"reason": "deterministic policy rule"})
    elif command.type == "project.governance.configure":
        version = record["governance"]["current_version"]
        for key in sorted(after):
            approval = after[key]
            if key.startswith("approval:") and approval["validity"] == "current" and approval["policy_version"] != version:
                add("approval.invalidate", approval["id"], {"reason": "policy_changed"})
    elif command.type == "approval.expire":
        resolution = record["expiration_resolution"]
        if resolution["kind"] == "renew":
            add("approval.renew", resolution["next_approval_id"],
                {"previous_id": record["id"], "previous_revision": record["revision"]})
        else:
            if resolution["kind"] == "escalate":
                add("approval.escalate", record["id"], {"reason": resolution["reason"]})
            impact(record, "approval_expired")
    elif command.type in {"approval.revoke", "approval.deny", "approval.invalidate"}:
        reason = {"approval.revoke": "approval_revoked", "approval.deny": "approval_denied",
                  "approval.invalidate": "policy_changed"}[command.type]
        if command.type == "approval.revoke":
            add("approval.escalate", record["id"], {"reason": reason})
        impact(record, reason)
    return result


class CausalCursor:
    """Transient Replay state; a partial compound is visible but never complete."""

    def __init__(self, frames=()):
        self.frames = list(frames)

    @property
    def pending(self):
        return {frame["command_id"] for frame in self.frames}

    def advance(self, event):
        if event.type in {"command.received", "command.rejected"}:
            # Audit payloads do not pass a governance domain reducer. They
            # must never use a claimed envelope to create or consume frames.
            if "governance_schema" in event.payload:
                raise ModelValidationError("audit Event cannot carry a governance effect envelope")
            if self.frames:
                expected = self.frames[-1]["remaining"][0]
                if (event.type != "command.received" or event.causation_id != expected["id"]
                        or event.payload.get("command_type") != expected["type"]):
                    raise ModelValidationError("required governance child missing, rejected or out of order")
            return self
        governed = event.payload.get("governance_schema") == SCHEMA
        if not governed:
            if self.frames:
                raise ModelValidationError("required governance child replaced by unrelated domain fact")
            return self
        frames = copy.deepcopy(self.frames)
        context = event.payload["context"]
        if frames:
            parent = frames[-1]
            expected = parent["remaining"][0]
            actual = {"id": event.causation_id, "type": event.payload["command_type"],
                      "target_id": event.aggregate_id, "payload": event.payload["command_payload"],
                      "actor_id": event.payload["actor_id"]}
            if (canonical_json(actual) != canonical_json(expected) or context.get("internal") is not True
                    or context.get("parent_command_id") != parent["command_id"]
                    or event.correlation_id != parent["correlation_id"]
                    or event.payload["observed_at_ms"] != parent["observed_at_ms"]):
                raise ModelValidationError("governance child differs from its required parent continuation")
            parent["remaining"].pop(0)
        elif context.get("parent_command_id") is not None or (
                context.get("internal") is True and context.get("trigger") != "host_tick"):
            raise ModelValidationError("internal governance child has no preceding parent")
        children = event.payload["continuations"]
        if children:
            frames.append({"command_id": event.causation_id, "correlation_id": event.correlation_id,
                           "observed_at_ms": event.payload["observed_at_ms"], "remaining": copy.deepcopy(children)})
        while frames and not frames[-1]["remaining"]:
            frames.pop()
        return CausalCursor(frames)
