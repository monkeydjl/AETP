"""A deterministic trusted-host scenario, shared by process tests and evidence.

All internal attestations here describe fixed literals generated in this file's
controlled context. These identities are fixtures, not autonomous model calls.
"""

from aetp.acceptance.service import AcceptanceService
from aetp.domain.models import Command
from aetp.governance.trust import InputAuthority
from aetp.runtime.contracts import COMMAND_AGGREGATES as EXECUTION_COMMANDS
from aetp.runtime.document import DocumentRuntime
from aetp.runtime.service import ExecutionService
from aetp.workspace.documents import DocumentWorkspace
from tests.m3.verification_support import verification_policy


class VerificationScenario:
    def __init__(self, store, workspace_root):
        self.store, self.counter, self.clock = store, 0, 1000
        self.sent = []
        self.runtime = DocumentRuntime(DocumentWorkspace(workspace_root))
        self.execution = ExecutionService(store, self.runtime, clock=lambda: self.clock)
        self.authority = InputAuthority("scenario-fixed-input-gateway")
        self.service = AcceptanceService(store, owner_id="human-owner", execution=self.execution,
            input_authority=self.authority, clock=lambda: self.clock)
        self.send("project.create", None, {"status": "planning"}, actor="bootstrap")
        for actor in ("a-1", "a-2"):
            self.send("agent.register", actor, {"model_id": f"deterministic-fixture-{actor}", "status": "available"}, actor="bootstrap")
        self.send("project.execution.configure", "p-1", actor="bootstrap", engine=self.execution)
        assert self.execution.recover("p-1")["barrier"] == "open"
        self.send("project.governance.configure", "p-1", {"policy": verification_policy()}, actor="human-owner")
        self.send("project.quality.configure", "p-1", {"grant_ttl_ms": 1000}, actor="human-owner")
        sessions = []
        for task_id, actor, criteria in (("t-1", "a-1", ["Scope", "Recovery"]), ("qa-task", "a-2", ["Execute Cases"])):
            self.send("task.create", task_id, {"title": "Fixed document scenario", "acceptance_criteria": criteria},
                      actor=actor, engine=self.execution)
            self.send("task.claim", task_id, actor=actor, engine=self.execution)
            _, session = self.send("execution.start", task_id, self.fence(task_id), actor=actor,
                                    engine=self.execution, start=True)
            assert session is not None
            sessions.append(session)
        self.author_session, self.qa_session = sessions

    def state(self):
        return self.store.read_projection("p-1")

    def fence(self, task_id, session=None):
        task = self.state()[f"task:{task_id}"]
        result = {"binding_id": task["current_binding_id"], "lease_epoch": task["lease_epoch"]}
        if session:
            result["session_id"] = session.id
        return result

    def send(self, kind, target, payload=None, *, actor="a-1", engine=None, session=None,
             trusted=False, start=False, expected="accepted", error=None):
        self.counter += 1
        identifier = f"verification-scenario-{self.counter}"
        aggregate = EXECUTION_COMMANDS.get(kind, kind.split(".")[0])
        revision = self.state().get(f"{aggregate}:{target}", {}).get("revision", 0)
        command = Command(identifier, "p-1", actor, kind, target, payload or {}, revision,
                          identifier, "fixed-verification-scenario")
        engine = engine or self.service
        if start:
            result, capability = engine.start_session(command, authenticated_actor_id=actor)
        elif engine is self.execution:
            result = engine.handle(command, authenticated_actor_id=actor, session=session)
        else:
            proof = self.authority.issue(command, exposure="internal") if trusted else None
            result = engine.handle(command, authenticated_actor_id=actor, session=session, input_receipt=proof)
        assert (result.status, result.error_code) == (expected, error), result.to_dict()
        self.sent.append({"command": command.to_dict(), "result": result.to_dict()})
        return (result, capability) if start else result

    def write(self, identifier="doc-1", content='{"scope":"local","recovery":true}'):
        fence = self.fence("t-1", self.author_session)
        approval_id = f"approval-{identifier}"
        self.send("approval.request", approval_id, {"target": self.service.snapshot("p-1", "task", "t-1"),
            "action": "document.write", "arguments": {**fence, "document": {"content": content}}, "ttl_ms": 1000}, trusted=True)
        result = self.send("tool.request", "t-1", {**fence, "operation": "document.write", "arguments": {"content": content},
            "approval_id": approval_id}, engine=self.execution, session=self.author_session)
        event = next(event for event in self.store.read_events("p-1") if event.id == result.event_ids[-1])
        action = self.execution.dispatch("p-1", event.aggregate_id, session=self.author_session)
        assert action["status"] == "completed"
        self.send("artifact.capture", identifier, {**fence, "source_action_id": action["id"]},
                  session=self.author_session, trusted=True)
        return self.state()[f"artifact:{identifier}"]

    def request(self, identifier="v-1", artifact_id="doc-1"):
        artifact = self.state()[f"artifact:{artifact_id}"]
        self.send("verification.request", identifier, {"artifact_id": artifact_id,
            "artifact_digest": artifact["content_digest"], "exec_task_id": "qa-task",
            **self.fence("qa-task", self.qa_session), "cases": [
                {"criterion": "Scope", "path": ["scope"], "equals": "local"},
                {"criterion": "Recovery", "path": ["recovery"], "equals": True}]},
            actor="a-2", session=self.qa_session, trusted=True)
        return self.state()[f"verification:{identifier}"]
