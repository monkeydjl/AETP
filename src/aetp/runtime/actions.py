"""Durable Action dispatch and conservative external query/reconciliation."""

from types import SimpleNamespace

from aetp.collaboration.policy import PolicyViolation
from aetp.domain.models import Command
from aetp.runtime.contracts import POLICY_VERSION, child_id
from aetp.runtime.policy import validate
from aetp.runtime.projection import action_is_current
from aetp.runtime.records import receipt


class ActionBroker:
    """Mixin for the trusted execution host, not an Agent-callable tool bag."""

    def _action_command(self, command, state, project, context):
        action = state.get(f"action:{command.target_id}")
        if action is None:
            raise PolicyViolation("INVALID_TARGET")
        self._revision(command, action)
        if command.actor_id != action["actor_id"]:
            raise PolicyViolation("PERMISSION_DENIED")
        if command.type == "tool.dispatch":
            validate(command.payload, set())
            if action["status"] != "pending":
                raise PolicyViolation("ACTION_NOT_PENDING")
            self._authorize_action(action, context.get("session"), state=state)
            return self._effect(command, state, "tool.invoked", {})
        if command.type == "tool.cancel":
            validate(command.payload, set())
            if action["status"] != "pending" or action_is_current(action, state, project, self._now(state)):
                raise PolicyViolation("RECONCILIATION_REQUIRED")
            return self._effect(command, state, "tool.cancelled", {})
        validate(command.payload, {"outcome", "result", "reason"})
        if action["status"] not in {"in_flight", "unknown"}:
            raise PolicyViolation("ACTION_ALREADY_RESOLVED")
        queried = command.type == "tool.reconcile"
        if command.payload.get("outcome") == "completed":
            result = command.payload.get("result")
            if result != receipt(action):
                raise PolicyViolation("RESULT_IDENTITY_MISMATCH")
            event = "tool.reconciled" if queried else "tool.completed"
            return self._effect(command, state, event, {"result": result, "queried": queried})
        if command.payload.get("outcome") == "unknown" and isinstance(command.payload.get("reason"), str):
            return self._effect(command, state, "tool.outcome_unknown", {
                "reason": command.payload["reason"], "queried": queried})
        raise PolicyViolation("INVALID_PAYLOAD")

    def _internal(self, action, kind, payload, *, session=None):
        key = child_id("broker", action["project_id"], f"{kind}:{action['id']}:{action['revision']}")
        command = Command(key, action["project_id"], action["actor_id"], kind, action["id"], payload,
                          action["revision"], key, action["correlation_id"])
        result = self._call(command, action["actor_id"], {"channel": "broker", "session": session})
        if result.status != "accepted":
            raise PolicyViolation(result.error_code)
        return self._state(action["project_id"])[f"action:{action['id']}"]

    def _expected_provider_identity(self, action):
        """Contract provider identity an Action must be bound to.

        An Action's ``workspace_provider_id`` identifies the trusted execution
        environment inherited from its Task/Project. A registered tool channel
        (``mcp.call``) runs inside that same environment, so it must not weaken
        or replace the environment binding.
        """
        if action["operation"] == "mcp.call" and getattr(self.runtime, "mcp_provider", None) is None:
            raise PolicyViolation("POLICY_UNAVAILABLE")
        return self.runtime.workspace.identity

    def _authorize_tool_channel(self, action):
        """Reject tool-channel violations before any external MCP request.

        Runs inside `_authorize_action`, i.e. before `dispatch` starts its
        try/except, so these are clean rejections rather than UNKNOWN outcomes.
        """
        provider = getattr(self.runtime, "mcp_provider", None)
        if provider is None:
            raise PolicyViolation("POLICY_UNAVAILABLE")
        arguments = action["arguments"]
        registration = provider.registry.resolve(arguments["server_id"], arguments["tool_name"])
        # Reject transport/server identity mismatch before dispatch's try/except,
        # so it cannot be misreported as an UNKNOWN outcome.
        declared_server = getattr(provider.server, "server_id", arguments["server_id"])
        if declared_server != registration.server_id:
            raise PolicyViolation("MCP_SERVER_MISMATCH")
        if provider.server.declared_tool_schema_digest(arguments["tool_name"]) != registration.schema_digest:
            raise PolicyViolation("MCP_SCHEMA_DRIFT")
        if registration.risk_level == "high":
            authorization = action.get("authorization")
            if not authorization or not authorization.get("approval_id"):
                raise PolicyViolation("APPROVAL_REQUIRED")

    def _authorize_action(self, action, session, *, state=None):
        state = self._state(action["project_id"]) if state is None else state
        address = SimpleNamespace(project_id=action["project_id"])
        project = self._project(address, state)
        if (action.get("policy_version") != POLICY_VERSION
                or action["workspace_provider_id"] != self._expected_provider_identity(action)):
            raise PolicyViolation("POLICY_UNAVAILABLE")
        if action["operation"] == "mcp.call":
            self._authorize_tool_channel(action)
        task = state.get(f"task:{action['task_id']}")
        if task is None:
            raise PolicyViolation("INVALID_TARGET")
        self._fence(task, action, action["actor_id"], project, state, self._now(state),
                    session=session, require_session=True)
        if task["status"] != "in_progress":
            raise PolicyViolation("TASK_NOT_EXECUTING")
        if project.get("governance") or action.get("authorization"):
            from aetp.governance.execution import authorize_action
            authorize_action(action, state, self._now(state))
        # Scoped credential ingestion: a consuming Action may carry a
        # credential_token_ref + required_permission. The broker checks scope,
        # wall-clock expiry and revocation at the real call boundary (fail-closed).
        credential_ref = action.get("arguments", {}).get("credential_token_ref")
        if credential_ref is not None:
            broker = getattr(self.runtime, "credential_broker", None)
            if broker is None:
                raise PolicyViolation("CREDENTIAL_UNAVAILABLE")
            required = action["arguments"].get("required_permission")
            if not isinstance(required, str) or not required.strip():
                raise PolicyViolation("INVALID_PAYLOAD")
            broker.assert_permission_by_ref(credential_ref, required, self._now(state))
        if not self._barriers.get(action["project_id"], False):
            raise PolicyViolation("RECOVERY_REQUIRED")

    def _effect_provider(self, action):
        """Route an Action to its operation's effect provider.

        Document operations keep the fixed workspace provider; trusted tool
        operations use the registered MCP provider bound to the same Runtime.
        """
        if action["operation"] == "mcp.call":
            provider = getattr(self.runtime, "mcp_provider", None)
            if provider is None:
                raise PolicyViolation("POLICY_UNAVAILABLE")
            return provider
        return self.runtime.workspace

    def dispatch(self, project_id, action_id, *, session):
        """Commit intent before effect. Unknown or terminal Actions never rerun."""
        if self.store.in_transaction:
            raise RuntimeError("external dispatch is forbidden inside a database transaction")
        with self.gate.hold():
            state = self._state(project_id)
            action = state.get(f"action:{action_id}")
            if action is None:
                raise PolicyViolation("INVALID_TARGET")
            self._authorize_action(action, session, state=state)
            if action["status"] != "pending":
                return action
            other = [row for row in self._unsettled(state, action["task_id"])
                     if row["id"] != action_id and row["status"] in {"in_flight", "unknown"}]
            if other:
                raise PolicyViolation("RECONCILIATION_REQUIRED")
            action = self._internal(action, "tool.dispatch", {}, session=session)
            # No SQLite transaction spans these calls. The OS resource gate
            # serializes revocation; the callback still checks durable facts.
            try:
                source_id = action["arguments"].get("source_action_id")
                if source_id is not None:
                    source = self._state(project_id).get(f"action:{source_id}")
                    if source is None or source["status"] != "completed":
                        raise PolicyViolation("SOURCE_UNVERIFIED")
                    query = self.runtime.workspace.query(source)
                    if (query.get("status") != "confirmed" or query.get("result") != receipt(source)
                            or query["result"]["envelope_digest"] != action["arguments"]["source_result_digest"]):
                        raise PolicyViolation("SOURCE_UNVERIFIED")
                result = self._effect_provider(action).write(
                    action, lambda: self._authorize_action(action, session))
            except Exception:
                return self._internal(action, "tool.report", {"outcome": "unknown", "reason": "PROVIDER_OUTCOME_UNKNOWN"})
            # A failure committing this report leaves IN_FLIGHT. Recovery
            # queries the original object; it must not repeat the write.
            return self._internal(action, "tool.report", {"outcome": "completed", "result": result})

    def _reconcile_locked(self, project_id, action_id):
        action = self._state(project_id).get(f"action:{action_id}")
        if action is None:
            raise PolicyViolation("INVALID_TARGET")
        if action["status"] not in {"in_flight", "unknown"}:
            return action
        # A rejected cross-provider reconciliation must not append an internal
        # tool.reconcile rejection using the Action's deterministic idempotency
        # key: that would poison the legitimate provider's later reconciliation.
        # Enforce the workspace boundary before touching the external provider
        # or submitting any internal Command.
        if action["workspace_provider_id"] != self.runtime.workspace.identity:
            raise PolicyViolation("WORKSPACE_MISMATCH")
        provider = self._effect_provider(action)
        try:
            query = provider.query(action)
        except Exception:
            query = {"status": "unknown", "reason": "QUERY_UNAVAILABLE"}
        if query.get("status") == "confirmed" and query.get("result") == receipt(action):
            payload = {"outcome": "completed", "result": query["result"]}
        else:
            payload = {"outcome": "unknown", "reason": query.get("reason", "QUERY_IDENTITY_MISMATCH")}
        return self._internal(action, "tool.reconcile", payload)

    def reconcile(self, project_id, action_id):
        """Trusted recovery query; stale/paused Actions still need accounting."""
        if self.store.in_transaction:
            raise RuntimeError("external query is forbidden inside a database transaction")
        with self.gate.hold():
            return self._reconcile_locked(project_id, action_id)
