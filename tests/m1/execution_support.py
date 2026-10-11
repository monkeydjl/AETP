"""Real SQLite/Windows fixtures for execution-boundary tests."""

from pathlib import Path
import tempfile
import unittest
import os

from aetp.domain.models import Command
from tests.m0.support import open_command_fixture

try:
    from aetp.runtime.service import ExecutionService
    from aetp.runtime.document import DocumentRuntime
    from aetp.workspace.documents import DocumentWorkspace
except ModuleNotFoundError as exc:
    if not exc.name.startswith(("aetp.runtime", "aetp.workspace")):
        raise
    ExecutionService = DocumentRuntime = DocumentWorkspace = None


class ManualClock:
    def __init__(self, value=1_800_000_000_000):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, milliseconds):
        self.value += milliseconds


class ExecutionCase(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(ExecutionService, "M1-02 execution boundary is not implemented")
        self.fixture = open_command_fixture(self)
        self.store = self.fixture.store
        # The managed host cannot pin C:/Users/Alin itself. Keep the actual
        # Workspace under the declared writable repository, whose ancestors
        # can be pinned. The production provider still refuses unsafe roots.
        temp_root = Path(__file__).resolve().parents[2] / ".tmp"
        temp_root.mkdir(exist_ok=True)
        workspace_temp = tempfile.TemporaryDirectory(prefix="m1-02-", dir=temp_root)
        self.addCleanup(workspace_temp.cleanup)
        self.root = Path(workspace_temp.name) / "working-copies"
        self.clock = ManualClock()
        self.workspace = DocumentWorkspace(self.root)
        self.runtime = DocumentRuntime(self.workspace)
        self.service = ExecutionService(self.store, self.runtime, clock=self.clock)
        self.counter = 0
        self.accept(self.command("project.execution.configure", "p-1", {}, actor="bootstrap"))
        self.assertEqual(self.service.recover("p-1")["barrier"], "open")
        self.accept(self.command("task.create", "t-1", {
            "title": "Write a recovery guide", "acceptance_criteria": ["Overview", "Failure case"]}))
        self.session = None

    def state(self):
        return self.store.read_projection("p-1")

    def task(self, identifier="t-1"):
        return self.state()[f"task:{identifier}"]

    def command(self, kind, target, payload, *, actor="a-1", revision=None, key=None):
        self.counter += 1
        key = key or f"execution-{self.counter:04d}"
        if revision is None:
            aggregate = "project" if kind.startswith("project.") else (
                "action" if kind in {"tool.dispatch", "tool.report", "tool.reconcile", "tool.cancel"} else "task")
            revision = self.state().get(f"{aggregate}:{target}", {}).get("revision", 0)
        return Command(key, "p-1", actor, kind, target, payload, revision, key, "execution-conversation")

    def accept(self, command, *, session=None):
        result = self.service.handle(command, authenticated_actor_id=command.actor_id, session=session)
        self.assertEqual(result.status, "accepted", result.to_dict())
        return result

    def reject(self, command, code, *, session=None, actor=None):
        result = self.service.handle(command, authenticated_actor_id=actor or command.actor_id, session=session)
        self.assertEqual(result.status, "rejected", result.to_dict())
        self.assertEqual(result.error_code, code)
        return result

    def claim(self, *, actor="a-1"):
        self.accept(self.command("task.claim", "t-1", {}, actor=actor))
        return self.task()

    def fence(self):
        task = self.task()
        payload = {"binding_id": task["current_binding_id"], "lease_epoch": task["lease_epoch"]}
        if self.session is not None:
            payload["session_id"] = self.session.id
        return payload

    def start(self, *, actor="a-1"):
        command = self.command("execution.start", "t-1", self.fence(), actor=actor)
        self.last_start_command = command
        result, self.session = self.service.start_session(command, authenticated_actor_id=actor)
        self.assertEqual(result.status, "accepted", result.to_dict())
        self.assertIsNotNone(self.session)
        return self.session

    def request(self, content="Overview\nFailure case\n", *, actor="a-1", operation="document.write", arguments=None):
        command = self.command("tool.request", "t-1", {**self.fence(), "operation": operation,
                               "arguments": arguments if arguments is not None else {"content": content}}, actor=actor)
        result = self.accept(command, session=self.session)
        event = next(e for e in self.store.read_events("p-1") if e.id == result.event_ids[-1])
        return self.state()[f"action:{event.aggregate_id}"]

    def dispatch(self, action):
        return self.service.dispatch("p-1", action["id"], session=self.session)

    def checkpoint(self, *, actor="a-1"):
        result = self.accept(self.command("checkpoint.create", "t-1", {**self.fence(),
            "context_snapshot": "Overview was written. Preserve the prior document.",
            "remaining_work": ["Add recovery detail"]}, actor=actor), session=self.session)
        event = next(e for e in self.store.read_events("p-1") if e.id == result.event_ids[-1])
        return self.state()[f"checkpoint:{event.aggregate_id}"]

    def handoff(self):
        self.accept(self.command("lease.revoke", "t-1", {**self.fence(), "reason": "handoff"}))
        self.service.recover("p-1")
        self.accept(self.command("task.requeue", "t-1", {}, actor="a-1"))
        self.session = None


def foreign_workspace_reconciler(db_path, workspace_path, action_id, ready, go, output):
    """A separate process with its own provider identity tries to reconcile a foreign Action."""
    from aetp.storage.sqlite_store import SQLiteStore
    try:
        with SQLiteStore.open(db_path) as store:
            runtime = DocumentRuntime(DocumentWorkspace(workspace_path))
            service = ExecutionService(store, runtime, clock=ManualClock())
            ready.send({"pid": os.getpid(), "provider_id": runtime.workspace.identity})
            if not go.wait(15):
                raise RuntimeError("foreign-workspace test was not released")
            result = service.reconcile("p-1", action_id)
            output.send({"pid": os.getpid(), "result": result})
    except BaseException as exc:
        output.send({"pid": os.getpid(), "error": type(exc).__name__, "detail": str(exc)})
    finally:
        ready.close()
        output.close()


def competing_claim(db_path, workspace_path, command_data, ready, go, output):
    """Compete through separate stores/processes, not a Python-only lock."""
    from aetp.storage.sqlite_store import SQLiteStore
    try:
        with SQLiteStore.open(db_path) as store:
            service = ExecutionService(store, DocumentRuntime(DocumentWorkspace(workspace_path)), clock=ManualClock())
            ready.put(True)
            if not go.wait(15):
                raise RuntimeError("competition did not start")
            command = Command.from_dict(command_data)
            result = service.handle(command, authenticated_actor_id=command.actor_id)
            output.put(result.to_dict())
    except BaseException as exc:
        output.put({"error": type(exc).__name__, "detail": str(exc)})


def process_document_worker(db_path, workspace_path, mode, output, allow_effect=None):
    """Real process termination or delayed filesystem operation after IN_FLIGHT."""
    from aetp.storage.sqlite_store import SQLiteStore
    try:
        with SQLiteStore.open(db_path) as store:
            runtime = DocumentRuntime(DocumentWorkspace(workspace_path))
            service = ExecutionService(store, runtime, clock=ManualClock())
            service.recover("p-1")
            task = store.read_projection("p-1")["task:t-1"]
            fence = {"binding_id": task["current_binding_id"], "lease_epoch": task["lease_epoch"]}
            start = Command("process-start", "p-1", "a-1", "execution.start", "t-1", fence,
                            task["revision"], "process-start", "process-test")
            result, session = service.start_session(start, authenticated_actor_id="a-1")
            if result.status != "accepted" or session is None:
                raise AssertionError(result.to_dict())
            task = store.read_projection("p-1")["task:t-1"]
            request = Command("process-request", "p-1", "a-1", "tool.request", "t-1",
                {**fence, "session_id": session.id, "operation": "document.write",
                 "arguments": {"content": "document from a separate process"}},
                task["revision"], "process-request", "process-test")
            result = service.handle(request, authenticated_actor_id="a-1", session=session)
            if result.status != "accepted":
                raise AssertionError(result.to_dict())
            action = next(value for key, value in store.read_projection("p-1").items() if key.startswith("action:"))
            real_write = runtime.workspace.write

            def fault_window(record, authorize):
                if store.in_transaction:
                    raise AssertionError("external effect inside transaction")
                if mode == "crash_before":
                    output.send({"phase": "in_flight", "action_id": record["id"]})
                    os._exit(73)
                if mode == "delayed":
                    output.send({"phase": "in_flight", "action_id": record["id"]})
                    if not allow_effect.wait(15):
                        raise AssertionError("effect release was not received")
                if mode == "crash_unpublished":
                    from unittest.mock import patch
                    real_fsync = os.fsync

                    def exit_after_flush(descriptor):
                        real_fsync(descriptor)
                        output.send({"phase": "unpublished_bytes_flushed", "action_id": record["id"]})
                        os._exit(73)

                    with patch("aetp.workspace.documents.os.fsync", side_effect=exit_after_flush):
                        return real_write(record, authorize)
                receipt = real_write(record, authorize)
                if mode == "crash_after":
                    output.send({"phase": "effect_written", "action_id": record["id"]})
                    os._exit(73)
                return receipt

            runtime.workspace.write = fault_window
            completed = service.dispatch("p-1", action["id"], session=session)
            output.send({"phase": "completed", "status": completed["status"], "action_id": action["id"]})
    except BaseException as exc:
        output.send({"error": type(exc).__name__, "detail": str(exc)})
    finally:
        output.close()


def process_revoker(db_path, workspace_path, command_data, output):
    from aetp.storage.sqlite_store import SQLiteStore
    try:
        with SQLiteStore.open(db_path) as store:
            service = ExecutionService(store, DocumentRuntime(DocumentWorkspace(workspace_path)), clock=ManualClock())
            command = Command.from_dict(command_data)
            output.send({"phase": "attempting_revocation"})
            result = service.handle(command, authenticated_actor_id=command.actor_id)
            output.send(result.to_dict())
    except BaseException as exc:
        output.send({"error": type(exc).__name__, "detail": str(exc)})
    finally:
        output.close()
