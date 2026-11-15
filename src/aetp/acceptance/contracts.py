"""Fixed, versioned document checker limits."""

RUNNER_ID = "aetp.fixed-json-document/v1"
MAX_CASES = 32
MAX_CASE_BYTES = 16384
MAX_DOCUMENT_BYTES = 65536
MAX_DEPTH = 32
MAX_PATH = 16
MAX_NUMBER_CHARS = 128

SCHEMA = "aetp-trusted-document-verification-1"
COMMAND_TERMINALS = {
    "project.quality.configure": frozenset({"project.quality_configured"}),
    "artifact.capture": frozenset({"artifact.captured"}),
    "artifact.observe": frozenset({"artifact.observed"}),
    "verification.request": frozenset({"verification.requested"}),
    "verification.revoke": frozenset({"verification.revoked"}),
    "verification.dispatch": frozenset({"verification.dispatched"}),
    "verification.record": frozenset({"verification.finished"}),
}
COMMAND_AGGREGATES = {kind: kind.split(".")[0] for kind in COMMAND_TERMINALS}
DOMAIN_EVENTS = frozenset(event for values in COMMAND_TERMINALS.values() for event in values) | {"artifact.verification_reported"}
INTERNAL_COMMANDS = frozenset({"verification.dispatch", "verification.record"})


def system_actor(project_id):
    from aetp.governance.contracts import system_actor as governance_actor
    return governance_actor(project_id)


def report_id(project_id, verification_id):
    from aetp.runtime.contracts import child_id
    return child_id("verification-report", project_id, verification_id)


def reserved_report_id(identifier):
    prefix = "verification-report-"
    return (isinstance(identifier, str) and identifier.startswith(prefix) and len(identifier) == len(prefix) + 64
            and all(character in "0123456789abcdef" for character in identifier[len(prefix):]))
