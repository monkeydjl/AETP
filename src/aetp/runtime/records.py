"""Deterministic document intent and result identities, without IO."""

import copy
import base64

from aetp.collaboration.policy import PolicyViolation, digest_text, digest_value, strings, text
from aetp.runtime.contracts import POLICY_VERSION, UNSETTLED, child_id


def normalize_arguments(operation, arguments, task, state):
    if not isinstance(operation, str) or not isinstance(arguments, dict):
        raise PolicyViolation("INVALID_PAYLOAD")
    if operation.startswith(("shell.", "network.", "credential.")) or operation == "document.publish":
        raise PolicyViolation("APPROVAL_REQUIRED")
    if operation == "mcp.call":
        # Generic trusted-tool channel: no document keys and no caller-supplied
        # filesystem scope may be smuggled through a tool call.
        if arguments.keys() != {"server_id", "tool_name", "tool_arguments"}:
            raise PolicyViolation("INVALID_PAYLOAD")
        tool_arguments = arguments.get("tool_arguments")
        if not isinstance(tool_arguments, dict):
            raise PolicyViolation("INVALID_PAYLOAD")
        # Only genuine filesystem/workspace scope keys are denied here; business
        # argument names such as `target` belong to the registered tool schema.
        if tool_arguments.keys() & {"path", "filename", "root", "workspace", "workspace_id"}:
            raise PolicyViolation("WORKSPACE_SCOPE_DENIED")
        return {"server_id": text(arguments.get("server_id"), identifier=True),
                "tool_name": text(arguments.get("tool_name"), identifier=True),
                "tool_arguments": copy.deepcopy(tool_arguments)}
    if operation not in {"document.write", "document.restore", "document.append"}:
        raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
    if arguments.keys() & {"path", "filename", "target", "root", "workspace", "workspace_id"}:
        raise PolicyViolation("WORKSPACE_SCOPE_DENIED")
    if operation == "document.write":
        if arguments.keys() != {"content"}:
            raise PolicyViolation("INVALID_PAYLOAD")
        return {"content": text(arguments.get("content"))}
    if operation == "document.restore":
        if arguments.keys() != {"checkpoint_id"}:
            raise PolicyViolation("INVALID_PAYLOAD")
        identifier = text(arguments.get("checkpoint_id"), identifier=True)
        checkpoint = state.get(f"checkpoint:{identifier}")
        binding = task["bindings"][task["current_binding_id"]]
        if (checkpoint is None or checkpoint["task_id"] != task["id"]
                or binding["resume_checkpoint_id"] != identifier
                or not checkpoint["snapshot"]["document_actions"]):
            raise PolicyViolation("INVALID_REFERENCE")
        source_ref = checkpoint["snapshot"]["document_actions"][-1]
        source_id = source_ref["action_id"]
    else:
        if arguments.keys() != {"source_action_id", "text"}:
            raise PolicyViolation("INVALID_PAYLOAD")
        source_id = text(arguments.get("source_action_id"), identifier=True)
    source = state.get(f"action:{source_id}")
    if source is None or source["task_id"] != task["id"] or source["status"] != "completed":
        raise PolicyViolation("INVALID_REFERENCE")
    if operation == "document.append" and source["binding_id"] != task["current_binding_id"]:
        raise PolicyViolation("WORKSPACE_SCOPE_DENIED")
    if operation == "document.restore" and source_ref["result_digest"] != source["result"]["envelope_digest"]:
        raise PolicyViolation("INVALID_REFERENCE")
    content = source["arguments"]["content"]
    if operation == "document.append":
        content += text(arguments.get("text"))
    normalized = {"content": text(content), "source_action_id": source_id,
                  "source_result_digest": source["result"]["envelope_digest"]}
    if operation == "document.restore":
        normalized["checkpoint_id"] = identifier
    return normalized


def action_intent(command, task, state):
    arguments = normalize_arguments(command.payload.get("operation"), command.payload.get("arguments"), task, state)
    result = {"id": child_id("action", command.project_id, command.id), "project_id": command.project_id,
            "task_id": task["id"], "actor_id": command.actor_id,
            "binding_id": task["current_binding_id"], "lease_epoch": task["lease_epoch"],
            "session_id": command.payload["session_id"], "policy_version": POLICY_VERSION,
            "workspace_provider_id": task["workspace_provider_id"], "operation": command.payload["operation"],
            "requested_arguments": copy.deepcopy(command.payload["arguments"]), "arguments": arguments,
            "arguments_digest": digest_value(arguments), "requested_task_revision": task["revision"],
            "request_command_id": command.id, "correlation_id": command.correlation_id}
    if state[f"project:{command.project_id}"].get("governance"):
        from aetp.governance.execution import authorization_record
        result["authorization"] = authorization_record(command.payload.get("approval_id"), state,
                                                        command.payload.get("risk_level", "low"))
    return result


def object_key(action):
    # Full SHA-256 in case-normalized base32 keeps the layout short enough
    # for ordinary Windows consumers, without truncating identity entropy.
    def component(kind, identifier):
        digest = child_id(kind, action["project_id"], identifier).split("-", 1)[1]
        return base64.b32encode(bytes.fromhex(digest)).decode("ascii").lower().rstrip("=")
    project = "p-" + component("project", action["project_id"])
    binding = "b-" + component("copy", action["binding_id"])
    document = component("object", action["id"]) + ".json"
    return f"{project}/{binding}/{document}"


def envelope(action):
    common = {"project_id": action["project_id"],
              "task_id": action["task_id"], "binding_id": action["binding_id"], "lease_epoch": action["lease_epoch"],
              "action_id": action["id"], "operation": action["operation"],
              "arguments_digest": action["arguments_digest"]}
    if action["operation"] == "mcp.call":
        # Generic trusted-tool envelope: binds tool identity without document keys.
        return {**common, "schema_version": "aetp-mcp-call-1",
                "server_id": action["arguments"]["server_id"],
                "tool_name": action["arguments"]["tool_name"],
                "tool_arguments_digest": digest_value(action["arguments"]["tool_arguments"])}
    return {**common, "schema_version": "aetp-fixed-document-1", "object_key": object_key(action),
            "content": action["arguments"]["content"],
            "content_digest": digest_text(action["arguments"]["content"])}


def receipt(action):
    document = envelope(action)
    result = {"action_id": action["id"], "arguments_digest": action["arguments_digest"],
              "envelope_digest": digest_value(document)}
    if action["operation"] == "mcp.call":
        return result
    result.update(content_digest=document["content_digest"], object_key=document["object_key"])
    return result


def checkpoint_intent(command, task, state):
    if any(key.startswith("action:") and value["task_id"] == task["id"] and value["status"] in UNSETTLED
           for key, value in state.items()):
        raise PolicyViolation("RECONCILIATION_REQUIRED")
    context = text(command.payload.get("context_snapshot"))
    remaining = strings(command.payload.get("remaining_work"))
    actions = sorted((value for key, value in state.items() if key.startswith("action:")
                      and value["task_id"] == task["id"] and value["binding_id"] == task["current_binding_id"]
                      and value["status"] == "completed"), key=lambda value: value["created_sequence"])
    artifacts = [{"artifact_id": value["id"], "content_digest": value["content_digest"], "authority": "candidate_only"}
                 for key, value in state.items() if key.startswith("artifact:") and value["task_id"] == task["id"]]
    snapshot = {"task": copy.deepcopy(task), "agent": copy.deepcopy(state[f"agent:{command.actor_id}"]),
                "git": {"status": "not_applicable", "reason": "fixed document Runtime has no Git working tree"},
                "decisions": {"status": "not_applicable", "reason": "M1 has no Decision implementation"},
                "artifacts": artifacts,
                "document_actions": [{"action_id": action["id"], "result_digest": action["result"]["envelope_digest"],
                                      "content_digest": action["result"]["content_digest"]} for action in actions],
                "context_snapshot": {"text": context, "source": {"command_id": command.id,
                    "actor_id": command.actor_id, "untrusted_input": True, "authority": "context_only"}},
                "remaining_work": remaining}
    return {"id": child_id("checkpoint", command.project_id, command.id), "project_id": command.project_id,
            "task_id": task["id"], "actor_id": command.actor_id, "binding_id": task["current_binding_id"],
            "lease_epoch": task["lease_epoch"], "session_id": command.payload["session_id"],
            "policy_version": POLICY_VERSION, "snapshot": snapshot, "snapshot_digest": digest_value(snapshot)}
