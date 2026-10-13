"""Trusted declaration ingress and Integration Gate execution."""
import copy
from contextvars import ContextVar
from aetp.collaboration.policy import PolicyViolation
from aetp.core.commands import CommandHandler
from aetp.domain.models import Command, ModelValidationError
from aetp.integration.contracts import COMMAND_AGGREGATES, SCHEMA
from aetp.integration.gate import (
    dispatch_merge,
    validate_integration_ready,
    validate_system_verify,
)
from aetp.integration.records import evaluate
from aetp.quality.service import TaskQualityService
from aetp.runtime.policy import observed_time


class IntegrationContractService(TaskQualityService):
    def __init__(self, store, *, git_provider=None, **kwargs):
        super().__init__(store, **kwargs)
        # Trusted-only: the git provider's repo_dir lives inside the provider
        # object and never comes from an Agent Command.
        self._git_provider = git_provider
        self._integration_context = ContextVar(f"integration_{id(self)}", default=None)

    def handle(self, command, *, authenticated_actor_id, session=None, input_receipt=None):
        if not isinstance(command, Command):
            raise TypeError("Command required")
        if command.type not in COMMAND_AGGREGATES:
            return super().handle(command, authenticated_actor_id=authenticated_actor_id,
                                  session=session, input_receipt=input_receipt)
        if self.store.in_transaction:
            raise RuntimeError("Integration entry requires the resource gate before the writer transaction")
        with self.gate.hold():
            token = self._integration_context.set({"input_receipt": input_receipt})
            try:
                return CommandHandler.handle(self, command, authenticated_actor_id=authenticated_actor_id)
            finally:
                self._integration_context.reset(token)

    def _evaluate(self, command, authenticated_actor_id):
        if command.type not in COMMAND_AGGREGATES:
            return super()._evaluate(command, authenticated_actor_id)
        try:
            supplied = self._integration_context.get()
            if supplied is None:
                raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
            state = self._state(command.project_id)
            at = observed_time(state, self.clock())
            if self.input_authority is None or supplied["input_receipt"] is None:
                raise PolicyViolation("INPUT_CONTEXT_INVALID")
            context = {"channel": "agent", "input_proof": self.input_authority.verify(command, supplied["input_receipt"])}

            if command.type == "project.integration.declare":
                effects = evaluate(command, state, at, context)
                envelope = {"integration_schema": SCHEMA, "command": command.to_dict(), "context": context,
                            "observed_at_ms": at, "effect_index": 0, "effect_count": 1}
                return self._batch(command, state, [(kind, aggregate, identifier, record["revision"],
                    {**envelope, "record": record}) for kind, aggregate, identifier, record in effects])

            # Task Gate commands: task.integration_ready, git.merge, task.system_verify
            task = state.get(f"task:{command.target_id}")
            if task is None:
                raise PolicyViolation("INVALID_TARGET")
            if command.expected_revision != task["revision"]:
                raise PolicyViolation("EXPECTED_REVISION_MISMATCH")

            if command.type == "task.integration_ready":
                contract = state.get(f"project:{command.project_id}", {}).get("integration_contract", {})
                validate_integration_ready(task, contract)
                record = copy.deepcopy(task)
                record["status"] = "ready_for_integration"
                record["revision"] += 1
                record["updated_at_ms"] = at
                kind = "task.integration_ready"

            elif command.type == "git.merge":
                outcome = dispatch_merge(self._git_provider, task, command.payload)
                record = copy.deepcopy(task)
                record["revision"] += 1
                record["updated_at_ms"] = at
                if outcome["conflict"]:
                    record["integration_conflict"] = True
                    record["conflict_paths"] = copy.deepcopy(outcome.get("conflict_paths", []))
                    kind = "integration.conflict"
                else:
                    record["status"] = "integrated"
                    record["result_commit"] = outcome.get("result_commit")
                    kind = "integration.completed"

            elif command.type == "task.system_verify":
                validate_system_verify(task, command.payload)
                record = copy.deepcopy(task)
                record["status"] = "system_verified"
                record["system_verification"] = {
                    "outcome": command.payload.get("outcome"),
                    "result_commit": command.payload.get("result_commit")
                }
                record["revision"] += 1
                record["updated_at_ms"] = at
                kind = "task.system_verified"
            else:
                raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")

            envelope = {"integration_schema": SCHEMA, "command": command.to_dict(), "context": context,
                        "observed_at_ms": at, "effect_index": 0, "effect_count": 1}
            return self._batch(command, state, [(kind, "task", command.target_id, record["revision"],
                {**envelope, "record": record})])

        except PolicyViolation as exc:
            return self._rejected(command, exc.code), []
        except (ModelValidationError, KeyError, TypeError, ValueError, RecursionError, OverflowError):
            return self._rejected(command, "INVALID_PAYLOAD"), []
