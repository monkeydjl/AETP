"""Trusted Verification host; durable single-use grant precedes the fixed call."""

import copy
from contextvars import ContextVar

from aetp.acceptance.contracts import (
    COMMAND_AGGREGATES,
    INTERNAL_COMMANDS,
    SCHEMA,
    system_actor,
)
from aetp.acceptance.records import _observation, authorization_error, evaluate
from aetp.acceptance.runner import FixedJsonRunner
from aetp.collaboration.policy import PolicyViolation
from aetp.core.commands import CommandHandler
from aetp.core.projection import Projection
from aetp.domain.models import Command, ModelValidationError
from aetp.planning.service import PlanningService
from aetp.runtime.contracts import child_id
from aetp.runtime.policy import observed_time


class AcceptanceService(PlanningService):
    """Agent-facing calls accept data; host dispatch/record contexts stay private."""

    def __init__(self, store, **kwargs):
        super().__init__(store, **kwargs)
        self._acceptance_context = ContextVar(f"acceptance_{id(self)}", default=None)
        self._runner = FixedJsonRunner()

    def handle(self, command, *, authenticated_actor_id, session=None, input_receipt=None):
        if not isinstance(command, Command):
            raise TypeError("Command required")
        if command.type not in COMMAND_AGGREGATES:
            return super().handle(command, authenticated_actor_id=authenticated_actor_id, input_receipt=input_receipt)
        return self._call(command, authenticated_actor_id,
                          {"channel": "agent", "session": session, "input_receipt": input_receipt})

    def _call(self, command, actor, context):
        if self.store.in_transaction:
            raise RuntimeError("acceptance entry requires gate before writer transaction")
        with self.gate.hold():
            token = self._acceptance_context.set(context)
            try:
                return CommandHandler.handle(self, command, authenticated_actor_id=actor)
            finally:
                self._acceptance_context.reset(token)

    def _state(self, project_id):
        return Projection.rebuild(self.store.read_events(project_id))

    def _context_data(self, project_id, context):
        data = {"channel": context["channel"]}
        if context.get("termination"):
            data["termination"] = context["termination"]
        if self.execution is not None:
            data["live"] = self.execution.validation_context(project_id, context.get("session"))
        data["runner"] = self._runner.descriptor
        return data

    def _evaluate(self, command, authenticated_actor_id):
        if command.type not in COMMAND_AGGREGATES:
            return super()._evaluate(command, authenticated_actor_id)
        context = self._acceptance_context.get() or {"channel": "agent"}
        try:
            if command.type in INTERNAL_COMMANDS and context["channel"] not in {"host", "recovery"}:
                raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
            state = self._state(command.project_id)
            at = observed_time(state, self.clock())
            data = self._context_data(command.project_id, context)
            if command.type in {"verification.request", "artifact.capture"} and context.get("input_receipt") is not None:
                if self.input_authority is None:
                    raise PolicyViolation("INPUT_CONTEXT_INVALID")
                data["input_proof"] = self.input_authority.verify(command, context["input_receipt"])
            effects = evaluate(command, state, at, data)
            envelope = {"acceptance_schema": SCHEMA, "command": command.to_dict(), "context": data, "observed_at_ms": at}
            return self._batch(command, state, [(kind, aggregate, identifier, record["revision"],
                                               {**envelope, "record": record})
                                              for kind, aggregate, identifier, record in effects])
        except PolicyViolation as exc:
            return self._rejected(command, exc.code), []
        except (ModelValidationError, KeyError, TypeError, ValueError, RecursionError, OverflowError):
            return self._rejected(command, "INVALID_PAYLOAD"), []

    def _internal(self, record, kind, payload, context):
        key = child_id("verification-host", record["project_id"], f"{kind}:{record['id']}:{record['revision']}")
        command = Command(key, record["project_id"], system_actor(record["project_id"]), kind, record["id"],
                          payload, record["revision"], key, record["action"]["request_command_id"])
        result = self._call(command, command.actor_id, context)
        if result.status != "accepted":
            raise PolicyViolation(result.error_code)
        return self._state(record["project_id"])[f"verification:{record['id']}"]

    def _record(self, record, outcome, observation, context):
        # Fetch the latest revision in case a callback/revocation changed it.
        current_record = self._state(record["project_id"])[f"verification:{record['id']}"]
        return self._internal(current_record, "verification.record",
                              {"execution_outcome": outcome, "observation": observation}, context)

    def dispatch(self, project_id, verification_id, *, session):
        if self.store.in_transaction:
            raise RuntimeError("Verification dispatch is forbidden inside a database transaction")
        with self.gate.hold():
            state = self._state(project_id)
            record = state.get(f"verification:{verification_id}")
            if record is None or record.get("schema") != SCHEMA:
                raise PolicyViolation("INVALID_TARGET")
            if record["status"] == "finished" or record["action"]["status"] != "pending":
                return copy.deepcopy(record)
            context = {"channel": "host", "session": session}
            error = authorization_error(record, state, observed_time(state, self.clock()), self._context_data(project_id, context))
            if error:
                return self._record(record, "not_executed", None, context)
            record = self._internal(record, "verification.dispatch",
                                    {"action_id": record["action"]["id"], "grant_id": record["grant"]["id"]}, context)
            # Dispatch has committed. Re-sample actual invocation time while
            # keeping the cross-process gate, never a SQLite transaction, held.
            state = self._state(project_id)
            error = authorization_error(record, state, observed_time(state, self.clock()), self._context_data(project_id, context))
            if error:
                return self._record(record, "not_executed", None, context)
            try:
                observation = self._runner.run(state[f"artifact:{record['artifact_id']}"]["content"],
                                               record["case_set"]["cases"])
                observation = _observation(observation, record["case_set"]["cases"])
                outcome = "completed"
            except Exception:
                observation, outcome = None, "runner_error"
            # Failure committing this transaction must leave IN_FLIGHT; do not
            # turn an uncommitted result or the exception into a second run.
            return self._record(record, outcome, observation, context)

    def recover_verifications(self, project_id):
        if self.store.in_transaction:
            raise RuntimeError("Verification recovery requires gate before writer transaction")
        with self.gate.hold():
            records = [row for key, row in self._state(project_id).items() if key.startswith("verification:")
                       and row.get("schema") == SCHEMA and row["action"]["status"] == "in_flight"]
            context = {"channel": "recovery", "termination": "exclusive_gate_fixed_memory_runner_exited"}
            return [self._record(record, "recovered", None, context) for record in records]
