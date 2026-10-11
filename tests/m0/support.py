"""Reusable fixtures for M0 command-boundary tests."""

from __future__ import annotations

import math
import multiprocessing
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aetp.domain.models import Command
from aetp.storage.sqlite_store import SQLiteStore


@dataclass
class CommandFixture:
    db_path: str
    store: SQLiteStore
    handler: Any
    after_sequence: int


def new_test_db_path(testcase):
    tempdir = tempfile.TemporaryDirectory()
    testcase.addCleanup(tempdir.cleanup)
    return str(Path(tempdir.name) / "m0.sqlite")


def _command_id(idempotency_key: str, suffix: str = "") -> str:
    token = "".join(char if char.isalnum() else "-" for char in idempotency_key)
    return f"cmd-{token}{suffix}"


def make_task_create_command(
    *, actor_id: str = "a-1", idempotency_key: str = "k-1", expected_revision: int | None = 0,
    title: str = "Demo task", command_id: str | None = None,
) -> Command:
    return Command(
        command_id or _command_id(idempotency_key),
        "p-1",
        actor_id,
        "task.create",
        "t-1",
        {"title": title},
        expected_revision,
        idempotency_key,
        f"corr-{idempotency_key}",
    )


def make_command(
    *, command_id: str, actor_id: str, command_type: str, target_id: str | None,
    payload: dict[str, Any], expected_revision: int | None, idempotency_key: str,
    project_id: str = "p-1", correlation_id: str | None = None,
) -> Command:
    return Command(
        command_id,
        project_id,
        actor_id,
        command_type,
        target_id,
        payload,
        expected_revision,
        idempotency_key,
        correlation_id or f"corr-{idempotency_key}",
    )


def open_command_fixture(testcase) -> CommandFixture:
    db_path = new_test_db_path(testcase)
    store = SQLiteStore.open(db_path)
    testcase.addCleanup(store.close)
    try:
        from aetp.core.commands import CommandHandler
    except ModuleNotFoundError:
        return CommandFixture(db_path=db_path, store=store, handler=None, after_sequence=0)

    handler = CommandHandler(store)
    bootstrap_commands = [
        make_command(
            command_id="seed-project",
            actor_id="bootstrap",
            command_type="project.create",
            target_id=None,
            payload={"status": "planning"},
            expected_revision=0,
            idempotency_key="seed-project",
        ),
        make_command(
            command_id="seed-agent-a1",
            actor_id="bootstrap",
            command_type="agent.register",
            target_id="a-1",
            payload={"model_id": "model-1", "status": "available"},
            expected_revision=0,
            idempotency_key="seed-agent-a1",
        ),
        make_command(
            command_id="seed-agent-a2",
            actor_id="bootstrap",
            command_type="agent.register",
            target_id="a-2",
            payload={"model_id": "model-2", "status": "available"},
            expected_revision=0,
            idempotency_key="seed-agent-a2",
        ),
    ]
    for command in bootstrap_commands:
        result = handler.handle(command, authenticated_actor_id="bootstrap")
        if result.status != "accepted":
            raise AssertionError(f"bootstrap command was not accepted: {result}")
    events = store.read_events("p-1")
    after_sequence = events[-1].sequence if events else 0
    return CommandFixture(
        db_path=db_path, store=store, handler=handler, after_sequence=after_sequence
    )


def install_event_failure_fixture(testcase, store, event_type="task.created"):
    """Inject a real SQLite failure after receipt, without production test hooks."""
    from aetp.domain.models import EVENT_TYPES

    if event_type not in EVENT_TYPES:
        raise ValueError("invalid Event type for fault injection")
    connection = store._ensure_open()
    connection.execute(
        "CREATE TEMP TRIGGER fail_event_insert BEFORE INSERT ON events "
        f"WHEN NEW.type = '{event_type}' "
        "BEGIN SELECT RAISE(ABORT, 'injected event failure'); END"
    )

    def remove():
        connection.execute("DROP TRIGGER IF EXISTS temp.fail_event_insert")

    testcase.addCleanup(remove)
    return remove


def install_result_failure_fixture(testcase, store):
    """Fail result-index persistence after both Events have been inserted."""
    connection = store._ensure_open()
    connection.execute(
        "CREATE TEMP TRIGGER fail_result_update "
        "BEFORE UPDATE OF result_json ON idempotency "
        "BEGIN SELECT RAISE(ABORT, 'injected result failure'); END"
    )

    def remove():
        connection.execute("DROP TRIGGER IF EXISTS temp.fail_result_update")

    testcase.addCleanup(remove)
    return remove


def clear_projection_fixture(store, *, project_id):
    """Discard only test Projection cache rows, never Command/Event facts."""
    with store.transaction():
        connection = store._ensure_open()
        connection.execute("DELETE FROM projections WHERE project_id = ?", (project_id,))
        connection.execute("DELETE FROM projection_meta WHERE project_id = ?", (project_id,))


def install_projection_failure_fixture(testcase, store):
    """Fail cache metadata writes after durable Event insertion has been attempted."""
    connection = store._ensure_open()
    for action in ("INSERT", "UPDATE"):
        connection.execute(
            f"CREATE TEMP TRIGGER fail_projection_{action.lower()} "
            f"BEFORE {action} ON projection_meta "
            "BEGIN SELECT RAISE(ABORT, 'injected projection failure'); END"
        )

    def remove():
        for action in ("insert", "update"):
            connection.execute(f"DROP TRIGGER IF EXISTS temp.fail_projection_{action}")

    testcase.addCleanup(remove)
    return remove


def make_claim_commands(*, task_id: str, expected_revision: int) -> list[Command]:
    """Two independent registered actors submit the same version precondition."""
    commands = []
    for actor in ("a-1", "a-2"):
        key = f"claim-{task_id}-{actor}-r{expected_revision}"
        commands.append(make_command(
            command_id=f"cmd-{key}", actor_id=actor, command_type="task.claim",
            target_id=task_id, payload={}, expected_revision=expected_revision,
            idempotency_key=key, correlation_id=f"corr-claim-{task_id}",
        ))
    return commands


def _command_process(db_path, command_data, start_gate, output):
    """Spawn-safe target: no inherited connection or shared correctness lock."""
    from aetp.core.commands import CommandHandler

    store = None
    try:
        command = Command.from_dict(command_data)
        store = SQLiteStore.open(db_path)
        events = store.read_events(command.project_id)
        output.send({
            "stage": "ready", "pid": os.getpid(), "command_id": command.id,
            "idempotency_key": command.idempotency_key,
            "expected_revision": command.expected_revision,
            "observed_head_sequence": events[-1].sequence if events else 0,
            "ready_ns": time.monotonic_ns(),
        })
        start_gate.wait()
        handling_started_ns = time.monotonic_ns()
        result = CommandHandler(store).handle(
            command, authenticated_actor_id=command.actor_id,
        )
        output.send({
            "stage": "result", "result": result.to_dict(),
            "handling_started_ns": handling_started_ns,
        })
    except Exception as exc:
        try:
            output.send({
                "stage": "error", "pid": os.getpid(),
                "error_type": type(exc).__name__, "message": str(exc),
            })
        except (BrokenPipeError, EOFError, OSError):
            pass  # Parent already timed out; it owns termination and reaping.
    finally:
        if store is not None:
            store.close()
        output.close()


def _receive_process_message(connection, deadline, expected_stage):
    remaining = max(0.0, deadline - time.monotonic())
    if not connection.poll(remaining):
        raise TimeoutError(f"two-process fixture timed out waiting for {expected_stage}")
    try:
        message = connection.recv()
    except EOFError as exc:
        raise RuntimeError("worker exited without a complete result") from exc
    if message["stage"] == "error":
        raise RuntimeError(
            f"worker {message['pid']} failed: {message['error_type']}: {message['message']}"
        )
    if message["stage"] != expected_stage:
        raise RuntimeError(f"unexpected worker stage: {message['stage']}")
    return message


def run_two_processes_against_same_sqlite_file(
    db_path, commands, *, observations=None, timeout=30.0,
):
    """Return two real process outcomes in input order, or propagate failure.

    Each spawned child opens its own SQLiteStore and reads the pre-race head.
    The gate releases only after BOTH children are ready; it synchronizes the
    test, not the writes. Durable SQLite transactions arbitrate the Commands.
    A single bounded deadline covers startup, results and successful joins.
    Only children created by this call are terminated/reaped on failure.
    """
    from aetp.core.commands import CommandResult

    commands = list(commands)
    if len(commands) != 2 or any(not isinstance(command, Command) for command in commands):
        raise ValueError("exactly two validated Commands are required")
    if str(db_path) == ":memory:":
        raise ValueError("a shared SQLite file is required, not separate memory stores")
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("timeout must be positive and finite")
    context = multiprocessing.get_context("spawn")
    start_gate = context.Event()
    deadline = time.monotonic() + timeout
    processes, readers, senders = [], [], []
    try:
        for command in commands:
            reader, sender = context.Pipe(duplex=False)
            readers.append(reader)
            senders.append(sender)
            process = context.Process(
                target=_command_process,
                args=(str(db_path), command.to_dict(), start_gate, sender),
            )
            processes.append(process)
            process.start()
            sender.close()
        ready = [_receive_process_message(reader, deadline, "ready") for reader in readers]
        gate_released_ns = time.monotonic_ns()
        start_gate.set()
        completed = [_receive_process_message(reader, deadline, "result") for reader in readers]
        for process in processes:
            process.join(max(0.0, deadline - time.monotonic()))
            if process.is_alive():
                raise TimeoutError("two-process fixture timed out joining worker")
            if process.exitcode != 0:
                raise RuntimeError(f"worker {process.pid} exited with code {process.exitcode}")
        results = [CommandResult.from_dict(message["result"]) for message in completed]
        if observations is not None:
            for initial, final, process in zip(ready, completed, processes):
                observations.append({
                    **{key: value for key, value in initial.items() if key != "stage"},
                    "handling_started_ns": final["handling_started_ns"],
                    "gate_released_ns": gate_released_ns,
                    "exit_code": process.exitcode, "result": final["result"],
                })
        return results
    finally:
        for connection in readers + senders:
            connection.close()
        for process in processes:
            if process.pid is not None and process.is_alive():
                process.terminate()
        for process in processes:
            if process.pid is not None:
                process.join(5)
                if process.is_alive():
                    process.kill()
                    process.join(5)
                if process.is_alive():
                    raise RuntimeError(f"could not reap owned worker {process.pid}")
            process.close()


class RuntimeHarness:
    """Test-only trusted caller; the simulator never acknowledges durable work.

    Only this fixture binds actor a-1; production authentication is not inferred
    from a Command payload. Bootstrap uses the explicit trusted bootstrap actor.
    """

    def __init__(self, db_path, store, runtime):
        from aetp.core.commands import CommandHandler

        self.db_path = str(db_path)
        self.store = store
        self.runtime = runtime
        self.handler = CommandHandler(store)

    @classmethod
    def open(cls, db_path):
        from aetp.core.runtime import SimulatedRuntime

        if str(db_path) == ":memory:":
            raise ValueError("RuntimeHarness requires a persisted database")
        is_new = not Path(db_path).exists()
        store = SQLiteStore.open(db_path)
        try:
            harness = cls(db_path, store, SimulatedRuntime())
            if is_new:
                harness.seed_project("p-1")
            return harness
        except BaseException:
            store.close()
            raise

    def seed_project(self, project_id, *, status="planning"):
        """Same prerequisites as CommandFixture, via validated Commands only."""
        specifications = [
            ("project", "project.create", None, {"status": status}),
            ("agent-a1", "agent.register", "a-1", {"model_id": "model-1", "status": "available"}),
            ("agent-a2", "agent.register", "a-2", {"model_id": "model-2", "status": "available"}),
        ]
        for suffix, command_type, target_id, payload in specifications:
            key = f"{project_id}:seed-{suffix}"
            command = make_command(
                command_id=key, project_id=project_id, actor_id="bootstrap",
                command_type=command_type, target_id=target_id, payload=payload,
                expected_revision=0, idempotency_key=key,
            )
            result = self.handler.handle(command, authenticated_actor_id="bootstrap")
            if result.status != "accepted":
                raise AssertionError(f"bootstrap command was not accepted: {result}")

    def handle(self, command):
        return self.handler.handle(command, authenticated_actor_id="a-1")

    def run_demo_flow(self, project_id):
        """Create, claim and release; never claim a Task completed in M0."""
        for revision, command_type, payload in [
            (0, "task.create", {"title": "Demo task"}),
            (0, "task.claim", {}),
            (1, "task.release", {}),
        ]:
            key = f"{project_id}:demo:{command_type}"
            command = make_command(
                command_id=key, project_id=project_id, actor_id="a-1",
                command_type=command_type, target_id="demo-task", payload=payload,
                expected_revision=revision, idempotency_key=key,
            )
            result = self.handle(command)
            if result.status != "accepted":
                raise AssertionError(f"demo command was not accepted: {result}")
            # Deliberately separate from durable acceptance and from all replay.
            # The returned simulation-only observation is NOT a Command receipt.
            self.runtime.execute(command)
        return self.store.read_projection(project_id)

    def commit_then_drop_response(self, command):
        """Out-of-band fault witness, not a delivered response to a client.

        The test controller captures the committed result for assertions only.
        The process fixture below stops at this boundary and is forcibly killed
        before it can deliver a response or gracefully close its store.
        """
        return self.handle(command)

    def domain_event_count(self, project_id):
        return sum(
            event.type not in {"command.received", "command.rejected"}
            for event in self.store.read_events(project_id)
        )

    def close(self):
        self.store.close()


def persist_receipt_only_fixture(store, command):
    """Trusted storage fault fixture, NOT a new public Command acceptance path.

    Normal M0 handling atomically commits a terminal batch. This artificial
    incomplete receipt exercises conservative recovery of recorded intent, not
    external Action/UNKNOWN semantics and never an executable dispatch queue.
    """
    from aetp.domain.models import Event

    aggregate_type = command.type.split(".", 1)[0]
    aggregate_id = command.target_id or command.project_id
    with store.transaction():
        store.append_command(command)
        store.append_events([Event(
            id=f"{command.id}:received", project_id=command.project_id,
            sequence=0, type="command.received", aggregate_type=aggregate_type,
            aggregate_id=aggregate_id, aggregate_revision=0,
            causation_id=command.id, correlation_id=command.correlation_id,
            payload={"command_type": command.type, "request_digest": command.digest()},
        )])


def _response_loss_process(db_path, command_data, witness, hold_gate):
    """Only the supervising TEST channel observes commit, never the client."""
    harness = None
    try:
        harness = RuntimeHarness.open(db_path)
        command = Command.from_dict(command_data)
        result = harness.commit_then_drop_response(command)
        witness.send({"stage": "committed", "pid": os.getpid(), "result": result.to_dict()})
        hold_gate.wait()  # Parent kills this process; no client response below.
        witness.send({"stage": "unexpected_response"})
    except Exception as exc:
        witness.send({"stage": "error", "error_type": type(exc).__name__, "message": str(exc)})
    finally:
        if harness is not None:
            harness.close()
        witness.close()


def kill_process_after_commit(db_path, command, *, timeout=20.0):
    """Terminate/reap only our owned child at the post-commit response boundary."""
    from aetp.core.commands import CommandResult

    context = multiprocessing.get_context("spawn")
    reader, writer = context.Pipe(duplex=False)
    gate = context.Event()
    child = context.Process(
        target=_response_loss_process,
        args=(str(db_path), command.to_dict(), writer, gate),
    )
    try:
        child.start()
        writer.close()
        if not reader.poll(timeout):
            raise TimeoutError("response-loss worker did not reach commit boundary")
        message = reader.recv()
        if message.get("stage") != "committed":
            raise AssertionError(f"response-loss worker failed: {message}")
        child.terminate()
        child.join(timeout)
        if child.is_alive():
            raise TimeoutError("response-loss worker did not terminate")
        result = CommandResult.from_dict(message["result"])
        observation = {
            "pid": message["pid"], "exit_code": child.exitcode,
            "boundary": "committed_before_client_response", "result": result.to_dict(),
        }
        return result, observation
    finally:
        reader.close()
        writer.close()
        if child.pid is not None:
            if child.is_alive():
                child.terminate()
            child.join(5)
            if child.is_alive():
                child.kill()
                child.join(5)
            if child.is_alive():
                raise RuntimeError(f"could not reap owned worker {child.pid}")
        child.close()
