"""Immutable cursor for receipts, intermediate report facts and final outcomes."""

from aetp.acceptance.contracts import COMMAND_AGGREGATES, DOMAIN_EVENTS, report_id
from aetp.collaboration.policy import canonical_json
from aetp.domain.models import Command, ModelValidationError


class AcceptanceCursor:
    def __init__(self, receipts=None, completed=frozenset(), report=None):
        self.receipts = {} if receipts is None else receipts
        self.completed = completed
        self.report = report

    def advance(self, event):
        if self.report is not None and (event.type != "verification.finished" or event.causation_id != self.report.causation_id):
            raise ModelValidationError("Verification report must be followed immediately by its terminal fact")
        if event.type == "command.received":
            if event.payload.get("command_type") not in COMMAND_AGGREGATES:
                return self
            if event.causation_id in self.receipts or set(event.payload) != {"command_type", "request_digest"}:
                raise ModelValidationError("Acceptance Command has duplicate or invalid receipt")
            return AcceptanceCursor({**self.receipts, event.causation_id: event}, self.completed)
        receipt = self.receipts.get(event.causation_id)
        if event.type not in DOMAIN_EVENTS and receipt is None:
            return self
        if receipt is None or event.causation_id in self.completed:
            raise ModelValidationError("Acceptance effect has no pending matching receipt")
        is_report = event.type == "artifact.verification_reported"
        address = ("artifact", report_id(event.project_id, receipt.aggregate_id)) if is_report else (
            receipt.aggregate_type, receipt.aggregate_id)
        if (event.project_id != receipt.project_id or event.correlation_id != receipt.correlation_id
                or (event.aggregate_type, event.aggregate_id) != address):
            raise ModelValidationError("Acceptance fact changed receipt identity/address")
        if event.type == "command.rejected":
            if event.aggregate_revision != receipt.aggregate_revision:
                raise ModelValidationError("Acceptance rejection changed revision")
        elif event.type in DOMAIN_EVENTS:
            try:
                command = Command.from_dict(event.payload["command"])
                if command.type != receipt.payload["command_type"] or command.digest() != receipt.payload["request_digest"]:
                    raise ModelValidationError("Acceptance effect differs from receipt request")
                if (COMMAND_AGGREGATES[command.type], command.target_id) != (receipt.aggregate_type, receipt.aggregate_id):
                    raise ModelValidationError("Acceptance receipt differs from Command address")
            except (KeyError, TypeError, ValueError) as exc:
                raise ModelValidationError("invalid Acceptance causal proof") from exc
            if is_report:
                if command.type != "verification.record":
                    raise ModelValidationError("report requires the host result Command")
                return AcceptanceCursor(self.receipts, self.completed, event)
            if event.type == "verification.finished":
                if self.report is None or any(canonical_json(event.payload[key]) != canonical_json(self.report.payload[key])
                        for key in ("command", "context", "observed_at_ms")):
                    raise ModelValidationError("Verification terminal has no matching report context")
        else:
            raise ModelValidationError("Acceptance Command has an unrelated terminal fact")
        return AcceptanceCursor(self.receipts, self.completed | {event.causation_id})
