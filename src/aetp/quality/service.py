"""Trusted quality entry; requester capabilities are never filled from the target."""

from contextvars import ContextVar

from aetp.acceptance.service import AcceptanceService
from aetp.collaboration.policy import PolicyViolation
from aetp.core.commands import CommandHandler
from aetp.domain.models import Command, ModelValidationError
from aetp.quality.contracts import COMMAND_AGGREGATES, SCHEMA
from aetp.quality.records import evaluate
from aetp.runtime.policy import observed_time


class TaskQualityService(AcceptanceService):
    def __init__(self, store, **kwargs):
        super().__init__(store, **kwargs)
        self._quality_context = ContextVar(f"task_quality_{id(self)}", default=None)

    def handle(self, command, *, authenticated_actor_id, session=None, input_receipt=None):
        if not isinstance(command, Command):
            raise TypeError("Command required")
        if command.type not in COMMAND_AGGREGATES:
            return super().handle(command, authenticated_actor_id=authenticated_actor_id,
                                  session=session, input_receipt=input_receipt)
        if self.store.in_transaction:
            raise RuntimeError("quality entry requires the resource gate before the writer transaction")
        with self.gate.hold():
            token = self._quality_context.set({"session": session, "input_receipt": input_receipt})
            try:
                return CommandHandler.handle(self, command, authenticated_actor_id=authenticated_actor_id)
            finally:
                self._quality_context.reset(token)

    def _quality_observations(self, command, state, supplied):
        data = {"channel": "agent", "runner": self._runner.descriptor}
        if self.execution is not None:
            data["requester_live"] = self.execution.validation_context(command.project_id, supplied.get("session"))
            task = state.get(f"task:{command.target_id}")
            if command.type.startswith("review."):
                review = state.get(f"review:{command.target_id}", {})
                task = state.get(f"task:{review.get('task_id')}")
            if task:
                binding = task.get("bindings", {}).get(task.get("current_binding_id"), {})
                descriptor = binding.get("session")
                # Lookup observes the same Runtime's registry; it never
                # creates a capability from a persisted Session descriptor.
                session = self.execution.runtime.lookup(descriptor["id"]) if descriptor else None
                data["target_live"] = self.execution.validation_context(command.project_id, session)
        if supplied.get("input_receipt") is not None:
            if self.input_authority is None:
                raise PolicyViolation("INPUT_CONTEXT_INVALID")
            data["input_proof"] = self.input_authority.verify(command, supplied["input_receipt"])
        return data

    def _evaluate(self, command, authenticated_actor_id):
        if command.type not in COMMAND_AGGREGATES:
            return super()._evaluate(command, authenticated_actor_id)
        try:
            supplied = self._quality_context.get()
            if supplied is None:
                raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
            state = self._state(command.project_id)
            at = observed_time(state, self.clock())
            context = self._quality_observations(command, state, supplied)
            effects = evaluate(command, state, at, context)
            envelope = {"quality_schema": SCHEMA, "command": command.to_dict(), "context": context,
                        "observed_at_ms": at, "effect_count": len(effects)}
            return self._batch(command, state, [(kind, aggregate, identifier, record["revision"],
                {**envelope, "effect_index": index, "record": record})
                for index, (kind, aggregate, identifier, record) in enumerate(effects)])
        except PolicyViolation as exc:
            return self._rejected(command, exc.code), []
        except (ModelValidationError, KeyError, TypeError, ValueError, RecursionError, OverflowError):
            return self._rejected(command, "INVALID_PAYLOAD"), []
