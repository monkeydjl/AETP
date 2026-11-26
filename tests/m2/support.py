"""Real SQLite fixtures; the meter explicitly models process admission only."""

import unittest

from aetp.core.runtime import RuntimeRecovery
from aetp.domain.models import Command
from tests.m0.support import open_command_fixture

try:
    from aetp.meetings.metering import MeteringAuthority
    from aetp.meetings.records import Contribution
    from aetp.meetings.service import MeetingService
except ModuleNotFoundError as exc:
    if not exc.name.startswith("aetp.meetings"):
        raise
    MeetingService = Contribution = MeteringAuthority = None


class MeetingCase(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(MeetingService, "M2 structured collaboration is not implemented")
        self.fixture = open_command_fixture(self)
        self.store = self.fixture.store
        self.clock_value = 1000
        self.meter = MeteringAuthority("fixture-admission-meter")
        self.service = MeetingService(self.store, meter=self.meter, clock=lambda: self.clock_value)
        self.counter = 0

    def command(self, kind, target, payload=None, *, actor="a-1", revision=None, key=None):
        self.counter += 1
        key = key or f"m2-command-{self.counter}"
        if revision is None:
            row = self.state().get(f"{kind.split('.')[0]}:{target}")
            revision = row["revision"] if row else 0
        return Command(key, "p-1", actor, kind, target, payload or {}, revision, key, "m2-test")

    def accept(self, command):
        result = self.service.handle(command, authenticated_actor_id=command.actor_id)
        self.assertEqual(result.status, "accepted", result.to_dict())
        return result

    def reject(self, command, code):
        result = self.service.handle(command, authenticated_actor_id=command.actor_id)
        self.assertEqual((result.status, result.error_code), ("rejected", code))
        return result

    def state(self):
        return self.store.read_projection("p-1")

    def commands(self):
        recovery = RuntimeRecovery.open(self.fixture.db_path)
        try:
            return recovery._read_commands("p-1")
        finally:
            recovery.close()

    def open_discussion(self, identifier="d", **policy):
        self.accept(self.command("discussion.open", identifier, {
            "topic": "Choose storage", "participants": ["a-1", "a-2"], "moderator_id": "a-1", "policy": policy}))
        return identifier

    def begin_meeting(self, identifier="m", **policy):
        self.accept(self.command("meeting.create", identifier, {
            "topic": "Choose storage", "objective": "Compare two alternatives",
            "participants": ["a-1", "a-2"], "moderator_id": "a-1", "policy": policy}))
        self.accept(self.command("meeting.open", identifier))
        self.accept(self.command("meeting.advance", identifier))
        return identifier

    def contribution(self, target, *, actor="a-1", identifier=None, content="An opinion", category="opinion",
                     position=None, references=(), evidence=(), context=""):
        self.counter += 1
        kind = "meeting" if f"meeting:{target}" in self.state() else "discussion"
        return Contribution(identifier or f"post-{self.counter}", "p-1", kind, target, actor,
                            category, content, position, tuple(references), tuple(evidence), context)

    def post(self, target, *, tokens=1, call_id=None, **kwargs):
        entry = self.contribution(target, **kwargs)
        receipt = self.meter.issue(entry, call_id=call_id or f"call-{entry.id}", tokens=tokens)
        return self.service.post(entry, authenticated_actor_id=entry.author_id, receipt=receipt)

    def transcript(self, target, actor="a-1"):
        kind = "meeting" if f"meeting:{target}" in self.state() else "discussion"
        return self.service.transcript("p-1", kind, target, authenticated_actor_id=actor)

    def usage(self, target):
        kind = "meeting" if f"meeting:{target}" in self.state() else "discussion"
        return self.service.usage("p-1", kind, target, authenticated_actor_id="a-1")

    def event_text(self):
        return "\n".join(event.to_json() for event in self.store.read_events("p-1"))

    def ready_debate(self, **policy):
        self.begin_meeting(**policy)
        self.post("m", actor="a-1", category="analysis", content="independent A")
        self.post("m", actor="a-2", category="analysis", content="independent B")
        self.accept(self.command("meeting.advance", "m"))

    def synthesize(self, target, actor="a-1"):
        kind = "meeting" if f"meeting:{target}" in self.state() else "discussion"
        return self.accept(self.command(f"{kind}.synthesize", target, {"reason": "moderator_decision"}, actor=actor))

    def propose(self, target=None, *, identifier="decision-1", choice="A", actor="a-1", **extra):
        payload = {"title": "Storage choice", "choice": choice, "alternatives": ["A", "B"],
                   "reasoning": "Tradeoffs remain explicit", "risk_level": "low"}
        if target:
            kind = "meeting" if f"meeting:{target}" in self.state() else "discussion"
            payload["source"] = {"kind": kind, "id": target, "revision": self.state()[f"{kind}:{target}"]["revision"]}
        payload.update(extra)
        self.accept(self.command("decision.propose", identifier, payload, actor=actor))
        return self.state()[f"decision:{identifier}"]


def admission_worker(path, entry_data, call_id, gate, queue):
    """Independent process; no in-memory lock or receipt set shared with parent."""
    from aetp.meetings.metering import MeteringAuthority
    from aetp.meetings.records import Contribution
    from aetp.meetings.service import MeetingService
    from aetp.storage.sqlite_store import SQLiteStore
    try:
        with SQLiteStore.open(path) as store:
            meter = MeteringAuthority("fixture-admission-meter")
            service = MeetingService(store, meter=meter, clock=lambda: 1000)
            entry = Contribution.from_dict(entry_data)
            receipt = meter.issue(entry, call_id=call_id, tokens=5)
            gate.wait(15)
            service.post(entry, authenticated_actor_id=entry.author_id, receipt=receipt)
            queue.put({"status": "accepted"})
    except Exception as exc:
        queue.put({"status": "rejected", "code": getattr(exc, "code", type(exc).__name__)})
