"""Real SQLite and Command fixtures for M1; no alternate implementation."""

import unittest

from aetp.domain.models import Command, ModelValidationError
from tests.m0.support import open_command_fixture

try:
    from aetp.collaboration.service import CollaborationService
except ModuleNotFoundError as exc:
    if exc.name != "aetp.collaboration.service":
        raise
    CollaborationService = None


class CollaborationCase(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(CollaborationService, "M1 candidate evidence service is not implemented")
        self.fixture = open_command_fixture(self)
        self.store = self.fixture.store
        self.service = CollaborationService(self.store)
        self.counter = 0
        self.accept(self.command("task.create", "t-1", {
            "title": "Write a guide", "acceptance_criteria": ["Overview", "Failure case"]}))
        self.accept(self.command("task.claim", "t-1", {}))

    def command(self, kind, target, payload, *, actor="a-1", revision=0, key=None, project="p-1"):
        self.counter += 1
        key = key or f"m1-{self.counter:04d}"
        try:
            return Command(key, project, actor, kind, target, payload, revision, key, "m1-conversation")
        except ModelValidationError as exc:
            self.fail(f"required M1 Command is not implemented: {kind}: {exc}")

    def accept(self, command, actor=None):
        result = self.service.handle(command, authenticated_actor_id=actor or command.actor_id)
        self.assertEqual(result.status, "accepted", result.to_dict())
        return result

    def reject(self, command, code, actor=None):
        result = self.service.handle(command, authenticated_actor_id=actor or command.actor_id)
        self.assertEqual(result.status, "rejected", result.to_dict())
        self.assertEqual(result.error_code, code)
        return result

    def state(self):
        return self.store.read_projection("p-1")

    def artifact(self, identifier="art-1", *, actor="a-1", content="Overview\nFailure case\n", **extra):
        payload = {"task_id": "t-1", "type": "document", "content": content}
        payload.update(extra)
        result = self.accept(self.command("artifact.submit", identifier, payload, actor=actor))
        return self.state()[f"artifact:{identifier}"], result

    def request_review(self, identifier="rev-1", *, artifact_id="art-1", reviewer="a-2", actor="a-2"):
        artifact = self.state()[f"artifact:{artifact_id}"]
        return self.accept(self.command("review.request", identifier, {
            "artifact_id": artifact_id, "artifact_digest": artifact["content_digest"],
            "reviewer_id": reviewer}, actor=actor))

    def submit_review_command(self, identifier="rev-1", *, actor="a-2", status="approved", **extra):
        review = self.state()[f"review:{identifier}"]
        payload = {"status": status, "feedback": "Inspected the criteria and the fixed document.",
                   "artifact_digest": review["artifact_digest"]}
        payload.update(extra)
        return self.command("review.submit", identifier, payload, actor=actor)


def review_worker(db_path, command_data, gate, output):
    """A real competing process, not a same-process lock test."""
    from aetp.collaboration.service import CollaborationService
    from aetp.storage.sqlite_store import SQLiteStore
    try:
        with SQLiteStore.open(db_path) as store:
            service = CollaborationService(store)
            command = Command.from_dict(command_data)
            gate.wait(timeout=15)
            result = service.handle(command, authenticated_actor_id=command.actor_id)
            output.put({"result": result.to_dict()})
    except BaseException as exc:
        output.put({"error": type(exc).__name__, "detail": str(exc)})
