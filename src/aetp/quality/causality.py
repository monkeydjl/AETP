"""Immutable quality receipt and compound-effect cursor."""

from aetp.collaboration.policy import digest_value
from aetp.domain.models import Command, ModelValidationError
from aetp.quality.contracts import COMMAND_AGGREGATES, DOMAIN_EVENTS, MAX_ARTIFACTS


class QualityCursor:
    def __init__(self, receipts=None, completed=frozenset(), continuation=None):
        self.receipts = {} if receipts is None else receipts
        self.completed = completed
        self.continuation = continuation

    def advance(self, event):
        if self.continuation is not None and (event.causation_id != self.continuation[0] or event.type not in DOMAIN_EVENTS):
            raise ModelValidationError("quality compound must continue without interleaving")
        if event.type == "command.received":
            if event.payload.get("command_type") not in COMMAND_AGGREGATES:
                return self
            if event.causation_id in self.receipts or set(event.payload) != {"command_type", "request_digest"}:
                raise ModelValidationError("duplicate or malformed quality receipt")
            digest = event.payload["request_digest"]
            if not isinstance(digest, str) or len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest):
                raise ModelValidationError("quality receipt requires a canonical Command digest")
            return QualityCursor({**self.receipts, event.causation_id: event}, self.completed)
        receipt = self.receipts.get(event.causation_id)
        if event.type not in DOMAIN_EVENTS and receipt is None:
            return self
        if receipt is None or event.causation_id in self.completed:
            raise ModelValidationError("quality effect has no pending receipt")
        if event.project_id != receipt.project_id or event.correlation_id != receipt.correlation_id:
            raise ModelValidationError("quality effect changed receipt scope")
        if event.type == "command.rejected":
            if (event.aggregate_type, event.aggregate_id, event.aggregate_revision) != (
                    receipt.aggregate_type, receipt.aggregate_id, receipt.aggregate_revision):
                raise ModelValidationError("quality rejection changed receipt address/revision")
            error = event.payload.get("error")
            if (set(event.payload) != {"error"} or not isinstance(error, dict)
                    or not isinstance(error.get("code"), str) or not error["code"].strip()):
                raise ModelValidationError("quality rejection requires a typed error")
            return QualityCursor(self.receipts, self.completed | {event.causation_id})
        if event.type not in DOMAIN_EVENTS:
            raise ModelValidationError("quality receipt has an unrelated effect")
        try:
            command = Command.from_dict(event.payload["command"])
            index, count = event.payload["effect_index"], event.payload["effect_count"]
            if (command.type != receipt.payload["command_type"] or command.digest() != receipt.payload["request_digest"]
                    or (COMMAND_AGGREGATES[command.type], command.target_id) != (receipt.aggregate_type, receipt.aggregate_id)):
                raise ModelValidationError("quality effect differs from receipt intent")
            if type(index) is not int or type(count) is not int or not 0 <= index < count <= MAX_ARTIFACTS + 1:
                raise ModelValidationError("invalid quality effect index/count")
            signature = digest_value({key: event.payload[key] for key in ("command", "context", "observed_at_ms", "effect_count")})
            if self.continuation is None:
                if index != 0:
                    raise ModelValidationError("quality compound is missing its first effect")
            elif self.continuation != (event.causation_id, index, count, signature):
                raise ModelValidationError("quality compound changed context or effect order")
        except (KeyError, TypeError, ValueError) as exc:
            raise ModelValidationError("invalid quality causal proof") from exc
        if index + 1 == count:
            return QualityCursor(self.receipts, self.completed | {event.causation_id})
        return QualityCursor(self.receipts, self.completed, (event.causation_id, index + 1, count, signature))
