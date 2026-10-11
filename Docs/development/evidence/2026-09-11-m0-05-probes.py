"""Reproducible M0-05 acceptance observations and isolated behavioral mutants.

No source files are mutated. Each mutant is installed only inside its child
process, and must be detected by a real unittest assertion (not an import error).
Run from repository root with Python stdlib; no dependencies or global setup.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import io
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from aetp.core import projection as projection_module
from aetp.core import runtime as runtime_module
from aetp.core.commands import CommandResult
from aetp.core.projection import Projection
from aetp.core.runtime import RuntimeRecovery, SimulatedRuntime
from tests.m0.support import (
    RuntimeHarness, clear_projection_fixture, kill_process_after_commit,
    make_command, make_task_create_command, persist_receipt_only_fixture,
)
from tests.m0.test_replay_recovery import (
    effect_tripwires, observe_read_only_connections, state_digest,
)

SOURCE_PATHS = [
    "src/aetp/core/runtime.py", "src/aetp/core/projection.py", "tests/m0/support.py",
    "tests/m0/test_replay_recovery.py", "src/aetp/core/commands.py",
    "src/aetp/core/idempotency.py", "src/aetp/domain/models.py", "src/aetp/storage/sqlite_store.py",
]


def now():
    return datetime.now().astimezone().isoformat()


def source_hashes():
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in SOURCE_PATHS}


def event_digest(events):
    value = [event.to_dict() for event in events]
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def recovery_observation(directory, repetitions):
    path = directory / "pure-recovery.sqlite"
    harness = RuntimeHarness.open(str(path))
    try:
        before = harness.run_demo_flow("p-1")
        harness.seed_project("p-2", status="paused")
        pending_ids = ["z-received-first", "a-received-second"]
        for identity in pending_ids:
            command = make_command(
                command_id=identity, actor_id="a-1", command_type="task.create",
                target_id=identity, payload={"title": "diagnostic pending intent"},
                expected_revision=0, idempotency_key=identity,
            )
            persist_receipt_only_fixture(harness.store, command)
        command = make_command(
            command_id="p2-only", project_id="p-2", actor_id="a-1", command_type="task.create",
            target_id="p2-only", payload={"title": "paused receipt-only fault fixture"},
            expected_revision=0, idempotency_key="p2-only",
        )
        persist_receipt_only_fixture(harness.store, command)
        event_hash = event_digest(harness.store.read_events("p-1"))
        head = harness.store.read_events("p-1")[-1].sequence
        live_count = harness.runtime.invocation_count
        clear_projection_fixture(harness.store, project_id="p-1")
        clear_projection_fixture(harness.store, project_id="p-2")
    finally:
        harness.close()
    database_hash_before = hashlib.sha256(path.read_bytes()).hexdigest()
    positive_counts, recovery_runs = {}, []
    with effect_tripwires() as spies:
        for name, spy in spies.items():
            try:
                spy()
            except AssertionError:
                pass
            else:
                raise AssertionError(f"tripwire did not detect positive control: {name}")
            assert spy.call_count == 1
            positive_counts[name] = spy.call_count
            spy.reset_mock()
        with observe_read_only_connections() as (connections, write_attempts):
            for repetition in range(repetitions):
                recovery = RuntimeRecovery.open(str(path))
                try:
                    after = recovery.rebuild_project("p-1")
                    pending = recovery.reconcile_pending("p-1")
                    project2 = recovery.rebuild_project("p-2")
                    project2_pending = recovery.reconcile_pending("p-2")
                    assert after == before
                    assert state_digest(after) == state_digest(before)
                    assert pending == pending_ids
                    assert project2_pending == ["p2-only"]
                    assert project2["project:p-2"]["status"] == "paused"
                    assert recovery.runtime_invocation_count == 0
                    recovery_runs.append({
                        "repetition": repetition + 1,
                        "projection_digest": state_digest(after),
                        "pending_command_ids": pending,
                        "other_project_pending_ids": project2_pending,
                        "other_project_status": project2["project:p-2"]["status"],
                        "runtime_invocation_count": recovery.runtime_invocation_count,
                    })
                finally:
                    recovery.close()
            assert write_attempts == []
            connection_count = len(connections)
        replay_counts = {name: spy.call_count for name, spy in spies.items()}
        assert all(count == 0 for count in replay_counts.values())
    database_hash_after = hashlib.sha256(path.read_bytes()).hexdigest()
    assert database_hash_before == database_hash_after
    return {
        "projection_digest_before": state_digest(before),
        "event_digest_before": event_hash, "event_head_sequence": head,
        "database_digest_before": database_hash_before,
        "database_digest_after": database_hash_after,
        "live_simulator_invocations_before_restart": live_count,
        "simulation_source_example": SimulatedRuntime().execute(make_task_create_command()).to_dict(),
        "read_only_connections_opened_and_closed": connection_count,
        "sql_write_attempts": write_attempts,
        "effect_positive_control_counts": positive_counts,
        "effect_counts_during_recovery": replay_counts,
        "adapter_scope": "simulation.execute/stdlib exits are real spies; model.invoke and runtime.start are explicitly labelled sentinels for adapters absent in M0",
        "pending_scope": "artificial receipt-only Command fault fixtures; not a normal M0 partial commit or external Action/UNKNOWN state",
        "paused_scope": "preserves persisted project.created paused value only; no operational pause/resume verification",
        "runs": recovery_runs,
    }


def crash_observations(directory, repetitions):
    observations = []
    for index in range(repetitions):
        path = directory / f"post-commit-crash-{index}.sqlite"
        harness = RuntimeHarness.open(str(path))
        try:
            before_count = harness.domain_event_count("p-1")
        finally:
            harness.close()
        command = make_task_create_command(title="\u4efb\u52a1\u6062\u590d")
        original, witness = kill_process_after_commit(str(path), command)
        assert original.status == "accepted"
        assert witness["pid"] != os.getpid() and witness["exit_code"] != 0
        recovery = RuntimeRecovery.open(str(path))
        try:
            state = recovery.rebuild_project("p-1")
            assert state["task:t-1"]["title"] == "\u4efb\u52a1\u6062\u590d"
            assert recovery.reconcile_pending("p-1") == []
            assert recovery.runtime_invocation_count == 0
            recovered_digest = state_digest(state)
        finally:
            recovery.close()
        fresh = RuntimeHarness.open(str(path))
        try:
            before_retry = fresh.store.read_events("p-1")
            retries = [fresh.handle(command).to_dict() for _ in range(3)]
            after_retry = fresh.store.read_events("p-1")
            assert retries == [original.to_dict()] * 3
            assert before_retry == after_retry
            domain_after = fresh.domain_event_count("p-1")
            assert domain_after == before_count + 1
            assert fresh.runtime.invocation_count == 0
        finally:
            fresh.close()
        observations.append({
            "repetition": index + 1, "command": command.to_dict(),
            "commit_witness": witness,
            "retry_results": retries,
            "domain_count_before": before_count, "domain_count_after": domain_after,
            "domain_effect_increment": domain_after - before_count,
            "event_count_before_retry": len(before_retry), "event_count_after_retry": len(after_retry),
            "event_digest_before_retry": event_digest(before_retry),
            "event_digest_after_retry": event_digest(after_retry),
            "recovered_projection_digest": recovered_digest,
            "runtime_invocation_count": 0,
        })
    return observations


MUTANTS = {
    "cache_instead_of_events": ("ReplayRecoveryTests.test_a_forged_self_consistent_cache_is_not_an_authoritative_fact", "Replace forced Replay with ordinary cache read"),
    "dispatch_during_replay": ("ReplayRecoveryTests.test_forbidden_call_tripwires_have_positive_controls_then_remain_zero", "Execute simulation from rebuild_project"),
    "constant_runtime_counter": ("ReplayRecoveryTests.test_recovery_counter_reports_actual_simulator_calls_not_a_constant", "Return zero rather than actual counter"),
    "pending_always_empty": ("ReplayRecoveryTests.test_pending_ids_follow_receipt_sequence_not_lexical_order_or_task_status", "Discard every unresolved durable receipt"),
    "ignore_terminal_type": ("PendingProjectionTests.test_wrong_terminal_type_for_the_same_target_cannot_clear_pending", "Skip M0 Command-to-terminal type validation"),
    "writable_recovery": ("ReplayRecoveryTests.test_recovery_connection_is_enforced_read_only_by_sqlite", "Change SQLite recovery mode=ro to mode=rw"),
    "trust_result_index": ("ReplayRecoveryTests.test_pending_ids_do_not_trust_a_forged_terminal_result_index", "Treat a forged result index as completion instead of Event facts"),
    "no_read_snapshot": ("ReplayRecoveryTests.test_pending_uses_one_read_snapshot_during_a_concurrent_commit", "Remove the read transaction around Command/Event SELECTs"),
}


def source_mutation(function, old, new, module):
    code = textwrap.dedent(inspect.getsource(function))
    assert code.count(old) == 1, "mutation source does not match frozen implementation"
    namespace = dict(vars(module))
    exec(compile(code.replace(old, new, 1), "<M0-05 isolated source mutation>", "exec"), namespace)
    return namespace[function.__name__]


def run_mutation_worker(name):
    target, description = MUTANTS[name]
    with ExitStack() as stack:
        if name == "cache_instead_of_events":
            stack.enter_context(patch.object(RuntimeRecovery, "rebuild_project", lambda self, project: self._store.read_projection(project)))
        elif name == "dispatch_during_replay":
            original = RuntimeRecovery.rebuild_project

            def dispatch(self, project):
                self._runtime.execute(make_task_create_command())
                return original(self, project)

            stack.enter_context(patch.object(RuntimeRecovery, "rebuild_project", dispatch))
        elif name == "constant_runtime_counter":
            stack.enter_context(patch.object(RuntimeRecovery, "runtime_invocation_count", property(lambda self: 0)))
        elif name == "pending_always_empty":
            stack.enter_context(patch.object(RuntimeRecovery, "reconcile_pending", lambda self, project: []))
        elif name == "ignore_terminal_type":
            changed = source_mutation(
                Projection.pending_command_ids.__func__,
                "elif event.type != terminal_types.get(command.type):", "elif False:",
                projection_module,
            )
            stack.enter_context(patch.object(Projection, "pending_command_ids", changed))
        elif name == "writable_recovery":
            original = runtime_module.sqlite3.connect

            def writable(database, *args, **kwargs):
                if isinstance(database, str) and "?mode=ro" in database:
                    database = database.replace("?mode=ro", "?mode=rw")
                return original(database, *args, **kwargs)

            stack.enter_context(patch.object(runtime_module.sqlite3, "connect", writable))
        elif name == "trust_result_index":
            original = RuntimeRecovery.reconcile_pending

            def trust(self, project):
                pending = original(self, project)
                return [command_id for command_id in pending if not self._store._ensure_open().execute(
                    "SELECT result_json FROM idempotency WHERE command_id = ?", (command_id,),
                ).fetchone()[0]]

            stack.enter_context(patch.object(RuntimeRecovery, "reconcile_pending", trust))
        elif name == "no_read_snapshot":
            changed = source_mutation(
                RuntimeRecovery.reconcile_pending,
                'connection.execute("BEGIN")', 'None  # mutation: independent autocommit SELECTs',
                runtime_module,
            )
            stack.enter_context(patch.object(RuntimeRecovery, "reconcile_pending", changed))
        output = io.StringIO()
        suite = unittest.defaultTestLoader.loadTestsFromName("tests.m0.test_replay_recovery." + target)
        result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
    detected = result.testsRun == 1 and len(result.failures) == 1 and not result.errors
    print(json.dumps({
        "mutant": name, "description": description, "test": target,
        "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "detected_by_assertion": detected, "test_output": output.getvalue(),
    }, ensure_ascii=False))
    return 1 if detected else 2


def mutation_observations():
    results = []
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
    for name in MUTANTS:
        argv = [sys.executable, str(Path(__file__).resolve()), "--mutation-worker", name]
        start = now()
        result = subprocess.run(argv, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", timeout=60)
        entry = json.loads(result.stdout)
        entry.update(argv=argv, started_at=start, finished_at=now(), exit_code=result.returncode, stderr=result.stderr)
        results.append(entry)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mutation-worker", choices=sorted(MUTANTS))
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output", default="Docs/development/evidence/2026-09-11-m0-05-probes.json")
    args = parser.parse_args()
    if args.mutation_worker:
        return run_mutation_worker(args.mutation_worker)
    if not 1 <= args.repetitions <= 20:
        parser.error("--repetitions must be between 1 and 20")
    output = (ROOT / args.output).resolve()
    if not output.is_relative_to(ROOT):
        parser.error("--output must remain in this repository")
    if output.exists():
        parser.error("evidence already exists; select a fresh --output path")
    before_hashes = source_hashes()
    started_at = now()
    with tempfile.TemporaryDirectory(prefix="aetp-m0-05-probes-") as temporary:
        directory = Path(temporary).resolve()
        recovery = recovery_observation(directory, args.repetitions)
        crashes = crash_observations(directory, args.repetitions)
    mutations = mutation_observations()
    after_hashes = source_hashes()
    assert before_hashes == after_hashes, "source files changed during isolated probes"
    detected = all(entry["detected_by_assertion"] and entry["exit_code"] == 1 for entry in mutations)
    report = {
        "work_item": "M0-05", "started_at": started_at, "finished_at": now(),
        "status": "passed" if detected else "failed", "repetitions": args.repetitions,
        "source_sha256": before_hashes,
        "probe_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "recovery": recovery, "process_crashes": crashes,
        "mutations": mutations, "mutations_detected": sum(entry["detected_by_assertion"] for entry in mutations),
        "mutations_total": len(mutations),
        "claims": {"conformance_accepted": False, "bootstrap_verified": False, "external_tools_implemented": False},
    }
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "status": report["status"], "recovery_runs": len(recovery["runs"]),
        "real_post_commit_process_deaths": len(crashes),
        "mutations_detected": report["mutations_detected"], "mutations_total": len(mutations),
        "evidence": output.relative_to(ROOT).as_posix(),
    }))
    return 0 if detected else 1


if __name__ == "__main__":
    raise SystemExit(main())
