"""Immutable receipt/terminal cursor for declarations and rejection-only requests."""
from dataclasses import dataclass, field
from types import MappingProxyType
from aetp.domain.models import ModelValidationError
from aetp.integration.contracts import COMMAND_AGGREGATES, DOMAIN_EVENTS, COMMAND_TERMINALS


def _rejection(event, receipt):
    if ((event.aggregate_type, event.aggregate_id, event.aggregate_revision)
            != (receipt.aggregate_type, receipt.aggregate_id, receipt.aggregate_revision)):
        raise ModelValidationError("Integration rejection changed receipt address/revision")
    error = event.payload.get("error")
    if (set(event.payload) != {"error"} or not isinstance(error, dict)
            or set(error) != {"code", "message", "retryable", "severity", "context"}
            or not isinstance(error["code"], str) or not error["code"].strip()
            or error["message"] != f"Command rejected: {error['code']}"
            or error["retryable"] is not False or error["severity"] != "medium"):
        raise ModelValidationError("invalid Integration typed rejection")
    context = error["context"]
    if (not isinstance(context, dict) or set(context) != {"command_id", "target_id", "expected_revision", "current_revision"}
            or context["command_id"] != event.causation_id):
        raise ModelValidationError("invalid Integration rejection context")
    target = context["target_id"]
    expected = context["expected_revision"]
    current = context["current_revision"]
    address = (COMMAND_AGGREGATES[receipt.payload["command_type"]], target) if target else ("project", event.project_id)
    if ((target is not None and (not isinstance(target, str) or not target.strip() or target != target.strip()))
            or address != (receipt.aggregate_type, receipt.aggregate_id)
            or (expected is not None and (type(expected) is not int or expected < 0))
            or (current is None and receipt.aggregate_revision != 0)
            or (current is not None and (type(current) is not int or current != receipt.aggregate_revision))):
        raise ModelValidationError("Integration rejection context differs from receipt")


@dataclass(frozen=True, slots=True)
class IntegrationCursor:
    receipts: object = field(default_factory=dict)
    completed: frozenset = frozenset()

    def __post_init__(self):
        object.__setattr__(self, "receipts", MappingProxyType(dict(self.receipts)))
        object.__setattr__(self, "completed", frozenset(self.completed))

    def advance(self, event):
        if event.type == "command.received":
            kind = event.payload.get("command_type")
            if kind not in COMMAND_AGGREGATES:
                return self
            if event.causation_id in self.receipts or set(event.payload) != {"command_type", "request_digest"}:
                raise ModelValidationError("duplicate or malformed Integration receipt")
            digest = event.payload["request_digest"]
            if (not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
                    or event.aggregate_type not in ({"project"} if kind == "project.integration.declare" else {"project", "task"})):
                raise ModelValidationError("Integration receipt requires canonical digest/address")
            return IntegrationCursor({**self.receipts, event.causation_id: event}, self.completed)
        receipt = self.receipts.get(event.causation_id)
        if receipt is None and event.type not in DOMAIN_EVENTS:
            return self
        if receipt is None or event.causation_id in self.completed:
            raise ModelValidationError("Integration effect has no pending receipt")
        if event.project_id != receipt.project_id or event.correlation_id != receipt.correlation_id:
            raise ModelValidationError("Integration effect changed receipt scope")
        if event.type == "command.rejected":
            _rejection(event, receipt)
        else:
            allowed_events = COMMAND_TERMINALS.get(receipt.payload["command_type"], frozenset())
            if event.type not in allowed_events:
                raise ModelValidationError("Integration request cannot have this success effect")
            from aetp.integration.projection import effect_command
            command = effect_command(event)
            if (command.digest() != receipt.payload["request_digest"]
                    or (COMMAND_AGGREGATES[command.type], command.target_id) != (receipt.aggregate_type, receipt.aggregate_id)
                    or command.expected_revision != receipt.aggregate_revision
                    or event.aggregate_revision != receipt.aggregate_revision + 1):
                raise ModelValidationError("Integration effect differs from receipt intent/revision")
        return IntegrationCursor(self.receipts, self.completed | {event.causation_id})
