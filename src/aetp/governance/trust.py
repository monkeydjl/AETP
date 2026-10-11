"""Trusted ingress capabilities. Neither source IDs nor copied JSON prove origin."""

import copy
from dataclasses import asdict, dataclass
import threading
import uuid

from aetp.collaboration.policy import PolicyViolation, digest_value, text
from aetp.domain.models import Command
from aetp.governance.policy import fields

EXPOSURES = frozenset({"trusted", "internal", "untrusted", "unknown"})


@dataclass(frozen=True, slots=True)
class InputReceipt:
    id: str
    source_id: str
    command_digest: str
    actor_id: str
    exposure: str
    sources: tuple


class InputAuthority:
    """Owned only by an input facility that can attest the entire new context.

    This is an ingress capability, not a provenance detector. A host assertion
    must be true; Agents only get the data API and cannot issue capabilities.
    Durable source facts survive restart, but an old capability is never minted
    from an Event or from a caller's source_id/role/untrusted_input claim.
    """

    def __init__(self, source_id):
        self.source_id = text(source_id, identifier=True)
        self._issued = {}
        self._lock = threading.RLock()

    def issue(self, command, *, exposure, sources=()):
        if not isinstance(command, Command):
            raise TypeError("Command required")
        if exposure not in EXPOSURES or not isinstance(sources, (tuple, list)):
            raise ValueError("invalid input exposure")
        normalized = []
        for source in sources:
            fields(source, {"source_id", "exposure"}, {"source_id", "exposure"})
            text(source["source_id"], identifier=True)
            if source["exposure"] not in EXPOSURES:
                raise ValueError("invalid source exposure")
            normalized.append((source["source_id"], source["exposure"]))
        receipt = InputReceipt(uuid.uuid4().hex, self.source_id, command.digest(), command.actor_id, exposure, tuple(normalized))
        with self._lock:
            self._issued[receipt.id] = receipt
        return receipt

    def verify(self, command, receipt):
        with self._lock:
            if (not isinstance(receipt, InputReceipt) or self._issued.get(receipt.id) is not receipt
                    or receipt.source_id != self.source_id or receipt.command_digest != command.digest()
                    or receipt.actor_id != command.actor_id):
                raise PolicyViolation("INPUT_CONTEXT_INVALID")
            return {"receipt_id": receipt.id, "source_id": receipt.source_id, "command_digest": receipt.command_digest,
                    "actor_id": receipt.actor_id, "exposure": receipt.exposure,
                    "sources": [{"source_id": source, "exposure": exposure} for source, exposure in receipt.sources]}


def source_record(command, context, configured_source):
    proof = context.get("input_proof")
    if proof is None:
        proof = {"receipt_id": None, "source_id": None, "command_digest": command.digest(),
                 "actor_id": command.actor_id, "exposure": "unknown", "sources": []}
    fields(proof, {"receipt_id", "source_id", "command_digest", "actor_id", "exposure", "sources"},
           {"receipt_id", "source_id", "command_digest", "actor_id", "exposure", "sources"})
    if (proof["command_digest"] != command.digest() or proof["actor_id"] != command.actor_id
            or proof["exposure"] not in EXPOSURES or not isinstance(proof["sources"], list)):
        raise PolicyViolation("INPUT_CONTEXT_INVALID")
    if proof["source_id"] is None:
        if proof["receipt_id"] is not None or proof["exposure"] != "unknown" or proof["sources"]:
            raise PolicyViolation("INPUT_CONTEXT_INVALID")
    elif configured_source is None or proof["source_id"] != configured_source:
        raise PolicyViolation("INPUT_CONTEXT_INVALID")
    else:
        text(proof["receipt_id"], identifier=True)
    for source in proof["sources"]:
        fields(source, {"source_id", "exposure"}, {"source_id", "exposure"})
        text(source["source_id"], identifier=True)
        if source["exposure"] not in EXPOSURES:
            raise PolicyViolation("INPUT_CONTEXT_INVALID")
    return {**copy.deepcopy(proof), "untrusted_input": proof["exposure"] in {"unknown", "untrusted"}
            or any(source["exposure"] in {"unknown", "untrusted"} for source in proof["sources"])}


def inherit_document_sources(source, normalized, state):
    """A new ingress attestation cannot erase the provenance of referenced facts."""
    arguments = normalized["arguments"]
    inherited = []

    def retain(kind, identifier, provenance, digest):
        provenance = copy.deepcopy(provenance) if isinstance(provenance, dict) else {
            "exposure": "unknown", "untrusted_input": True}
        untrusted = provenance.get("untrusted_input") is not False
        inherited.append({"type": kind, "id": identifier, "content_digest": digest,
                          "source_digest": digest_value(provenance), "source": provenance,
                          "untrusted_input": untrusted})

    if "source_action_id" in arguments:
        action = state[f"action:{arguments['source_action_id']}"]
        retain("action", action["id"], action.get("authorization", {}).get("source"),
               action["result"]["envelope_digest"])
    if "checkpoint_id" in arguments:
        checkpoint = state[f"checkpoint:{arguments['checkpoint_id']}"]
        retain("checkpoint", checkpoint["id"], checkpoint["snapshot"].get("context_snapshot", {}).get("source"),
               checkpoint["snapshot_digest"])
    if inherited:
        source["derived_sources"] = inherited
        source["untrusted_input"] |= any(entry["untrusted_input"] for entry in inherited)
    return source
