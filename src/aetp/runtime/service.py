"""Fixed document execution through the existing atomic Command boundary."""

from contextvars import ContextVar
from dataclasses import replace
from dataclasses import asdict
import time

from aetp.collaboration.messages import participant
from aetp.collaboration.policy import PolicyViolation, text
from aetp.collaboration.service import CollaborationService
from aetp.core.projection import Projection
from aetp.domain.models import ModelValidationError
from aetp.runtime.contracts import (
    COMMAND_AGGREGATES, INTERNAL_COMMANDS, LEASE_MS, POLICY_VERSION, RUNTIME_ID,
    SESSION_MS, UNSETTLED, child_id,
)
from aetp.runtime.document import DocumentRuntime
from aetp.runtime.actions import ActionBroker
from aetp.runtime.policy import FENCE_FIELDS, binding_payload, governance, observed_time, validate
from aetp.runtime.records import action_intent, checkpoint_intent
from aetp.runtime.projection import action_is_current
from aetp.workspace.gate import ResourceGate


class ExecutionService(ActionBroker, CollaborationService):
    """Trusted host API; authenticated_actor_id comes from the host channel.

    The Agent supplies only Command data. It has no Python references to the
    store, Runtime registry, Provider or internal report channel.
    """

    def __init__(self, store, runtime, *, clock=None):
        super().__init__(store)
        if not isinstance(runtime, DocumentRuntime):
            raise TypeError("the fixed document Runtime is required")
        self.runtime = runtime
        self.clock = clock or (lambda: time.time_ns() // 1_000_000)
        self.gate = ResourceGate(store.database_path)
        self._context = ContextVar(f"execution_context_{id(self)}", default=None)
        self._barriers = {}

    def _call(self, command, actor, context):
        if self.store.in_transaction:
            raise RuntimeError("execution entry requires no existing database transaction")
        with self.gate.hold():
            token = self._context.set(context)
            try:
                return super().handle(command, authenticated_actor_id=actor)
            finally:
                self._context.reset(token)

    def handle(self, command, *, authenticated_actor_id, session=None):
        result = self._call(command, authenticated_actor_id, {"channel": "agent", "session": session})
        if result.status == "accepted" and command.type == "project.pause":
            self._barriers[command.project_id] = False
        return result

    def start_session(self, command, *, authenticated_actor_id):
        """Commit start then activate its credential. Replays never mint one."""
        if command.type != "execution.start":
            raise ValueError("start_session requires execution.start")
        context = {"channel": "start", "session": None}
        with self.gate.hold():
            result = self._call(command, authenticated_actor_id, context)
            if result.status != "accepted":
                return result, None
            state = self._state(command.project_id)
            task = state.get(f"task:{command.target_id}", {})
            binding = task.get("bindings", {}).get(task.get("current_binding_id"), {})
            descriptor = binding.get("session")
            expected_id = child_id("session", command.project_id, command.id)
            if descriptor is None or descriptor["id"] != expected_id or binding.get("status") != "running":
                return result, None
            if context.get("activate") == descriptor:
                return result, self.runtime.register(descriptor)
            # A previous accepted command is not permission to recreate a
            # lost external Session after a host restart.
            return result, self.runtime.lookup(expected_id)

    def _state(self, project_id):
        return Projection.rebuild(self.store.read_events(project_id))

    def validation_context(self, project_id, session):
        """Trusted observation for fixed consumers sharing this Runtime and gate.

        Consumers still check their own durable Task/Lease/Policy snapshot.
        Identical Session data without the registered object is not a capability.
        """
        return {"session": asdict(session) if self.runtime.registered(session) else None,
                "workspace_provider_id": self.runtime.workspace.identity,
                "barrier_open": self._barriers.get(project_id, False)}

    def governance_time(self, project_id):
        with self.gate.hold():
            state = self._state(project_id)
            return governance(state[f"project:{project_id}"], self._now(state))

    def _now(self, state):
        return observed_time(state, self.clock())

    def _project(self, command, state, *, active=True):
        project = state.get(f"project:{command.project_id}")
        if project is None:
            raise PolicyViolation("INVALID_TARGET")
        if project.get("execution_policy_version") != POLICY_VERSION:
            raise PolicyViolation("POLICY_UNAVAILABLE")
        if project.get("workspace_provider_id") != self.runtime.workspace.identity:
            raise PolicyViolation("WORKSPACE_MISMATCH")
        if active and project["status"] == "paused":
            raise PolicyViolation("PROJECT_PAUSED")
        if active and project["status"] not in {"planning", "active"}:
            raise PolicyViolation("PROJECT_INACTIVE")
        return project

    def _execution_task(self, command, state):
        task = state.get(f"task:{command.target_id}")
        if task is None:
            raise PolicyViolation("INVALID_TARGET")
        if task.get("execution_policy_version") != POLICY_VERSION:
            raise PolicyViolation("POLICY_UNAVAILABLE")
        return task

    @staticmethod
    def _revision(command, record):
        if command.expected_revision != record["revision"]:
            raise PolicyViolation("REVISION_CONFLICT")

    def _fence(self, task, payload, actor, project, state, at, *, session=None, require_session=False):
        binding_payload(payload)
        if (payload["binding_id"] != task["current_binding_id"]
                or payload["lease_epoch"] != task["lease_epoch"]
                or task["lease"] is None or task["lease"]["revoked"]
                or task["lease"]["expires_at_governance_ms"] <= governance(project, at)):
            raise PolicyViolation("STALE_EXECUTION")
        if task["owner_id"] != actor or not participant(state, actor):
            raise PolicyViolation("PERMISSION_DENIED")
        binding = task["bindings"][task["current_binding_id"]]
        if require_session:
            descriptor = binding.get("session")
            if (not self.runtime.registered(session) or descriptor is None
                    or payload.get("session_id") != descriptor["id"]
                    or any(getattr(session, key) != value for key, value in descriptor.items())):
                raise PolicyViolation("SESSION_INVALID")
            if at >= descriptor["expires_at_wall_ms"]:
                raise PolicyViolation("SESSION_EXPIRED")
        return binding

    @staticmethod
    def _unsettled(state, task_id):
        return [value for key, value in state.items() if key.startswith("action:")
                and value["task_id"] == task_id and value["status"] in UNSETTLED]

    def _effect(self, command, state, event_type, payload, *, aggregate=None, identifier=None):
        aggregate = aggregate or self._aggregate_address(command)[0]
        identifier = identifier or command.target_id
        previous = state.get(f"{aggregate}:{identifier}")
        revision = previous["revision"] + 1 if previous is not None else 0
        payload = {**payload, "actor_id": command.actor_id,
                   "observed_at_ms": self._context.get()["command_time_ms"]}
        return self._batch(command, state, [(event_type, aggregate, identifier, revision, payload)])

    def _evaluate(self, command, authenticated_actor_id):
        context = self._context.get() or {}
        state = self._state(command.project_id)
        task = state.get(f"task:{command.target_id}")
        owned_command = command.type in COMMAND_AGGREGATES or command.type == "task.create" or (
            command.type == "task.claim" and task and task.get("execution_policy_version"))
        if not owned_command:
            return super()._evaluate(command, authenticated_actor_id)
        try:
            if command.type in INTERNAL_COMMANDS and context.get("channel") not in {"start", "broker"}:
                raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
            if command.target_id is None:
                raise PolicyViolation("INVALID_TARGET")
            # One server observation supplies all timestamps in this atomic
            # batch. Final resource access still samples the live clock anew.
            context["command_time_ms"] = self._now(state)
            if command.type == "project.execution.configure":
                return self._configure(command, state)
            if command.type in {"project.pause", "project.resume"}:
                return self._project_control(command, state)
            allow_paused = command.type in {"lease.revoke", "task.requeue", "tool.report", "tool.reconcile", "tool.cancel"} or (
                command.type == "execution.report" and bool(state.get(f"project:{command.project_id}", {}).get("governance")))
            project = self._project(command, state, active=not allow_paused)
            at = context["command_time_ms"]
            if command.type in {"tool.dispatch", "tool.report", "tool.reconcile", "tool.cancel"}:
                return self._action_command(command, state, project, context)
            if command.type == "task.create":
                result, events = super()._evaluate(command, authenticated_actor_id)
                if result.status == "accepted":
                    events[-1] = replace(events[-1], payload={**events[-1].payload,
                        "execution_policy_version": POLICY_VERSION,
                        "workspace_provider_id": project["workspace_provider_id"]})
                return result, events
            task = self._execution_task(command, state)
            if task["status"] in {"completed", "cancelled", "failed"}:
                raise PolicyViolation("INVALID_TRANSITION")
            if command.type == "task.claim":
                return self._claim(command, task, state, project, at)
            if command.type == "lease.revoke":
                return self._revoke(command, task, state, project, at)
            if command.type == "task.requeue":
                validate(command.payload, set())
                self._revision(command, task)
                if task["lease"] is None or not task["lease"]["revoked"]:
                    raise PolicyViolation("REVOCATION_REQUIRED")
                if command.actor_id not in {"bootstrap", task["owner_id"]}:
                    raise PolicyViolation("PERMISSION_DENIED")
                if self._unsettled(state, task["id"]):
                    raise PolicyViolation("RECONCILIATION_REQUIRED")
                return self._effect(command, state, "task.requeued", {"reason": "execution_requeue"})

            fields = {"execution.start": set(), "lease.renew": set(), "execution.report": {"summary"},
                      "tool.request": {"operation", "arguments"},
                      "checkpoint.create": {"context_snapshot", "remaining_work"}}.get(command.type)
            if fields is None:
                raise PolicyViolation("UNSUPPORTED_COMMAND")
            governed_tool = command.type == "tool.request" and bool(project.get("governance"))
            validate(command.payload, fields | FENCE_FIELDS | ({"approval_id"} if governed_tool else set()),
                     governed=governed_tool)
            require_session = command.type not in {"execution.start", "lease.renew"} or (
                command.type == "lease.renew" and task["bindings"].get(task["current_binding_id"], {}).get("session") is not None)
            binding = self._fence(task, command.payload, command.actor_id, project, state, at,
                                  session=context.get("session"), require_session=require_session)
            self._revision(command, task)
            fence = {"binding_id": binding["id"], "lease_epoch": task["lease_epoch"]}
            if command.type == "lease.renew":
                return self._effect(command, state, "lease.renewed", {**fence,
                    "expires_at_governance_ms": governance(project, at) + LEASE_MS})
            if command.type == "execution.start":
                if not self._barriers.get(command.project_id, False):
                    raise PolicyViolation("RECOVERY_REQUIRED")
                if task["status"] != "assigned" or binding["session"] is not None:
                    raise PolicyViolation("SESSION_ALREADY_STARTED")
                descriptor = {"id": child_id("session", command.project_id, command.id),
                    "project_id": command.project_id, "task_id": task["id"], "actor_id": command.actor_id,
                    **fence, "expires_at_wall_ms": at + SESSION_MS}
                context["activate"] = descriptor
                return self._effect(command, state, "task.started", {**fence, "session": descriptor})
            if command.type == "execution.report":
                report = {**fence, "summary": text(command.payload.get("summary"))}
                if project["status"] == "paused":
                    report["while_paused"] = True
                return self._effect(command, state, "execution.reported", report)
            if command.type == "tool.request":
                if task["status"] != "in_progress":
                    raise PolicyViolation("TASK_NOT_EXECUTING")
                if any(action["status"] in {"in_flight", "unknown"} for action in self._unsettled(state, task["id"])):
                    raise PolicyViolation("RECONCILIATION_REQUIRED")
                action = action_intent(command, task, state)
                if governed_tool:
                    from aetp.governance.execution import authorize_action
                    authorize_action(action, state, at)
                return self._effect(command, state, "tool.requested", {"action": action},
                                    aggregate="action", identifier=action["id"])
            if command.type == "checkpoint.create":
                if task["status"] != "in_progress":
                    raise PolicyViolation("TASK_NOT_EXECUTING")
                checkpoint = checkpoint_intent(command, task, state)
                return self._effect(command, state, "checkpoint.created", {"checkpoint": checkpoint},
                                    aggregate="checkpoint", identifier=checkpoint["id"])
            raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
        except PolicyViolation as exc:
            return self._rejected(command, exc.code), []
        except ModelValidationError:
            return self._rejected(command, "INVALID_PAYLOAD"), []

    def _configure(self, command, state):
        validate(command.payload, set())
        if command.actor_id != "bootstrap":
            raise PolicyViolation("PERMISSION_DENIED")
        project = state.get(f"project:{command.project_id}")
        if project is None or command.target_id != command.project_id:
            raise PolicyViolation("INVALID_TARGET")
        self._revision(command, project)
        if "execution_clock" in project:
            raise PolicyViolation("ALREADY_CONFIGURED")
        if project["status"] not in {"planning", "active"}:
            raise PolicyViolation("PROJECT_INACTIVE")
        return self._effect(command, state, "project.execution_configured", {
            "policy_version": POLICY_VERSION, "workspace_provider_id": self.runtime.workspace.identity})

    def _project_control(self, command, state):
        if state.get(f"project:{command.project_id}", {}).get("governance"):
            raise PolicyViolation("GOVERNANCE_REQUIRED")
        validate(command.payload, set())
        if command.actor_id != "bootstrap":
            raise PolicyViolation("PERMISSION_DENIED")
        project = self._project(command, state, active=False)
        if command.target_id != command.project_id:
            raise PolicyViolation("INVALID_TARGET")
        self._revision(command, project)
        if command.type == "project.pause":
            if project["status"] not in {"planning", "active"}:
                raise PolicyViolation("PROJECT_INACTIVE")
            kind, status = "project.paused", "paused"
        else:
            if project["status"] != "paused":
                raise PolicyViolation("PROJECT_NOT_PAUSED")
            kind, status = "project.resumed", project["paused_from"]
        return self._effect(command, state, kind, {"status": status,
            "elapsed_ms": governance(project, self._context.get()["command_time_ms"])})

    def _claim(self, command, task, state, project, at):
        validate(command.payload, set())
        if not participant(state, command.actor_id):
            raise PolicyViolation("PERMISSION_DENIED")
        self._revision(command, task)
        if task["status"] != "pending" or task["owner_id"] is not None:
            raise PolicyViolation("TASK_NOT_ASSIGNABLE")
        epoch = task["lease_epoch"] + 1
        identifier = child_id("binding", command.project_id, command.id)
        checkpoints = [value for key, value in state.items() if key.startswith("checkpoint:") and value["task_id"] == task["id"]]
        latest = max(checkpoints, key=lambda value: value["created_sequence"]) if checkpoints else None
        binding = {"id": identifier, "agent_id": command.actor_id, "lease_epoch": epoch,
                   "runtime_id": RUNTIME_ID, "workspace_provider_id": project["workspace_provider_id"],
                   "status": "assigned", "session": None,
                   "resume_checkpoint_id": latest["id"] if latest else None}
        lease = {"owner_id": command.actor_id, "binding_id": identifier, "lease_epoch": epoch,
                 "expires_at_governance_ms": governance(project, at) + LEASE_MS, "revoked": False}
        return self._effect(command, state, "task.claimed", {"binding_id": identifier, "lease_epoch": epoch,
                                                             "binding": binding, "lease": lease})

    def _revoke(self, command, task, state, project, at):
        validate(command.payload, FENCE_FIELDS | {"reason"})
        binding_payload(command.payload)
        self._revision(command, task)
        if (command.payload["binding_id"] != task["current_binding_id"]
                or command.payload["lease_epoch"] != task["lease_epoch"]
                or task["lease"] is None or task["lease"]["revoked"]):
            raise PolicyViolation("STALE_EXECUTION")
        reason = command.payload.get("reason")
        if not ((reason == "handoff" and command.actor_id == task["owner_id"])
                or (reason == "expired" and command.actor_id == "bootstrap"
                    and task["lease"]["expires_at_governance_ms"] <= governance(project, at))):
            raise PolicyViolation("PERMISSION_DENIED")
        return self._effect(command, state, "lease.revoked", {"binding_id": task["current_binding_id"],
                            "lease_epoch": task["lease_epoch"], "reason": reason})

    def recover(self, project_id):
        """Rebuild first; no automatic starts or repeat dispatches."""
        if self.store.in_transaction:
            raise RuntimeError("recovery queries require no existing transaction")
        with self.gate.hold():
            self._barriers[project_id] = False
            state = self._state(project_id)
            project = state.get(f"project:{project_id}")
            if project is None or project.get("workspace_provider_id") != self.runtime.workspace.identity:
                raise PolicyViolation("WORKSPACE_MISMATCH")
            from aetp.core.runtime import RuntimeRecovery
            pending_commands = RuntimeRecovery(self.store).reconcile_pending(project_id)
            at = self._now(state)
            reconciled, cancelled = [], []
            for key, action in list(state.items()):
                if not key.startswith("action:"):
                    continue
                if action["status"] in {"in_flight", "unknown"}:
                    self._reconcile_locked(project_id, action["id"])
                    reconciled.append(action["id"])
                elif action["status"] == "pending" and not action_is_current(action, state, project, at):
                    self._internal(action, "tool.cancel", {})
                    cancelled.append(action["id"])
            state = self._state(project_id)
            missing = []
            for key, task in state.items():
                if not key.startswith("task:") or not task.get("current_binding_id") or task["lease"]["revoked"]:
                    continue
                descriptor = task["bindings"][task["current_binding_id"]]["session"]
                if descriptor and (self.runtime.lookup(descriptor["id"]) is None or descriptor["expires_at_wall_ms"] <= at):
                    missing.append(descriptor["id"])
            unknown = [value["id"] for key, value in state.items()
                       if key.startswith("action:") and value["status"] in {"in_flight", "unknown"}]
            opened = project["status"] in {"planning", "active"} and not missing and not unknown and not pending_commands
            if project.get("governance"):
                checks = self.recovery_status(project_id, at=self._now(state))["checks"]
                opened = opened and checks["ready"]
                unknown = checks["unknown_actions"]
            self._barriers[project_id] = opened
            return {"barrier": "open" if opened else "closed", "missing_sessions": missing, "unknown_actions": unknown,
                    "reconciled_actions": reconciled, "cancelled_actions": cancelled, "pending_commands": pending_commands}

    def recovery_status(self, project_id, *, exclude_command_id=None, at=None):
        """Check live registered Sessions and durable facts without provider IO.

        The governance caller already holds gate -> writer transaction; the
        nested acquisition keeps public callers on the same ordering. Ignoring
        only that caller's just-persisted, not-yet-received Command avoids
        misclassifying the transaction currently being validated as recovery.
        """
        from aetp.core.runtime import RuntimeRecovery
        from aetp.governance.controls import recovery_assessment
        with self.gate.hold(), self.store.transaction():
            events = self.store.read_events(project_id)
            state = Projection.rebuild(events)
            commands = [command for command in RuntimeRecovery(self.store)._read_commands(project_id)
                        if command.id != exclude_command_id]
            pending = Projection.pending_command_ids(events, commands)
            live = {}
            for key, task in state.items():
                if not key.startswith("task:") or not task.get("current_binding_id"):
                    continue
                descriptor = task["bindings"][task["current_binding_id"]]["session"]
                session = self.runtime.lookup(descriptor["id"]) if descriptor else None
                if session is not None and self.runtime.registered(session):
                    live[session.id] = asdict(session)
            observations = {"live_sessions": live, "pending_commands": pending,
                            "workspace_provider_id": self.runtime.workspace.identity}
            at = self._now(state) if at is None else observed_time(state, at)
            return {"observations": observations, "checks": recovery_assessment(state, project_id, at, observations)}
