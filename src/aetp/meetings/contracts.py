"""Static M2 vocabulary; importing it does not open process storage."""

POLICY_VERSION = "m2-local-discussion-v1"
COMMAND_AGGREGATES = {
    **{f"discussion.{action}": "discussion" for action in ("open", "synthesize", "tick", "close")},
    **{f"meeting.{action}": "meeting" for action in ("create", "open", "advance", "synthesize", "tick", "close")},
    **{f"decision.{action}": "decision" for action in ("propose", "approve", "activate")},
}
COMMAND_TERMINALS = {
    "discussion.open": {"discussion.started"},
    "discussion.synthesize": {"discussion.synthesizing"}, "discussion.tick": {"discussion.synthesizing"},
    "discussion.close": {"discussion.closed"},
    "meeting.create": {"meeting.created"}, "meeting.open": {"meeting.started"},
    "meeting.advance": {"meeting.advanced", "meeting.synthesizing"},
    "meeting.synthesize": {"meeting.synthesizing"}, "meeting.tick": {"meeting.synthesizing"},
    "meeting.close": {"meeting.completed"},
    "decision.propose": {"decision.proposed"}, "decision.approve": set(), "decision.activate": set(),
}
DOMAIN_EVENTS = frozenset().union(*COMMAND_TERMINALS.values())
AGGREGATES = frozenset(COMMAND_AGGREGATES.values())
