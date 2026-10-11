"""Trusted governance host. Compounds commit atomically; Replay never invokes it."""

from contextvars import ContextVar
import copy

from aetp.collaboration.policy import PolicyViolation
from aetp.core.idempotency import IdempotencyConflict
from aetp.core.projection import Projection
from aetp.domain.models import Command, ModelValidationError
from aetp.governance.contracts import COMMAND_AGGREGATES, SCHEMA, system_actor
from aetp.governance.causality import command_id, continuations, expiry_id
from aetp.governance.policy import current
from aetp.governance.projection import evaluate
from aetp.governance.snapshots import snapshot
from aetp.governance.trust import InputAuthority
from aetp.meetings.service import MeetingService
from aetp.meetings.policy import projected_time
from aetp.runtime.contracts import child_id
from aetp.runtime.policy import observed_time
from aetp.workspace.gate import ResourceGate


class GovernanceService(MeetingService):
    """Only the host receives this object, Runtime, store and input issuer.

    Agent requests are data plus a trusted connection identity. Human identity
    is rooted explicitly on first configuration and subsequently in Events.
    """

    def __init__(self, store, *, owner_id=None, execution=None, input_authority=None, meter=None, clock=None):
        super().__init__(store, meter=meter, clock=clock)
        if input_authority is not None and not isinstance(input_authority, InputAuthority):
            raise TypeError("a trusted InputAuthority is required")
        if execution is not None and execution.store is not store:
            raise ValueError("execution and governance must use the same store")
        self.owner_id = owner_id
        self.execution = execution
        self.input_authority = input_authority
        self.gate = ResourceGate(store.database_path)
        self._governance_context = ContextVar(f"governance_{id(self)}", default=None)

    def snapshot(self, project_id, target_type, target_id):
        return snapshot(Projection.rebuild(self.store.read_events(project_id)), target_type, target_id)

    def handle(self, command, *, authenticated_actor_id, input_receipt=None):
        if not isinstance(command, Command):
            raise TypeError("Command required")
        if command.type not in COMMAND_AGGREGATES:
            return super().handle(command, authenticated_actor_id=authenticated_actor_id)
        if self.store.in_transaction:
            raise RuntimeError("governance entry requires gate before writer transaction")
        with self.gate.hold():
            actor = self._authenticated_actor(authenticated_actor_id)
            if command.actor_id == actor:
                try:
                    prior = self._idempotency.lookup((command.project_id, actor, command.idempotency_key), command.digest())
                except IdempotencyConflict:
                    return self._rejected(command, "IDEMPOTENCY_CONFLICT")
                if prior is not None:
                    return prior
            context = {"input_receipt": input_receipt}
            if command.type == "project.resume" and command.actor_id == actor:
                from aetp.governance.controls import project_control_input
                try:
                    state = Projection.rebuild(self.store.read_events(command.project_id))
                    project = project_control_input(command, state)
                    if project.get("execution_policy_version"):
                        if self.execution is None:
                            raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
                        # Reconciliation can query external documents. It runs
                        # before the writer transaction, with the gate held.
                        self.execution.recover(command.project_id)
                except PolicyViolation as exc:
                    context["forced_error"] = exc.code
            with self.store.transaction():
                result = self._submit(command, actor, context)
            if result.status == "accepted" and command.type == "project.pause" and self.execution is not None:
                self.execution._barriers[command.project_id] = False
            return result

    def _submit(self, command, actor, context):
        # Authentication and existing result take precedence over new clocks,
        # ingress capabilities or continuation work.
        actor = self._authenticated_actor(actor)
        if command.actor_id != actor:
            return super().handle(command, authenticated_actor_id=actor)
        try:
            prior = self._idempotency.lookup((command.project_id, actor, command.idempotency_key), command.digest())
        except IdempotencyConflict:
            return self._rejected(command, "IDEMPOTENCY_CONFLICT")
        if prior is not None:
            return prior
        token = self._governance_context.set(context)
        try:
            try:
                with self.store.transaction():
                    result = super().handle(command, authenticated_actor_id=actor)
                    if result.status == "accepted":
                        self._followups(command, context)
                    return result
            except PolicyViolation as exc:
                # Normal child rejections return a result; _child converts them
                # to this exception. The savepoint removes every partial child
                # and parent result before auditing the rejected parent intent.
                if context.get("parent_command_id") is not None:
                    raise
                context["forced_error"] = exc.code
                return super().handle(command, authenticated_actor_id=actor)
        finally:
            self._governance_context.reset(token)

    def _rejection_events(self, command, result):
        # A rejected child cannot coexist with its parent's accepted fact.
        # Propagate before appending it so the outer savepoint can roll back
        # the compound and persist a typed rejection of the original intent.
        context = self._governance_context.get() or {}
        if context.get("internal") is True and context.get("parent_command_id") is not None:
            raise PolicyViolation(result.error_code)
        return super()._rejection_events(command, result)

    def _evaluate(self, command, authenticated_actor_id):
        if command.type not in COMMAND_AGGREGATES:
            return super()._evaluate(command, authenticated_actor_id)
        context = self._governance_context.get() or {}
        if context.get("forced_error"):
            return self._rejected(command, context["forced_error"]), []
        events = self.store.read_events(command.project_id)
        state = Projection.rebuild(events)
        try:
            at = context.get("at")
            if at is None:
                at = observed_time(state, self.clock())
                context["at"] = at
            data = {"idempotency_key": command.idempotency_key}
            data.update({key: copy.deepcopy(context[key]) for key in ("internal", "parent_command_id", "trigger") if key in context})
            if command.type == "project.governance.configure":
                data.update(bootstrap_owner=self.owner_id,
                            input_authority_id=self.input_authority.source_id if self.input_authority else None)
            if command.type == "approval.request" and context.get("input_receipt") is not None:
                if self.input_authority is None:
                    raise PolicyViolation("INPUT_CONTEXT_INVALID")
                data["input_proof"] = self.input_authority.verify(command, context["input_receipt"])
            if command.type == "project.resume":
                if state[f"project:{command.project_id}"].get("execution_policy_version"):
                    if self.execution is None:
                        raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
                    data["recovery_observations"] = self.execution.recovery_status(
                        command.project_id, exclude_command_id=command.id, at=at)["observations"]
                else:
                    from aetp.core.runtime import RuntimeRecovery
                    # The writer transaction already fixes both reads to one
                    # snapshot. Only this newly persisted resume has no receipt
                    # yet; every older incomplete Command still blocks resume.
                    commands = [saved for saved in RuntimeRecovery(self.store)._read_commands(command.project_id)
                                if saved.id != command.id]
                    data["recovery_observations"] = {
                        "live_sessions": {}, "pending_commands": Projection.pending_command_ids(events, commands),
                        "workspace_provider_id": None}
            kind, record = evaluate(command, state, at, data)
            payload = {"governance_schema": SCHEMA, "actor_id": command.actor_id, "command_type": command.type,
                       "command_payload": command.payload, "expected_revision": command.expected_revision,
                       "observed_at_ms": at, "context": data, "record": record,
                       "continuations": continuations(command, record, state)}
            return self._batch(command, state, [(kind, COMMAND_AGGREGATES[command.type], command.target_id,
                                                record["revision"], payload)])
        except PolicyViolation as exc:
            return self._rejected(command, exc.code), []
        except (ModelValidationError, TypeError, KeyError, ValueError):
            return self._rejected(command, "INVALID_PAYLOAD"), []

    def _child(self, parent, kind, target, payload, context, *, actor=None):
        state = Projection.rebuild(self.store.read_events(parent.project_id))
        previous = state.get(f"{COMMAND_AGGREGATES[kind]}:{target}")
        key = command_id(parent.project_id, parent.id, kind, target)
        actor = actor or system_actor(parent.project_id)
        command = Command(key, parent.project_id, actor, kind, target, payload,
                          previous["revision"] if previous else 0, key, parent.correlation_id)
        child_context = {"internal": True, "parent_command_id": parent.id, "at": context["at"]}
        result = self._submit(command, actor, child_context)
        if result.status != "accepted":
            raise PolicyViolation(result.error_code)
        return result

    def _followups(self, command, context):
        fact = next(event for event in self.store.read_events(command.project_id)
                    if event.causation_id == command.id and event.payload.get("governance_schema") == SCHEMA)
        for child in fact.payload["continuations"]:
            self._child(command, child["type"], child["target_id"], child["payload"], context, actor=child["actor_id"])

    def tick(self, project_id):
        """Trusted host scan; no background task or external notification sender."""
        if self.store.in_transaction:
            raise RuntimeError("governance tick requires gate before writer transaction")
        with self.gate.hold(), self.store.transaction():
            state = Projection.rebuild(self.store.read_events(project_id))
            current(state, project_id)
            at = observed_time(state, self.clock())
            elapsed = projected_time(state[f"project:{project_id}"], at)
            expired = []
            for key, approval in state.items():
                if not key.startswith("approval:") or approval["status"] not in {"pending", "approved"} or elapsed < approval["expires_at"]:
                    continue
                key = expiry_id(project_id, approval["id"], approval["revision"])
                command = Command(key, project_id, system_actor(project_id), "approval.expire", approval["id"], {},
                                  approval["revision"], key, approval["origin_command_id"])
                result = self._submit(command, command.actor_id, {"internal": True, "trigger": "host_tick", "at": at})
                if result.status != "accepted":
                    raise PolicyViolation(result.error_code)
                expired.append(approval["id"])
            return {"expired_approval_ids": expired}
