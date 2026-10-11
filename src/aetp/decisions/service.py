"""Load source material only at the trusted proposal Command boundary."""

from aetp.collaboration.policy import PolicyViolation
from aetp.decisions.records import assemble, freeze_source, source_reference
from aetp.meetings.policy import payload


def propose(service, command, state):
    payload(command.payload, {"title", "choice", "alternatives", "reasoning", "risk_level", "source", "supersedes"})
    service._new(command, state, "decision")
    snapshot = None
    if command.payload.get("source") is not None:
        source = source_reference(command.payload["source"], state, command.actor_id)
        rows, meta = service.process.read(source)
        if meta["compacted"]:
            raise PolicyViolation("PROCESS_UNRECONCILED")
        snapshot = freeze_source(source, rows, state)
    record = assemble(command, state, snapshot)
    return service._record_effect(command, state, "decision.proposed", record)
