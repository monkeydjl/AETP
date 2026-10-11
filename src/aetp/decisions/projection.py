"""Pure proposal validation; no process-storage or Runtime dependency."""

from aetp.collaboration.policy import canonical_json
from aetp.decisions.records import assemble
from aetp.domain.models import ModelValidationError


def reduce_proposal(command, record, previous, state):
    if previous is not None or command.type != "decision.propose":
        raise ModelValidationError("Decision proposals are immutable")
    expected = assemble(command, state, record.get("source"))
    if canonical_json(expected) != canonical_json(record):
        raise ModelValidationError("Decision attribution, source or conclusion was changed")
    return expected
