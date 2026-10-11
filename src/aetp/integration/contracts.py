"""Fixed input bounds, not Provider or Runtime capabilities."""

MAX_IDENTIFIER_CHARS = 128
MAX_REF_CHARS = 255
OID_LENGTHS = {"sha1": 40, "sha256": 64}
MAX_VERSIONS = 64
MAX_REASON_CHARS = 2048

SCHEMA = "aetp-integration-contract-1"
MAX_TASKS = 64

# Success vocabulary is deliberately limited to requirement declaration.
COMMAND_AGGREGATES = {
    "project.integration.declare": "project",
    "git.merge": "task",
    "task.integration_ready": "task",
    "task.system_verify": "task",
}
DOMAIN_EVENTS = frozenset({
    "project.integration_declared",
    "task.integration_ready",
    "integration.completed",
    "integration.conflict",
    "task.system_verified",
})
COMMAND_TERMINALS = {
    "project.integration.declare": frozenset({"project.integration_declared"}),
    "git.merge": frozenset({"integration.completed", "integration.conflict"}),
    "task.integration_ready": frozenset({"task.integration_ready"}),
    "task.system_verify": frozenset({"task.system_verified"}),
}
EVENT_AGGREGATES = {
    "project.integration_declared": "project",
    "task.integration_ready": "task",
    "integration.completed": "task",
    "integration.conflict": "task",
    "task.system_verified": "task",
}
