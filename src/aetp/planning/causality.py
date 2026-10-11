"""A pure receipt cursor for the single-effect planning Command contract."""

from aetp.domain.models import Command, ModelValidationError
from aetp.planning.contracts import COMMAND_AGGREGATES, DOMAIN_EVENTS


class PlanningCursor:
    def __init__(self, receipts=None, completed=frozenset()):
        self.receipts = {} if receipts is None else receipts
        self.completed = completed

    def advance(self, event):
        if event.type == "command.received":
            if event.payload.get("command_type") not in COMMAND_AGGREGATES:
                return self
            if event.causation_id in self.receipts:
                raise ModelValidationError("planning Command has multiple receipt Events")
            if set(event.payload) != {"command_type", "request_digest"}:
                raise ModelValidationError("planning receipt has unexpected fields")
            return PlanningCursor({**self.receipts, event.causation_id: event}, self.completed)
        receipt = self.receipts.get(event.causation_id)
        if event.type not in DOMAIN_EVENTS and receipt is None:
            return self
        if receipt is None or event.causation_id in self.completed:
            raise ModelValidationError("planning effect has no pending matching receipt")
        if (event.project_id, event.aggregate_type, event.aggregate_id, event.correlation_id) != (
                receipt.project_id, receipt.aggregate_type, receipt.aggregate_id, receipt.correlation_id):
            raise ModelValidationError("planning terminal differs from its receipt address")
        if event.type == "command.rejected":
            if event.aggregate_revision != receipt.aggregate_revision:
                raise ModelValidationError("planning rejection cannot change aggregate revision")
        elif event.type in DOMAIN_EVENTS:
            try:
                command = Command.from_dict(event.payload["command"])
                if command.type != receipt.payload["command_type"] or command.digest() != receipt.payload["request_digest"]:
                    raise ModelValidationError("planning effect differs from receipt request digest")
            except (KeyError, TypeError, ValueError) as exc:
                raise ModelValidationError("invalid planning receipt/effect proof") from exc
        else:
            raise ModelValidationError("planning Command has an unrelated terminal Event")
        return PlanningCursor(self.receipts, self.completed | {event.causation_id})
