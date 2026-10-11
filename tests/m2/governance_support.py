"""Governance integration fixtures over real Commands, SQLite and document Sessions."""

import copy
from pathlib import Path
import tempfile

from aetp.domain.models import Command
from aetp.runtime.document import DocumentRuntime
from aetp.runtime.service import ExecutionService
from aetp.workspace.documents import DocumentWorkspace
from tests.m2.support import MeetingCase

try:
    from aetp.governance.service import GovernanceService
    from aetp.governance.trust import InputAuthority
except ModuleNotFoundError as exc:
    if not exc.name.startswith("aetp.governance"):
        raise
    GovernanceService = InputAuthority = None


def policy(version="gov-1", **rule_changes):
    rules = [{"action": action, "risk_level": "low", "approval": "auto"}
             for action in ("decision.activate", "document.write", "document.restore", "document.append")]
    for rule in rules:
        rule.update(rule_changes)
    return {"version": version, "mode": "selective", "max_ttl_ms": 3600000, "max_renewals": 2,
            "rules": rules,
            "subjects": {"human-owner": {"type": "human", "roles": ["human_owner"]},
                         "human-peer": {"type": "human", "roles": ["human_collaborator"]},
                         "a-1": {"type": "agent", "roles": ["agent_reviewer", "independent_reviewer"]},
                         "a-2": {"type": "agent", "roles": ["agent_reviewer", "independent_reviewer"]}}}


class GovernanceCase(MeetingCase):
    def setUp(self):
        self.assertIsNotNone(GovernanceService, "M2-02 GovernanceService is not implemented")
        super().setUp()
        temp_root = Path(__file__).resolve().parents[2] / ".tmp"
        temp_root.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="m2-02-", dir=temp_root)
        self.addCleanup(temporary.cleanup)
        self.workspace = DocumentWorkspace(Path(temporary.name) / "workspace")
        self.runtime = DocumentRuntime(self.workspace)
        self.execution = ExecutionService(self.store, self.runtime, clock=lambda: self.clock_value)
        self.eaccept(self.command("project.execution.configure", "p-1", actor="bootstrap"))
        self.execution.recover("p-1")
        self.eaccept(self.command("task.create", "t-1", {
            "title": "Document governance", "acceptance_criteria": ["Scope", "Recovery"]}))
        self.eaccept(self.command("task.claim", "t-1"))
        start = self.command("execution.start", "t-1", self.fence(), revision=self.task()["revision"])
        result, self.session = self.execution.start_session(start, authenticated_actor_id="a-1")
        self.assertEqual(result.status, "accepted", result.to_dict())
        self.assertIsNotNone(self.session)
        self.input_authority = InputAuthority("fixture-input-gateway")
        self.service = GovernanceService(self.store, owner_id="human-owner", execution=self.execution,
            input_authority=self.input_authority, meter=self.meter, clock=lambda: self.clock_value)
        self.configure()

    def configure(self, value=None):
        self.accept(self.command("project.governance.configure", "p-1", {"policy": value or policy()},
                                 actor="human-owner"))

    def command(self, kind, target, payload=None, *, actor="a-1", revision=None, key=None):
        self.counter += 1
        identifier = key or f"gov-command-{self.counter}"
        if revision is None:
            aggregate = kind.split(".")[0]
            if kind.startswith(("execution.", "lease.")) or kind in {"tool.request", "checkpoint.create"}:
                aggregate = "task"
            elif kind.startswith("tool."):
                aggregate = "action"
            row = self.state().get(f"{aggregate}:{target}")
            revision = row["revision"] if row else 0
        return Command(identifier, "p-1", actor, kind, target, payload or {}, revision, identifier, "m2-governance")

    def eaccept(self, command, *, session=None):
        result = self.execution.handle(command, authenticated_actor_id=command.actor_id, session=session)
        self.assertEqual(result.status, "accepted", result.to_dict())
        return result

    def ereject(self, command, code, *, session=None):
        result = self.execution.handle(command, authenticated_actor_id=command.actor_id, session=session)
        self.assertEqual((result.status, result.error_code), ("rejected", code), result.to_dict())
        return result

    def task(self):
        return self.state()["task:t-1"]

    def fence(self):
        task = self.task()
        data = {"binding_id": task["current_binding_id"], "lease_epoch": task["lease_epoch"]}
        if getattr(self, "session", None):
            data["session_id"] = self.session.id
        return data

    def document_arguments(self, content="Scope and Recovery"):
        return {**self.fence(), "document": {"content": content}}

    def request_command(self, identifier="ap-1", *, target=None, action="document.write", arguments=None,
                        actor="a-1", **extra):
        body = {"target": target or self.service.snapshot("p-1", "task", "t-1"), "action": action,
                "arguments": arguments if arguments is not None else self.document_arguments(), "ttl_ms": 1000}
        body.update(extra)
        return self.command("approval.request", identifier, body, actor=actor)

    def request_approval(self, identifier="ap-1", *, trusted=False, **kwargs):
        command = self.request_command(identifier, **kwargs)
        receipt = self.input_authority.issue(command, exposure="internal") if trusted else None
        result = self.service.handle(command, authenticated_actor_id=command.actor_id, input_receipt=receipt)
        self.assertEqual(result.status, "accepted", result.to_dict())
        return self.approval(identifier)

    def approval(self, identifier="ap-1"):
        return self.state()[f"approval:{identifier}"]

    def grant(self, identifier="ap-1", *, actor="a-2"):
        return self.command("approval.grant", identifier, {"reason": "Independently checked scope and evidence"}, actor=actor)

    def event_types(self):
        return [event.type for event in self.store.read_events("p-1")]

    def ready_decision(self, identifier="decision-1", **kwargs):
        proposal = self.propose(identifier=identifier, **kwargs)
        self.accept(self.command("decision.review", identifier, {"feedback": "Compared both options"}, actor="a-2"))
        self.accept(self.command("decision.submit", identifier))
        return proposal

    def approve_decision(self, identifier="decision-1", approval_id="decision-ap", **kwargs):
        self.request_approval(approval_id, target=self.service.snapshot("p-1", "decision", identifier),
                              action="decision.activate", arguments={"choice": "A"}, **kwargs)
        self.accept(self.grant(approval_id, actor="human-owner" if kwargs.get("risk_level") in {"medium", "high", "critical"} else "a-2"))
        self.accept(self.command("decision.approve", identifier,
                                 {"approval_id": approval_id, "arguments": {"choice": "A"}}))
        return self.state()[f"decision:{identifier}"]

    def request_document(self, approval_id="ap-1", content="Scope and Recovery"):
        result = self.eaccept(self.command("tool.request", "t-1", {**self.fence(), "operation": "document.write",
            "arguments": {"content": content}, "approval_id": approval_id}), session=self.session)
        effect = next(event for event in self.store.read_events("p-1") if event.id == result.event_ids[-1])
        return self.state()[f"action:{effect.aggregate_id}"]

    def control(self, action, *, identifier=None):
        return self.command(f"project.{action}", "p-1", {
            "intervention_id": identifier or f"intervention-{self.counter + 1}",
            "reason": "Human changes scheduling", "impact": "project"}, actor="human-owner")


def governance_process(db_path, mode, command_data, at, ready, go, output, done):
    """A separate writer/process, synchronized at the real OS resource gate."""
    import os
    from aetp.storage.sqlite_store import SQLiteStore
    try:
        with SQLiteStore.open(db_path) as store:
            service = GovernanceService(store, clock=lambda: at)
            ready.put({"pid": os.getpid()})
            if not go.wait(15):
                raise RuntimeError("process was not released")
            output.put({"phase": "attempting", "pid": os.getpid()})
            if mode == "tick":
                result = service.tick("p-1")
            else:
                command = Command.from_dict(command_data)
                result = service.handle(command, authenticated_actor_id=command.actor_id).to_dict()
            output.put({"phase": "result", "pid": os.getpid(), "result": result})
    except BaseException as exc:
        output.put({"phase": "error", "pid": os.getpid(), "error": type(exc).__name__, "detail": str(exc)})
    finally:
        done.set()
