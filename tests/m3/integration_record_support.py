"""Pure evaluator fixtures. DraftCommand is NOT an authenticated domain Command."""

import copy
import hashlib
import unittest
from dataclasses import asdict, dataclass, replace

from aetp.collaboration.policy import PolicyViolation, canonical_json, digest_value
from tests.m3.quality_support import QualityCase
from tests.m3.test_integration_contract_inputs import target_fixture

try:
    from aetp.integration.records import evaluate
except ModuleNotFoundError as exc:
    if exc.name != "aetp.integration.records":
        raise
    evaluate = None


@dataclass(frozen=True)
class DraftCommand:
    id: str
    project_id: str
    actor_id: str
    type: str
    target_id: str
    payload: dict
    expected_revision: int
    idempotency_key: str
    correlation_id: str

    def digest(self):
        # Match Command.digest wire algorithm; deliberately not a Command subtype.
        return hashlib.sha256(canonical_json(asdict(self)).encode("utf-8")).hexdigest()


class RecordCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture = QualityCase()
        try:
            fixture.setUp()
            cls.exempt_snapshot = fixture.state()
            fixture.configure_task_quality(version="without-exemption", exempt=False)
            cls.snapshot = fixture.state()
            cls.at = fixture.clock_value
        finally:
            # unittest.run normally does this; direct fixture setup must do it too.
            fixture.doCleanups()

    def setUp(self):
        self.assertIsNotNone(evaluate, "Integration declaration evaluator is not implemented")
        self.state = copy.deepcopy(self.snapshot)

    def project(self):
        return self.state["project:p-1"]

    def task(self):
        return self.state["task:t-1"]

    def command(self, *, state=None, task_id="t-1", version=1, **changes):
        state = self.state if state is None else state
        payload = {"task_id": task_id, "expected_task_revision": state[f"task:{task_id}"]["revision"],
                   "version": version, "supersedes_version": version - 1 if version > 1 else None,
                   "requirement": "required", "target": target_fixture(), "reason": "  需要集成  "}
        command = DraftCommand(f"declare-{task_id}-{version}", "p-1", "human-owner", "project.integration.declare",
                               "p-1", payload, state["project:p-1"]["revision"], f"key-{task_id}-{version}", "integration")
        return replace(command, **changes)

    def context(self, command, *, state=None):
        state = self.state if state is None else state
        # Historical data fixture only. No InputAuthority has issued this draft.
        return {"channel": "agent", "input_proof": {
            "receipt_id": "historical-proof-fixture", "source_id": state["project:p-1"]["governance"]["input_authority_id"],
            "command_digest": command.digest(), "actor_id": command.actor_id,
            "exposure": "trusted", "sources": [{"source_id": "human-request", "exposure": "internal"}]}}

    def result(self, command=None, *, state=None, context=None, at=None):
        state = self.state if state is None else state
        command = self.command(state=state) if command is None else command
        context = self.context(command, state=state) if context is None else context
        before = copy.deepcopy((state, asdict(command), context))
        try:
            return evaluate(command, state, self.at if at is None else at, context)
        finally:
            self.assertEqual((state, asdict(command), context), before, "pure evaluation mutated inputs")

    def reject(self, code, command=None, **kwargs):
        with self.assertRaises(PolicyViolation) as caught:
            self.result(command, **kwargs)
        self.assertEqual(caught.exception.code, code)

    @staticmethod
    def version(record, task_id="t-1", version=1):
        return record["integration_contract"]["tasks"][task_id]["versions"][str(version)]

    def rehash_policies(self):
        project = self.project()
        for key in ("governance", "task_quality_policy"):
            history = project[key]
            value = history["versions"][history["current_version"]]
            value["content_digest"] = digest_value(value["policy"])
