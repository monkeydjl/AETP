"""Execute M0 fixtures and retain evidence without granting acceptance.

Repository-local tooling reuses test-only process/fault helpers, never installs
these into the product Command path. Every invocation owns a NEW database and
evidence directory. Existing paths are refused, not cleared or trusted.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import io
import json
import os
import socket
import subprocess
import sys
import unittest
import urllib.request
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

import aetp.core.runtime as runtime_module
from aetp.core.commands import CommandHandler
from aetp.core.projection import Projection
from aetp.core.runtime import RuntimeRecovery, SimulatedRuntime
from aetp.storage.sqlite_store import SQLiteStore
from tests.m0.support import (
    RuntimeHarness,
    kill_process_after_commit,
    make_command,
    persist_receipt_only_fixture,
    run_two_processes_against_same_sqlite_file,
)
from tests.m0.test_replay_recovery import effect_tripwires

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "Docs/AETP-设计方案.md §18.3"
CAPABILITIES = {
    "runtime": "deterministic simulation-only", "real_adapters": [],
    "model": False, "shell": False, "network": False,
    "runtime_start": False, "external_actions": False,
    "lease_binding": False, "approval": False,
    "review_verification": False, "bootstrap_acceptance": False,
}
_REQUIREMENTS = {
    "TEST-001": "同键同内容重试返回原结果，不重复提交领域 Event 批次",
    "TEST-002": "Agent 不得直接修改 State",
    "TEST-003": "Task 不得跳过 Review / Verification 进入 VERIFIED",
    "TEST-004": "未经 Approval 的高风险 Command 必须拒绝",
    "TEST-005": "删除 State Store 后重放 Event 得到一致状态",
    "TEST-006": "Agent 崩溃后 Task 可按 Lease 重新分配",
    "TEST-007": "Untrusted Input 不得直接授权 Command",
    "TEST-008": "Review 通过但 Verification 缺失不得 VERIFIED",
    "TEST-009": "有集成面任务未经 Integration Gate 不得 COMPLETED；豁免必须显式留痕",
    "TEST-010": "Mission Acceptance 失败不得 Delivery",
    "TEST-011": "Approval 过期后必须产生升级路径，不得静默悬挂",
    "TEST-012": "Orchestrator 重启后调度状态完整恢复",
    "TEST-013": "Agent 主动发起的协作与 Orchestrator 下发走同一条 Command 校验路径",
    "TEST-014": "工作副本不相互污染；声称安全隔离的 Provider 还须阻止越界访问",
    "TEST-015": "无 Manager 的 Agent 可直接发言、回复、质疑与提案；独立审查不要求接管被审 Task，无职级前置",
    "TEST-016": "伪造 actor 或冒用他人 Binding 不得取得执行权",
    "TEST-017": "提交 Event 后、返回响应前崩溃，恢复重试得到原结果且无重复效果",
    "TEST-018": "同幂等键异内容被拒绝；释放后用新键可合法再次认领",
    "TEST-019": "两个 Agent 基于同一旧版本认领，最多一个成功并保持 Lease / Binding 一致",
    "TEST-020": "外部结果 UNKNOWN 时查询 / 对账，不重复创建资源或发布",
    "TEST-021": "Replay 不执行模型、Shell、Runtime.start 或已确认的工具动作",
    "TEST-022": "新代次生效后旧执行可留档但不能推进 Task / 合并；已在途效果仍对账",
    "TEST-023": "审批后改变目标 / 参数被拒绝；Mission 审批绑定准则与交付快照",
    "TEST-024": "更换代码、测试集、环境或验收标准后旧验证不能自动放行；合并基线检查有效",
    "TEST-025": "PAUSED 继续记录在途事实而不派发；重启保持暂停，不把软暂停显示成彻底停止",
    "TEST-026": "绕过代理执行高风险操作被真实边界阻止；未具备能力不得宣称完整兼容",
    "TEST-027": "输入来源标记跨 Agent 转述保留；来源未知按不可信处理，普通讨论不要求审批",
    "TEST-028": "两个以上平等 Agent 从粗糙想法讨论方案并按方案交付，无 Manager 必经路径",
}
_CORE = {"TEST-001", "TEST-002", "TEST-005", "TEST-017", "TEST-018", "TEST-021"}
_PARTIAL = {
    "TEST-012": "Only read-only Command/Event recovery; full scheduling, Lease/epoch, Approval, Session/Binding, budgets and UNKNOWN reconciliation are absent.",
    "TEST-016": "Only trusted-entry actor mismatch is exercised; Binding impersonation and real execution authorization remain unimplemented.",
    "TEST-019": "Real two-process revision competition is exercised, but Lease/Binding consistency and fencing are not implemented.",
}
_DEFERRED = {
    "TEST-003": "M1: Review / Verification quality gates are absent.",
    "TEST-004": "M2: Approval and real high-risk enforcement are absent; unsupported Commands are not an Approval implementation.",
    "TEST-006": "M1: Lease crash reassignment is absent.",
    "TEST-007": "M2: end-to-end untrusted-input authorization is absent.",
    "TEST-008": "M1: independent Review / Verification entities are absent.",
    "TEST-009": "M3: Integration Gate and explicit exemption evidence are absent.",
    "TEST-010": "M3: Mission Acceptance and Delivery are absent.",
    "TEST-011": "M2-02: Approval expiry and escalation are absent; registration only.",
    "TEST-013": "M1: Agent collaboration/router and scheduler paths are absent.",
    "TEST-014": "M1: Workspace isolation and real Provider enforcement are absent.",
    "TEST-015": "M1: Message/dialogue and independent Review are absent; test-worker roles are not product Agent hierarchy.",
    "TEST-020": "Later execution scope: no external Action/UNKNOWN reconciliation.",
    "TEST-022": "M1+: no Lease epochs, late reports or in-flight external effects.",
    "TEST-023": "M2/M3: Approval snapshots and Mission snapshot binding are absent.",
    "TEST-024": "M3: Verification freshness and integration baselines are absent.",
    "TEST-025": "Later recovery scope: retaining a paused creation value is not operational pause/in-flight fact handling.",
    "TEST-026": "M1+: real execution and high-risk enforcement boundaries are absent.",
    "TEST-027": "M2: cross-Agent input provenance and trust handling are absent.",
    "TEST-028": "M3: full peer discussion/plan/delivery and Bootstrap Acceptance are absent.",
}
_SCOPE_LIMITS = {
    "TEST-002": "Library-visible Command/read interfaces only, not isolation from privileged host Python/SQLite access; raw-SQL fault injection is a trusted test facility, not an Agent path.",
    "TEST-017": "Internal atomic Command results only; no external exactly-once guarantee or repair of missing/corrupt durable result indexes.",
    "TEST-018": "M0 ownership/revision claim-release path only; no Lease or Binding guarantee.",
    "TEST-021": "Real M0 Replay with stdlib/simulator tripwires; model.invoke and Runtime.start are explicitly labelled absent-adapter sentinels, not real adapters or confirmed external Action history.",
}


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat()


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _display(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def _write_json(path: Path, value: Any) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as output:
        json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
        output.write("\n")


def _new_path(value: Any, label: str) -> Path:
    if not isinstance(value, (str, os.PathLike)):
        raise TypeError(f"{label} must be a filesystem path")
    text = os.fspath(value)
    if not isinstance(text, str):
        raise TypeError(f"{label} must not be bytes")
    if not text.strip() or text != text.strip() or text == ":memory:":
        raise ValueError(f"{label} must name a new persisted filesystem path")
    path = Path(text)
    if path.exists() or path.is_symlink():
        raise FileExistsError(f"refusing existing {label}: {path}")
    return path.resolve()


def _new_database_paths(value: Any) -> tuple[Path, ...]:
    database = _new_path(value, "database")
    # SQLite can inspect or delete these implicit files even for a new database.
    sidecars = tuple(
        _new_path(str(database) + suffix, f"SQLite {suffix} sidecar")
        for suffix in ("-journal", "-wal", "-shm")
    )
    return (database, *sidecars)


def _distinct_outputs(*paths: Path) -> None:
    for index, path in enumerate(paths):
        for other in paths[index + 1:]:
            if path == other or path.is_relative_to(other) or other.is_relative_to(path):
                raise ValueError(f"outputs must be distinct and non-nested: {path}, {other}")


class _CoreFixtures(unittest.TestCase):
    """Nine concrete fixtures; assertions remain active under python -O."""

    def __init__(self, methodName: str, db_path: Path):
        super().__init__(methodName)
        self.db_path = db_path
        self.test_id = "TEST-" + methodName.removeprefix("test_")
        self.project = "m0-" + self.test_id.lower()
        self.complete = False
        self.record: dict[str, Any] = {
            "test_id": self.test_id, "project_id": self.project,
            "database": _display(db_path), "runtime_capabilities": CAPABILITIES,
            "initial_events": [], "initial_state": {}, "commands": [],
            "fault_injection": [], "checks": [], "replay_state": None,
        }

    def setUp(self):
        self.store = SQLiteStore.open(str(self.db_path))
        self.addCleanup(self.store.close)
        self.handler = CommandHandler(self.store)
        RuntimeHarness(self.db_path, self.store, SimulatedRuntime()).seed_project(self.project)
        self.record["initial_events"] = self.events()
        self.record["initial_state"] = self.store.read_projection(self.project)
        self.initial_state = {
            f"project:{self.project}": {"id": self.project, "project_id": self.project, "revision": 0, "status": "planning"},
            "agent:a-1": {"id": "a-1", "project_id": self.project, "revision": 0, "model_id": "model-1", "status": "available"},
            "agent:a-2": {"id": "a-2", "project_id": self.project, "revision": 0, "model_id": "model-2", "status": "available"},
        }
        self.check("literal initial state", self.record["initial_state"], self.initial_state)
        self.check("initial receipt/domain count", len(self.record["initial_events"]), 6)

    def command(self, kind, key, revision=0, *, actor="a-1", payload=None):
        return make_command(
            command_id=f"{self.project}-{key}", project_id=self.project,
            actor_id=actor, command_type=kind, target_id="task",
            payload={} if payload is None else payload, expected_revision=revision,
            idempotency_key=key, correlation_id=f"{self.project}-{key}",
        )

    def input(self, command, actor=None, *, source="trusted conformance caller"):
        self.record["commands"].append({
            "source": source, "authenticated_actor_id": actor or command.actor_id,
            "command": command.to_dict(),
        })

    def submit(self, command, actor=None):
        self.input(command, actor)
        result = self.handler.handle(command, authenticated_actor_id=actor or command.actor_id)
        self.record["commands"][-1]["result"] = result.to_dict()
        return result

    def events(self):
        return [event.to_dict() for event in self.store.read_events(self.project)]

    def check(self, name, actual, expected):
        # Snapshot evidence before asserting, including a failing observation.
        self.record["checks"].append(json.loads(json.dumps({
            "name": name, "actual": actual, "expected": expected,
            "passed": actual == expected,
        }, ensure_ascii=False, allow_nan=False)))
        self.assertEqual(actual, expected, name)

    def task_state(self, revision=0, status="pending", owner=None):
        return {**self.initial_state, "task:task": {
            "id": "task", "project_id": self.project, "revision": revision,
            "title": "Conformance task", "status": status, "owner_id": owner,
        }}

    def create_task(self):
        command = self.command("task.create", "create", payload={"title": "Conformance task"})
        self.check("create accepted", self.submit(command).status, "accepted")
        return command

    def demo(self):
        command = self.create_task()
        self.check("claim accepted", self.submit(self.command("task.claim", "claim")).status, "accepted")
        self.check("release accepted", self.submit(self.command("task.release", "release", 1)).status, "accepted")
        return command

    def finish(self, expected, *, pending=None):
        recovery = RuntimeRecovery.open(str(self.db_path))
        try:
            state = recovery.rebuild_project(self.project)
            self.record["replay_state"] = state
            self.check("literal replay state", state, expected)
            self.check("pending facts", recovery.reconcile_pending(self.project), pending or [])
            self.check("no recovery simulation", recovery.runtime_invocation_count, 0)
        finally:
            recovery.close()
        self.record["final_events"] = self.events()
        self.complete = True

    def test_001(self):
        command = self.command("task.create", "create", payload={"title": "Conformance task"})
        original = self.submit(command)
        self.check("first accepted", original.status, "accepted")
        committed = self.events()
        self.record["fault_injection"].append({"kind": "duplicate delivery", "point": "after atomic commit; same immutable Command/key"})
        retry = self.submit(command)
        self.check("original result returned", retry.to_dict(), original.to_dict())
        self.check("complete Event stream unchanged", self.events(), committed)
        self.check("single domain effect", [event["type"] for event in committed[6:]], ["command.received", "task.created"])
        stale = self.command("task.claim", "stale", 99)
        rejected = self.submit(stale)
        self.check("stale rejected", rejected.error_code, "REVISION_CONFLICT")
        rejected_events = self.events()
        self.check("rejected retry is original", self.submit(stale).to_dict(), rejected.to_dict())
        self.check("no second rejected batch", self.events(), rejected_events)
        self.finish(self.task_state())

    def test_002(self):
        command = self.create_task()
        committed = self.events()
        detached = self.store.read_projection(self.project)
        self.record["fault_injection"].append({"kind": "untrusted local mutation", "point": "returned read view and immutable Command payload; not privileged host SQL"})
        detached["task:task"]["status"] = "completed"
        detached["agent:a-1"]["model_id"] = "attacker"
        self.check("read mutation is not State", self.store.read_projection(self.project), self.task_state())
        self.check("read mutation creates no facts", self.events(), committed)
        with self.assertRaises(TypeError):
            command.payload["title"] = "rewritten"
        self.check("Command history remains immutable", command.payload["title"], "Conformance task")
        complete = self.submit(self.command("task.complete", "bypass-quality"))
        self.check("unsupported direct completion rejected", complete.error_code, "UNSUPPORTED_COMMAND")
        self.check("no completed fact", sum(event["type"] == "task.completed" for event in self.events()), 0)
        self.finish(self.task_state())

    def test_005(self):
        self.demo()
        expected = self.task_state(2)
        self.check("pre-delete literal State", self.store.read_projection(self.project), expected)
        self.record["fault_injection"].append({"kind": "trusted storage fault", "point": "DROP disposable projections and projection_meta tables after commit"})
        connection = self.store._ensure_open()
        connection.execute("DROP TABLE projections")
        connection.execute("DROP TABLE projection_meta")
        self.finish(expected)
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.check("read-only replay did not recreate State tables", sorted(tables & {"projections", "projection_meta"}), [])

    def test_012(self):
        self.create_task()
        pending = self.command("task.claim", "receipt-only")
        self.input(pending, source="artificial receipt-only storage fault, NOT a normal atomic Handler window")
        persist_receipt_only_fixture(self.store, pending)
        self.record["fault_injection"].append({"kind": "artificial receipt-only plus restart", "point": "durable recorded intent without terminal fact; not external UNKNOWN or an executable queue"})
        committed = self.events()
        restarts = []
        for _ in range(2):
            recovery = RuntimeRecovery.open(str(self.db_path))
            try:
                restarts.append({"state": recovery.rebuild_project(self.project), "pending": recovery.reconcile_pending(self.project), "simulation_calls": recovery.runtime_invocation_count})
            finally:
                recovery.close()
        self.record["restarts"] = restarts
        self.check("fresh recovery repeats only durable facts", restarts, [{"state": self.task_state(), "pending": [pending.id], "simulation_calls": 0}] * 2)
        self.check("recovery writes no Events", self.events(), committed)
        self.finish(self.task_state(), pending=[pending.id])

    def test_016(self):
        command = self.command("task.create", "forged", payload={"title": "Conformance task"})
        before = self.events()
        self.record["fault_injection"].append({"kind": "forged actor", "point": "a-2 authenticated connection claims a-1, before idempotency reservation"})
        result = self.submit(command, "a-2")
        self.check("actor mismatch refused", result.error_code, "ACTOR_MISMATCH")
        self.check("forgery cannot submit protocol facts", self.events(), before)
        self.check("forgery cannot reserve key", self.store.read_idempotency((self.project, "a-2", command.idempotency_key)), None)
        audit = [row for row in self.store.read_security_audit(authenticated_actor_id="a-2") if row["command_id"] == command.id]
        self.record["security_audit"] = audit
        self.check("trusted security audit", [(row["claimed_actor_id"], row["authenticated_actor_id"], row["error_code"]) for row in audit], [("a-1", "a-2", "ACTOR_MISMATCH")])
        self.check("legitimate caller still accepted", self.submit(command, "a-1").status, "accepted")
        self.finish(self.task_state())

    def test_017(self):
        command = self.command("task.create", "crash", payload={"title": "Conformance task"})
        self.input(command, source="owned spawned worker; commit witness is NOT a delivered client response")
        original, witness = kill_process_after_commit(str(self.db_path), command)
        self.record["process_death"] = witness
        self.record["fault_injection"].append({"kind": "real process termination", "point": witness["boundary"], "pid": witness["pid"], "exit_code": witness["exit_code"]})
        self.check("committed result accepted", original.status, "accepted")
        self.check("separate process", witness["pid"] != os.getpid(), True)
        self.check("worker actually terminated", witness["exit_code"] not in (None, 0), True)
        self.check("commit-before-response boundary", witness["boundary"], "committed_before_client_response")
        self.store.close()
        self.store = SQLiteStore.open(str(self.db_path))
        self.addCleanup(self.store.close)
        self.handler = CommandHandler(self.store)
        committed = self.events()
        self.check("durable single batch after death", [event["type"] for event in committed[6:]], ["command.received", "task.created"])
        self.check("fresh retry returns original", self.submit(command).to_dict(), original.to_dict())
        self.check("fresh retry adds no effects", self.events(), committed)
        self.finish(self.task_state())

    def test_018(self):
        self.create_task()
        claim = self.command("task.claim", "claim")
        original_claim = self.submit(claim)
        self.check("initial claim accepted", original_claim.status, "accepted")
        claimed = self.events()
        self.record["fault_injection"].append({"kind": "same-key content conflict and delayed old Commands", "point": "before and after real release/new-key reclaim"})
        changed = replace(claim, id=claim.id + "-changed", payload={"note": "different content"})
        self.check("same-key changed content refused", self.submit(changed).error_code, "IDEMPOTENCY_CONFLICT")
        self.check("conflict leaves batch unchanged", self.events(), claimed)
        release = self.command("task.release", "release", 1)
        original_release = self.submit(release)
        self.check("real owner release accepted", original_release.status, "accepted")
        self.check("release really requeues", self.store.read_projection(self.project), self.task_state(2))
        released = self.events()
        self.check("old claim retains old result", self.submit(claim).to_dict(), original_claim.to_dict())
        self.check("old claim cannot reassign", self.events(), released)
        reclaim = self.command("task.claim", "new-claim", 2)
        result = self.submit(reclaim)
        self.check("new key and current revision can reclaim", [result.status, result.aggregate_revision], ["accepted", 3])
        reclaimed = self.events()
        self.check("old release retains old result", self.submit(release).to_dict(), original_release.to_dict())
        self.check("old release cannot revoke new ownership", self.events(), reclaimed)
        self.check("literal domain sequence", [event["type"] for event in reclaimed[6:] if event["type"] != "command.received"], ["task.created", "task.claimed", "task.requeued", "task.claimed"])
        self.finish(self.task_state(3, "assigned", "a-1"))

    def test_019(self):
        self.create_task()
        commands = [self.command("task.claim", "claim-" + actor, actor=actor) for actor in ("a-1", "a-2")]
        for command in commands:
            self.input(command, source="distinct trusted spawned worker, independent connection")
        observations = []
        results = run_two_processes_against_same_sqlite_file(str(self.db_path), commands, observations=observations)
        self.record["process_competition"] = observations
        self.record["fault_injection"].append({"kind": "two-process stale revision race", "point": "both read head 8/revision 0 before barrier release; SQLite final commit arbitrates"})
        self.check("distinct child processes", len({row["pid"] for row in observations} - {os.getpid()}), 2)
        self.check("both observed same durable version", [row["observed_head_sequence"] for row in observations], [8, 8])
        self.check("workers reaped successfully", [row["exit_code"] for row in observations], [0, 0])
        self.check("one winner", sorted(result.status for result in results), ["accepted", "rejected"])
        winner = next(index for index, result in enumerate(results) if result.status == "accepted")
        self.check("loser rejected at current revision", [results[1 - winner].error_code, results[1 - winner].aggregate_revision], ["REVISION_CONFLICT", 1])
        self.check("one claimed domain fact", sum(event["type"] == "task.claimed" for event in self.events()), 1)
        committed = self.events()
        for command, result in zip(commands, results):
            self.check("race retry preserves original result", self.submit(command).to_dict(), result.to_dict())
        self.check("race retries preserve whole stream", self.events(), committed)
        self.finish(self.task_state(1, "assigned", commands[winner].actor_id))

    def test_021(self):
        command = self.demo()
        simulation = SimulatedRuntime()
        observation = simulation.execute(command)
        self.check("real simulator counter positive control", simulation.invocation_count, 1)
        self.check("simulation not a protocol ACK", observation.to_dict()["source"], "simulation-only")
        recovery = RuntimeRecovery.open(str(self.db_path))
        self.addCleanup(recovery.close)
        self.record["fault_injection"].append({"kind": "isolated Replay mutants", "point": "inject each forbidden call into actual Projection.rebuild reached by RuntimeRecovery; traps reject before any external effect"})
        # Invalid stdlib arguments stay harmless even if an instrument is broken.
        # Absent-adapter sentinels are labelled separately, not real adapters.
        calls = {
            "simulation.execute": lambda: recovery._runtime.execute(None),
            "shell.Popen": lambda: subprocess.Popen(None),
            "shell.system": lambda: os.system(None),
            "network.socket": lambda: socket.socket("not-a-family"),
            "network.urlopen": lambda: urllib.request.urlopen(None),
            "runtime.start_sentinel": lambda: recovery._runtime.start(),
            "model.invoke_sentinel": lambda: runtime_module.invoke_model(),
        }
        controls = []
        real_rebuild = Projection.rebuild
        with effect_tripwires() as spies:
            for label, call in calls.items():
                def forbidden_rebuild(events, invoke=call):
                    invoke()
                    return real_rebuild(events)
                with patch.object(Projection, "rebuild", forbidden_rebuild):
                    with self.assertRaisesRegex(AssertionError, "forbidden recovery effect"):
                        recovery.rebuild_project(self.project)
                self.check("live Replay trap: " + label, spies[label].call_count, 1)
                controls.append({"label": label, "detected_in_replay": True, "kind": "absent-adapter sentinel" if label.endswith("sentinel") else "real M0/stdlib boundary"})
                spies[label].reset_mock()
            self.record["tripwire_controls"] = controls
            self.finish(self.task_state(2))
            counts = {label: spy.call_count for label, spy in spies.items()}
            self.record["replay_forbidden_call_counts"] = counts
            self.check("unmodified Replay has zero calls", counts, dict.fromkeys(calls, 0))


def _execute(test_id: str, db_path: Path, directory: Path) -> dict[str, Any]:
    case = _CoreFixtures("test_" + test_id.removeprefix("TEST-"), db_path)
    stream = io.StringIO()
    started = _now()
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.TestSuite([case]))
    execution = {
        "status": "failed", "started_at": started, "finished_at": _now(),
        "tests_run": result.testsRun, "failures": len(result.failures),
        "errors": len(result.errors), "skipped": len(result.skipped),
        "expected_failures": len(result.expectedFailures),
        "unexpected_successes": len(result.unexpectedSuccesses),
        "fixture_complete": case.complete,
    }
    valid = (
        result.testsRun == 1 and result.wasSuccessful()
        and not result.skipped and not result.expectedFailures
        and not result.unexpectedSuccesses and case.complete
        and bool(case.record["commands"]) and bool(case.record["fault_injection"])
        and bool(case.record["checks"]) and all(check["passed"] for check in case.record["checks"])
        and case.record["replay_state"] is not None
    )
    if valid:
        execution["status"] = "passed"
    else:
        stream.write("\nConformance execution failed or incomplete: no pass from skips, xfails, empty/no-op fixtures or errors.\n")
    log_path = directory / f"{test_id}.txt"
    with log_path.open("x", encoding="utf-8", newline="\n") as output:
        output.write(stream.getvalue())
    observation_path = directory / f"{test_id}.json"
    _write_json(observation_path, {**case.record, "execution": execution})
    return {
        "execution": execution,
        "fixture": f"conformance.m0.runner._CoreFixtures.test_{test_id[-3:]}",
        "evidence": _display(observation_path), "evidence_sha256": _sha(observation_path),
        "raw_output": _display(log_path), "raw_output_sha256": _sha(log_path),
        "evidence_kind": "executed fixture observations and raw unittest output",
    }


def run_m0_conformance(db_path: str, *, evidence_dir: str | Path | None = None) -> dict:
    """Return 28 requirements; actually run nine applicable M0 fixtures.

    `passed` is limited to the declared M0 capabilities. Partial cases stay
    `pending` after successful execution, but become `failed` on failure.
    Scope registrations never run or count as passes.
    """
    database_paths = _new_database_paths(db_path)
    database = database_paths[0]
    directory = _new_path(evidence_dir if evidence_dir is not None else str(database) + ".evidence", "evidence directory")
    _distinct_outputs(*database_paths, directory)
    database.parent.mkdir(parents=True, exist_ok=True)
    directory.mkdir(parents=True, exist_ok=False)
    with database.open("xb"):
        pass  # Exclusive ownership; no existing database can be initialized.
    report = {}
    for test_id, requirement in _REQUIREMENTS.items():
        entry: dict[str, Any] = {
            "requirement": requirement, "source": SOURCE, "status": "not_applicable",
            "scope": "later milestone; no executed M0 guarantee", "limitations": [],
        }
        if test_id in _CORE or test_id in _PARTIAL:
            entry.update(_execute(test_id, database, directory))
            entry["scope"] = "partial M0 behavior only" if test_id in _PARTIAL else "M0 Core Kernel only; not full Runtime compatibility"
            entry["limitations"] = [_PARTIAL[test_id]] if test_id in _PARTIAL else [_SCOPE_LIMITS.get(test_id, "No real Runtime adapters, external effects or Bootstrap acceptance are claimed.")]
            entry["status"] = "failed" if entry["execution"]["status"] == "failed" else "pending" if test_id in _PARTIAL else "passed"
        else:
            reason = _DEFERRED[test_id]
            entry["limitations"] = [reason]
            statement = directory / f"{test_id}.json"
            _write_json(statement, {"test_id": test_id, "requirement": requirement, "status": "not_applicable", "reason": reason, "execution": "not_run", "runtime_capabilities": CAPABILITIES})
            entry.update({
                "execution": {"status": "not_run", "tests_run": 0}, "fixture": None,
                "evidence": _display(statement), "evidence_sha256": _sha(statement),
                "raw_output": None, "raw_output_sha256": None,
                "evidence_kind": "scope registration only, NOT execution evidence",
            })
        report[test_id] = entry
    return report


def _source_hashes() -> dict[str, str]:
    paths = set((ROOT / "src" / "aetp").rglob("*.py"))
    paths.update(ROOT / path for path in [
        "conformance/__init__.py", "conformance/m0/__init__.py", "conformance/m0/runner.py",
        "conformance/m0/README.md", "tests/m0/support.py", "tests/m0/test_replay_recovery.py",
        "tests/m0/test_conformance_subset.py", "Docs/AETP-设计方案.md",
    ])
    return {_display(path): _sha(path) for path in sorted(paths)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, help="new SQLite fixture file; never an existing product database")
    parser.add_argument("--json", required=True, help="new JSON execution report; never overwrites evidence")
    arguments = parser.parse_args(argv)
    try:
        output = _new_path(arguments.json, "report")
        database_paths = _new_database_paths(arguments.db)
        database = database_paths[0]
        directory = _new_path(output.with_suffix(".evidence"), "evidence directory")
        _distinct_outputs(*database_paths, output, directory)
        started = _now()
        sources = _source_hashes()
        tests = run_m0_conformance(str(database), evidence_dir=directory)
        source_unchanged = sources == _source_hashes()
        counts = Counter(entry["status"] for entry in tests.values())
        execution_counts = Counter(entry["execution"]["status"] for entry in tests.values())
        successful = not counts["failed"] and source_unchanged
        report = {
            "schema_version": "aetp-m0-conformance-0.1", "work_item": "M0-06",
            "scope": "m0-core-only", "status": "executed" if successful else "failed",
            "started_at": started, "finished_at": _now(), "python": sys.version,
            "command": [sys.executable, "-m", "conformance.m0.runner", "--db", arguments.db, "--json", arguments.json],
            "counts": {key: counts[key] for key in ("passed", "failed", "pending", "not_applicable")},
            "execution_counts": {key: execution_counts[key] for key in ("passed", "failed", "not_run")},
            "claims": {"full_aetp_compatible": False, "work_item_accepted": False, "task_completed": False},
            "bootstrap_status": "not_started", "review": {"status": "pending", "reviewer": None},
            "runtime_capabilities": CAPABILITIES, "source_sha256": sources,
            "source_unchanged_during_run": source_unchanged,
            "database": {"path": _display(database), "sha256": _sha(database)},
            "tests": tests,
        }
        output.parent.mkdir(parents=True, exist_ok=True)
        _write_json(output, report)
        print(f"M0-only execution: {dict(report['counts'])}; independent acceptance pending; full compatibility and Bootstrap unclaimed.")
        print(f"report: {_display(output)}")
        return 0 if successful else 1
    except (OSError, TypeError, ValueError) as exc:
        print(f"Conformance run refused/failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
