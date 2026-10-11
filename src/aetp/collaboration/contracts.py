"""The implemented M1 vocabulary, shared without startup registrations."""

COMMAND_AGGREGATES = {
    "artifact.submit": "artifact",
    "review.request": "review",
    "review.submit": "review",
    "verification.run": "verification",
    "verification.submit": "verification",
    "task.verify": "task",
    "task.complete": "task",
}
COMMAND_TERMINALS = {
    "artifact.submit": frozenset({"artifact.created"}),
    "review.request": frozenset({"review.requested"}),
    "review.submit": frozenset({"review.approved", "review.rejected"}),
    "verification.run": frozenset({"verification.completed"}),
    "verification.submit": frozenset(),
    "task.verify": frozenset(),
    "task.complete": frozenset(),
}
DOMAIN_EVENTS = frozenset().union(*COMMAND_TERMINALS.values())
AGGREGATES = frozenset(COMMAND_AGGREGATES.values())
