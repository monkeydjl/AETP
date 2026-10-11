"""Reproducible M0-04 observations and isolated mutation checks (stdlib only).

Run from the repository root. JSON goes to stdout; this script never edits
canonical product/test files. Temporary SQLite files and mutant trees are
owned by this run and removed after their resolved cleanup roots are checked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]

from aetp.core.commands import CommandHandler
from aetp.core.projection import Projection
from aetp.storage.sqlite_store import SQLiteStore
from tests.m0.support import (
    clear_projection_fixture, make_claim_commands, make_command,
    make_task_create_command, open_command_fixture,
    run_two_processes_against_same_sqlite_file,
)

SOURCE_PATHS = (
    "src/aetp/core/idempotency.py", "src/aetp/core/commands.py",
    "src/aetp/storage/sqlite_store.py", "src/aetp/core/projection.py",
    "tests/m0/support.py", "tests/m0/test_idempotency_concurrency.py",
)


def source_hashes():
    return {path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest() for path in SOURCE_PATHS}


def digest(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def durable_rows(store):
    return {
        table: store._ensure_open().execute(f"SELECT * FROM {table} ORDER BY 1, 2, 3").fetchall()
        for table in ("commands", "events", "idempotency")
    }


def race(kind, repetition):
    case = unittest.TestCase()
    try:
        fixture = open_command_fixture(case)
        store = fixture.store
        if kind == "claims":
            assert fixture.handler.handle(make_task_create_command(), authenticated_actor_id="a-1").status == "accepted"
            commands = make_claim_commands(task_id="t-1", expected_revision=0)
            expected_head, expected_delta = 8, 4
        else:
            first = make_task_create_command(idempotency_key="shared", title="First")
            second = first if kind == "duplicate" else replace(first, id="conflicting-command", payload={"title": "Second"})
            commands = [first, second]
            expected_head, expected_delta = 6, 2
        before_events = store.read_events("p-1")
        assert len(before_events) == expected_head
        observations = []
        results = run_two_processes_against_same_sqlite_file(fixture.db_path, commands, observations=observations)
        assert len(observations) == len(results) == 2
        assert len({entry["pid"] for entry in observations}) == 2
        assert os.getpid() not in {entry["pid"] for entry in observations}
        for command, observed, result in zip(commands, observations, results):
            assert observed["exit_code"] == 0
            assert observed["command_id"] == command.id
            assert observed["idempotency_key"] == command.idempotency_key
            assert observed["expected_revision"] == command.expected_revision
            assert observed["observed_head_sequence"] == expected_head
            assert observed["ready_ns"] <= observed["gate_released_ns"] <= observed["handling_started_ns"]
            assert observed["result"] == result.to_dict()
        events = store.read_events("p-1")
        assert len(events) == expected_head + expected_delta
        assert [event.sequence for event in events] == list(range(1, len(events) + 1))
        increment = events[expected_head:]
        winner = next(i for i, result in enumerate(results) if result.status == "accepted")
        if kind == "duplicate":
            assert results[0] == results[1]
            assert results[0].aggregate_revision == 0
        else:
            loser = 1 - winner
            assert [result.status for result in results].count("accepted") == 1
            assert results[loser].status == "rejected"
            expected_error = "REVISION_CONFLICT" if kind == "claims" else "IDEMPOTENCY_CONFLICT"
            assert results[loser].error_code == expected_error
            if kind == "claims":
                assert [result.aggregate_revision for result in results] == [1, 1]
                assert [event.type for event in increment] == ["command.received", "task.claimed", "command.received", "command.rejected"]
                assert increment[-1].payload["error"]["context"] == {
                    "command_id": commands[loser].id, "target_id": "t-1",
                    "expected_revision": 0, "current_revision": 1,
                }
            else:
                assert results[loser].event_ids == ()
                assert results[loser].aggregate_revision is None
        if kind != "claims":
            assert [event.type for event in increment] == ["command.received", "task.created"]
        for command, result in zip(commands, results):
            # A conflicting new Command has no persisted Event batch.
            assert result.event_ids == tuple(event.id for event in increment if event.causation_id == command.id)
        projected = store.read_projection("p-1")
        assert projected == Projection.rebuild(events)
        state = projected["task:t-1"]
        if kind == "claims":
            assert (state["status"], state["owner_id"], state["revision"]) == ("assigned", commands[winner].actor_id, 1)
        else:
            assert (state["status"], state["owner_id"], state["revision"]) == ("pending", None, 0)
            assert state["title"] == commands[winner].payload["title"]
        row_snapshot = durable_rows(store)
        clear_projection_fixture(store, project_id="p-1")
        store.close()
        store = SQLiteStore.open(fixture.db_path)
        case.addCleanup(store.close)
        handler = CommandHandler(store)
        writes = store._ensure_open().total_changes
        for command, result in zip(commands, results):
            assert handler.handle(command, authenticated_actor_id=command.actor_id) == result
        rebuilt = store.read_projection("p-1")
        assert rebuilt == projected
        assert durable_rows(store) == row_snapshot
        assert store._ensure_open().total_changes == writes
        evidence = {
            "scenario": kind, "repetition": repetition, "parent_pid": os.getpid(),
            "db_path": fixture.db_path, "commands": [command.to_dict() for command in commands],
            "processes": observations, "results": [result.to_dict() for result in results],
            "event_count_before": expected_head, "event_count_after_race": len(events),
            "race_event_delta": len(increment), "race_events": [event.to_dict() for event in increment],
            "row_counts": {table: len(rows) for table, rows in row_snapshot.items()},
            "retry_event_delta": len(store.read_events("p-1")) - len(events),
            "reopened_retry_sql_write_delta": store._ensure_open().total_changes - writes,
            "durable_rows_sha256_before_retry": digest(row_snapshot),
            "durable_rows_sha256_after_retry": digest(durable_rows(store)),
            "incremental_projection_sha256": digest(projected),
            "replay_projection_sha256": digest(Projection.rebuild(events)),
            "cache_deleted_read_sha256": digest(rebuilt),
        }
        if kind == "claims":
            release = make_command(
                command_id="cmd-release", actor_id=commands[winner].actor_id,
                command_type="task.release", target_id="t-1", payload={},
                expected_revision=1, idempotency_key="release",
            )
            released = handler.handle(release, authenticated_actor_id=release.actor_id)
            assert (released.status, released.aggregate_revision) == ("accepted", 2)
            new_claim = make_command(
                command_id="cmd-reclaim", actor_id=commands[1 - winner].actor_id,
                command_type="task.claim", target_id="t-1", payload={},
                expected_revision=2, idempotency_key="new-reclaim-intent",
            )
            reclaimed = handler.handle(new_claim, authenticated_actor_id=new_claim.actor_id)
            assert (reclaimed.status, reclaimed.aggregate_revision) == ("accepted", 3)
            before_old_retries = durable_rows(store)
            for command, result in zip([*commands, release], [*results, released]):
                assert handler.handle(command, authenticated_actor_id=command.actor_id) == result
            assert durable_rows(store) == before_old_retries
            final_events = store.read_events("p-1")
            assert len(final_events) == 16
            assert [event.aggregate_revision for event in final_events if event.type.startswith("task.")] == [0, 1, 2, 3]
            final_state = store.read_projection("p-1")
            assert final_state == Projection.rebuild(final_events)
            assert final_state["task:t-1"]["owner_id"] == new_claim.actor_id
            assert final_state["task:t-1"]["revision"] == 3
            evidence["release_new_key_reclaim"] = {
                "release_command": release.to_dict(), "release_result": released.to_dict(),
                "new_claim": new_claim.to_dict(), "reclaim_result": reclaimed.to_dict(),
                "event_count": 16, "task_revisions": [0, 1, 2, 3],
                "old_intent_retry_event_delta": 0,
                "original_conflict_revision_after_revision_three": results[1 - winner].aggregate_revision,
                "projection_sha256": digest(final_state),
                "replay_sha256": digest(Projection.rebuild(final_events)),
            }
        return evidence
    finally:
        if not case.doCleanups():
            raise RuntimeError("probe fixture cleanup failed")


MUTATIONS = (
    ("foreign_result_identity", "src/aetp/core/idempotency.py",
     'if result.command_id != record["command_id"]:', 'if False:',
     "DurableIdempotencyTests.test_foreign_durable_result_identity_fails_closed"),
    ("digest_conflict", "src/aetp/core/idempotency.py",
     'if record["request_digest"] != digest:', 'if False:',
     "DurableIdempotencyTests.test_same_key_changed_content_or_identity_conflicts_without_writes"),
    ("trusted_actor_scope", "src/aetp/core/idempotency.py",
     'record = self.store.read_idempotency(scope)',
     'record = self.store.read_idempotency((scope[0], "a-1", scope[2]))',
     "IdempotencyLookupTests.test_lookup_scope_includes_project_trusted_actor_and_key"),
    ("canonical_context_binding", "src/aetp/core/idempotency.py",
     '    return command.digest()',
     '    from dataclasses import replace\n    return replace(command, correlation_id="ignored-context").digest()',
     "CanonicalDigestTests.test_every_immutable_command_field_binds_the_digest"),
    ("durable_revision_guard", "src/aetp/core/commands.py",
     'if command.expected_revision != snapshot.revision:', 'if False:',
     "ProcessCompetitionTests.test_two_process_claims_have_one_winner_and_durable_version_evidence"),
    ("atomic_batch_boundary", "src/aetp/core/commands.py",
     '            self.store.append_events(events)',
     '            self.store._ensure_open().commit()\n            self.store.append_events(events)',
     "DurableIdempotencyTests.test_result_failure_rolls_back_key_then_original_command_can_retry"),
)


def mutations():
    results = []
    temp_root = Path(tempfile.gettempdir()).resolve()
    for name, path, old, new, test in MUTATIONS:
        temp = tempfile.TemporaryDirectory(prefix="aetp-m004-mutant-", dir=temp_root)
        root = Path(temp.name).resolve()
        assert root.is_relative_to(temp_root) and root.name.startswith("aetp-m004-mutant-")
        try:
            shutil.copytree(ROOT / "src", root / "src", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (root / "tests").mkdir()
            shutil.copy2(ROOT / "tests/__init__.py", root / "tests/__init__.py")
            shutil.copytree(ROOT / "tests/m0", root / "tests/m0", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            source = (root / path).read_text(encoding="utf-8")
            assert source.count(old) == 1, (name, "mutation marker is not unique")
            (root / path).write_text(source.replace(old, new, 1), encoding="utf-8")
            env = os.environ.copy()
            env.update(PYTHONPATH=str(root / "src"), PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
            args = [sys.executable, "-m", "unittest", "tests.m0.test_idempotency_concurrency." + test, "-v"]
            started = datetime.now(timezone.utc).isoformat()
            run = subprocess.run(args, cwd=root, env=env, capture_output=True, text=True, encoding="utf-8", timeout=90)
            count = re.search(r"Ran (\d+) test", run.stderr)
            summary = re.search(r"FAILED \(([^)]+)\)", run.stderr)
            failures = re.search(r"failures=(\d+)", summary[1]) if summary else None
            errors = re.search(r"errors=(\d+)", summary[1]) if summary else None
            tests_run = int(count[1]) if count else 0
            failure_count = int(failures[1]) if failures else 0
            error_count = int(errors[1]) if errors else 0
            killed = run.returncode == 1 and tests_run == 1 and failure_count > 0 and error_count == 0
            results.append({
                "name": name, "path": path, "old": old, "new": new,
                "test": test, "command": "python " + " ".join(args[1:]),
                "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
                "exit_code": run.returncode, "tests_run": tests_run,
                "failures": failure_count, "errors": error_count, "killed": killed,
                "stdout": run.stdout, "stderr": run.stderr,
            })
        finally:
            # Only this freshly created, checked temporary tree is recursive-cleaned.
            assert root.is_relative_to(temp_root) and root.name.startswith("aetp-m004-mutant-")
            temp.cleanup()
    return {"mutations": results, "all_killed_by_assertion": all(result["killed"] for result in results)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("races", "mutations", "all"), default="all")
    parser.add_argument("--repetitions", type=int, default=5)
    options = parser.parse_args()
    if options.repetitions < 1:
        parser.error("repetitions must be positive")
    before = source_hashes()
    output = {"work_item": "M0-04", "started_at": datetime.now(timezone.utc).isoformat(), "source_sha256": before}
    if options.mode in ("races", "all"):
        output["races"] = [race(kind, repetition) for repetition in range(1, options.repetitions + 1) for kind in ("claims", "duplicate", "conflict")]
    if options.mode in ("mutations", "all"):
        output.update(mutations())
    output["canonical_sources_unchanged"] = source_hashes() == before
    output["finished_at"] = datetime.now(timezone.utc).isoformat()
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0 if output["canonical_sources_unchanged"] and output.get("all_killed_by_assertion", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
