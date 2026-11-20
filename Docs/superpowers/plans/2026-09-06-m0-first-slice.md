# M0 Core Kernel First Slice Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在无危险外部效果的模拟 Runtime 中贯通 AETP 五核心对象与 `Command → Event Store → Projection` 事实链，验证版本、幂等、重启和纯 Replay。

**Architecture:** 使用 Python + SQLite 的 headless Core Kernel。Command Handler 在一个 SQLite 事务中校验受信 actor、目标版本和幂等键，提交不可变 Event 批次；Projection 只消费 Event；Orchestrator 只从持久化记录重建调度状态。M0 不接真实模型、Shell、Workspace、网络发布或 A2A。

**Tech Stack:** Python 3.11+（当前环境实测 Python 3.14.6）、SQLite、`unittest`；依赖保持标准库，避免在依赖未锁定前冻结 FastAPI/WebSocket 版本。

**Spec:** `Docs/AETP-设计方案.md` §§4.2、7.2–7.3、10.4、13.4、13.10、14.1–14.2、17.2、18.3；开发约定见 `AGENTS.md`；工作项见 `Docs/development/backlog.json`。

**Preparation errata (2026-09-07):** Test discovery, fixture setup, file scopes and future evidence paths were reconciled during PREP-006 review. This is still an unexecuted plan, not M0 implementation evidence.

**Preparation errata (2026-09-08):** `read_events` returns the complete Event stream, including `command.received` required by §14.1. Planned assertions distinguish the single domain effect from receipt events and compare the complete stream before/after a same-Command retry. Preparation countermodels are not product RED/GREEN.

## Global Constraints

- 保持用户基本设定：至少两个平等、独立 Agent 可以直接交流、讨论、质疑和提案；没有 Manager 必经路径。
- M0 只实现 `Project / Agent / Task / Command / Event`；Message、Artifact、Review、Verification 和真实执行边界留到 M1。
- 从第一天遵守 `Command → Event Store → Projection`；Agent 不直接写 State，Agent 不直接产生 Event。
- Event 历史不可变，`sequence` 只能由 Sequencer 赋值；Projection 删除后必须可从 Event Store 重建。
- 幂等作用域是 `(project_id, authenticated_actor_id, idempotency_key)`；同键异内容拒绝。
- 外部效果完全禁用；Replay 不执行模型、Shell、Runtime.start 或任何工具调用。
- 没有 Review/Verification 时，不得宣称 Task 合规 `COMPLETED`，不得写 `BOOTSTRAP_VERIFIED`。
- 测试先行：每个行为先写一个会因目标行为缺失而失败的测试，记录 RED，再写最小实现并记录 GREEN。
- 当前仓库没有 Git 元数据；不把 commit 步骤伪装成已完成，提交由有权限的协作者另行处理。

---

## 文件边界

```text
src/aetp/
  __init__.py                 包版本与公开入口
  domain/models.py            五核心对象的不可变/可序列化模型
  storage/sqlite_store.py     SQLite schema、事务、不可变 Event 与幂等记录
  core/commands.py            Command 类型、规范化摘要、Handler
  core/projection.py          Event → State Projection
  core/idempotency.py         Durable deduplication and canonical command digests
  core/runtime.py             无外部效果的模拟 Runtime 与恢复入口
schemas/m0/                   valid/invalid fixture
conformance/m0/               M0 适用 TEST 的运行入口和报告

tests/__init__.py             Explicit unittest package
tests/m0/
  __init__.py
  test_models.py
  test_command_boundary.py
  test_event_projection.py
  test_idempotency_concurrency.py
  test_replay_recovery.py
  test_conformance_subset.py
  support.py                 测试夹具与故障注入辅助，不进入生产包
```

Task 1 先定义共享模型与存储字段契约；每个后续任务在对应的 Interfaces 段先定义自己的公开接口，后续步骤只消费已经定义的接口，不临时改变字段名。SQLite 是实现细节，测试通过接口和可观察结果断言，不依赖私有表布局。

## Fixture and test-discovery contract

All Python blocks below are **planned test skeletons**, not evidence of executed tests. Each test is a `unittest.TestCase` method; no pytest dependency or collection adapter is assumed. Implement the named helper in the owning task before running that task's RED check. Import errors, missing fixtures, `Ran 0 tests`, skips and expected failures are not evidence that the target behavior was exercised.

Before any M0 execution, verify PREP-008 is `done` and obtain implementation authorization. In the M0 command shell, save `$m0PreviousPythonPath = $env:PYTHONPATH` and set `$env:PYTHONPATH = (Join-Path $PWD 'src')`; restore `$env:PYTHONPATH = $m0PreviousPythonPath` after the session. This is process-local import configuration, not dependency installation or a change to user/system configuration. Create the package markers listed in Task 1; run discovery with `-t .` from the repository root.

For a newly introduced interface, first establish the imports and fixture setup, then retain an assertion failure for missing target behavior as RED. Record the failing test ID, failure output and count. GREEN requires exit 0 **and all named target test IDs actually executed**: the skeleton minima for Tasks 1..6 are 1, 2, 1, 2, 2 and 1 cases (9 total), without skips/expected failures. Add the remaining failure fixtures named by each task's acceptance; these skeleton minima are not sufficient for full task acceptance.

The following are test-only interfaces in `tests/m0/support.py`, not new production APIs:

- Task 1: `new_test_db_path(testcase: unittest.TestCase) -> str` creates a `TemporaryDirectory`, registers its cleanup with `testcase.addCleanup` and returns an isolated SQLite file path.
- Task 2: `make_task_create_command(*, actor_id="a-1", idempotency_key="k-1", expected_revision=0) -> Command` creates a new `task.create` intent for absent `t-1` in `p-1`.
- Task 2: `open_command_fixture(testcase: unittest.TestCase) -> CommandFixture` creates that temporary DB, opens `SQLiteStore`, registers `store.close` after directory cleanup (LIFO), constructs `CommandHandler(store)`, and seeds project `p-1` and Agents `a-1`/`a-2` **through validated Commands with a trusted bootstrap caller**, never by writing domain State or fabricating Events. It returns explicit `db_path`, `store`, `handler`, and `after_sequence` fields. `after_sequence` is the last seed Event sequence; no Task has been created yet. Count task effects after this baseline, not all project/Agent seed Events.
- Task 3: `clear_projection_fixture(store: SQLiteStore, project_id="p-1") -> None` clears only the test Projection, never Commands/Event history. No arbitrary State deletion API is added to production.
- Task 4: `make_claim_commands(*, task_id: str, expected_revision: int) -> tuple[Command, Command]` creates distinct-key claims by the two seeded Agents for the same revision. `run_two_processes_against_same_sqlite_file(db_path: str, commands) -> list[CommandResult]` opens that **same persisted file** in two separate Python worker processes, synchronizes their start, collects both outcomes and process IDs, and joins/closes workers before cleanup. A process-local lock is not the correctness boundary.
- Task 5: `RuntimeHarness.open(db_path: str) -> RuntimeHarness` seeds the same validated prerequisites only for a new DB and owns the simulated runtime/store. It exposes `run_demo_flow(project_id) -> dict[str, dict]`, `commit_then_drop_response(command) -> CommandResult`, `handle(command) -> CommandResult`, `domain_event_count(project_id) -> int`, and idempotent `close()`. The drop-response helper captures the committed result at the fault-injection boundary for assertion while simulating its loss to the client. It does not create a second intent or an external effect.

All resource cleanup is explicit and Windows-safe. Task-specific additions to `support.py` are sequential changes listed in both this plan and the backlog; they are not disjoint concurrent write sets.

## Evidence and write-scope contract

`backlog.json` is the canonical development work-item list. Task N below implements `M0-0N`; its **Files** list must match that item's planned write set. Shared storage/support files are changed sequentially according to dependencies, not concurrently claimed.

Future **product test evidence** is recorded under `artifacts/`, using the exact paths in each item's `evidence` field. PREP review and static inspection records remain under `Docs/development/evidence/`. These future report paths do not exist merely because the plan names them, and no product status changes during this preparation errata.

## Task 1: 五核心对象与持久化 schema

**Files:**
- Create: `src/aetp/__init__.py`
- Create: `src/aetp/domain/__init__.py`
- Create: `src/aetp/domain/models.py`
- Create: `src/aetp/storage/__init__.py`
- Create: `src/aetp/storage/sqlite_store.py`
- Create: `src/aetp/core/__init__.py`
- Create: `tests/__init__.py`
- Create: `tests/m0/__init__.py`
- Create: `tests/m0/support.py` (Task 1 helper only)
- Create: `tests/m0/test_models.py`
- Create: `schemas/m0/valid/*.json`
- Create: `schemas/m0/invalid/*.json`
- Record: `artifacts/m0-01-test-report.json`

**Interfaces:**
- `Project(id: str, revision: int, status: str)`、`Agent(id: str, project_id: str, model_id: str, status: str)`、`Task(id: str, project_id: str, title: str, status: str, revision: int)`、`Command(id: str, project_id: str, actor_id: str, type: str, target_id: str | None, payload: dict, expected_revision: int | None, idempotency_key: str, correlation_id: str)`、`Event(id: str, project_id: str, sequence: int, type: str, aggregate_type: str, aggregate_id: str, aggregate_revision: int, causation_id: str, correlation_id: str, payload: dict)`。
- `SQLiteStore.open(path: str) -> SQLiteStore`；`SQLiteStore.transaction() -> context manager`；`SQLiteStore.append_command(command: Command) -> None`；`SQLiteStore.append_events(events: list[Event]) -> None`；`SQLiteStore.read_events(project_id: str, after_sequence: int = 0) -> list[Event]`；`SQLiteStore.read_idempotency(scope: tuple[str, str, str]) -> dict | None`。
- `SQLiteStore.close() -> None` is idempotent and releases DB resources before temporary-directory cleanup.
- Model serialization must produce stable JSON with sorted object keys; timestamps are supplied by caller as ISO-8601 strings rather than generated during Replay.

- [ ] **Step 1: Write the failing test**

```python
import unittest

from aetp.domain.models import Command


class ModelTests(unittest.TestCase):
    def test_command_serializes_with_stable_required_fields(self):
        command = Command("c-1", "p-1", "a-1", "task.create", None, {"title": "demo"}, 0, "k-1", "corr-1")
        self.assertEqual(command.to_dict()["idempotency_key"], "k-1")
        self.assertEqual(command.to_json(), '{"actor_id":"a-1","correlation_id":"corr-1","expected_revision":0,"id":"c-1","idempotency_key":"k-1","payload":{"title":"demo"},"project_id":"p-1","target_id":null,"type":"task.create"}')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests/m0/test_models.py -v`
Expected: after import/fixture scaffolding is ready, `ModelTests.test_command_serializes_with_stable_required_fields` fails an assertion for missing or unstable serialization. An import error alone is not behavioral RED.

- [ ] **Step 3: Write the minimal models and SQLite schema**

Use frozen dataclasses, explicit enum-like string validation, JSON serialization with `sort_keys=True` and compact separators, and SQLite tables for `commands`, `events`, `idempotency`, and `projection_meta`. Define unique constraints for `(project_id, sequence)` and the idempotency scope plus request digest. Do not add a direct State write API.

- [ ] **Step 4: Run the model tests and schema fixture checks**

Run: `python -m unittest tests/m0/test_models.py -v`
Expected: PASS; malformed fixture tests reject missing IDs, unsupported types, negative revisions, and empty idempotency keys.

- [ ] **Step 5: Record evidence**

Write command, exit code, Python version, fixture paths and reviewer field to `artifacts/m0-01-test-report.json`; status remains `review` until a different Agent checks it.

## Task 2: Command Handler and atomic Event submission

**Files:**
- Create: `src/aetp/core/commands.py`
- Create: `tests/m0/test_command_boundary.py`
- Modify: `src/aetp/storage/sqlite_store.py`
- Modify: `tests/m0/support.py` (Command fixtures)
- Record: `artifacts/m0-02-test-report.json`

**Interfaces:**
- `CommandHandler(store: SQLiteStore).handle(command: Command, *, authenticated_actor_id: str) -> CommandResult`.
- `CommandResult(status: str, command_id: str, event_ids: tuple[str, ...], aggregate_revision: int | None, error_code: str | None)`.
- Supported M0 command types: `project.create` (target absent), `agent.register`, `task.create`, `task.claim`, `task.release`.
- `CommandHandler` receives `authenticated_actor_id: str` from its caller; it does not trust an actor string supplied by untrusted payload.

- [ ] **Step 1: Write the failing tests**

```python
import unittest

from tests.m0.support import make_task_create_command, open_command_fixture


class CommandBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = open_command_fixture(self)

    def test_task_create_commits_event_before_projection_is_read(self):
        result = self.fixture.handler.handle(make_task_create_command(), authenticated_actor_id="a-1")
        self.assertEqual(result.status, "accepted")
        events = self.fixture.store.read_events("p-1", after_sequence=self.fixture.after_sequence)
        event_types = [event.type for event in events]
        self.assertIn("command.received", event_types)
        self.assertEqual([kind for kind in event_types if kind == "task.created"], ["task.created"])

    def test_actor_mismatch_is_rejected_without_domain_event(self):
        result = self.fixture.handler.handle(make_task_create_command(actor_id="a-claimed"), authenticated_actor_id="a-real")
        self.assertEqual(result.error_code, "ACTOR_MISMATCH")
        self.assertEqual(self.fixture.store.read_events("p-1", after_sequence=self.fixture.after_sequence), [])
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests/m0/test_command_boundary.py -v`
Expected: FAIL because `CommandHandler` and `CommandResult` are not implemented.

- [ ] **Step 3: Implement the minimal transaction path**

Normalize the Command, compute a request digest, authenticate the actor, validate target/revision/state, insert the immutable received command and domain Event batch in one transaction, and return the stored result. Rejected commands preserve a rejection record but never create a domain state Event. An Agent may propose or claim directly; no Manager check is added.

- [ ] **Step 4: Run GREEN and mutation checks**

Run: `python -m unittest tests/m0/test_command_boundary.py -v`
Expected: PASS. Mutate actor binding, expected revision, target type, and transaction order one at a time; at least one test must fail for each mutation.

- [ ] **Step 5: Record evidence**

Write `artifacts/m0-02-test-report.json` with test output, rejected-command fixture and event count. Keep the work item in `review` pending independent review.

## Task 3: Event Sequencer and State Projection

**Files:**
- Create: `src/aetp/core/projection.py`
- Create: `tests/m0/test_event_projection.py`
- Modify: `src/aetp/storage/sqlite_store.py`
- Modify: `tests/m0/support.py` (Projection cleanup fixture)
- Record: `artifacts/m0-03-test-report.json`

**Interfaces:**
- `Projection.apply(event: Event) -> None`.
- `Projection.rebuild(events: Iterable[Event]) -> dict[str, dict]`.
- `SQLiteStore.next_sequence(project_id: str) -> int` is called only inside the append transaction; Runtime code cannot provide a sequence.
- `SQLiteStore.read_projection(project_id: str) -> dict[str, dict]` is read-only.

- [ ] **Step 1: Write the failing replay test**

```python
import unittest

from aetp.core.projection import Projection
from tests.m0.support import clear_projection_fixture, make_task_create_command, open_command_fixture


class EventProjectionTests(unittest.TestCase):
    def setUp(self):
        self.fixture = open_command_fixture(self)

    def test_rebuild_from_events_equals_incremental_projection(self):
        result = self.fixture.handler.handle(make_task_create_command(), authenticated_actor_id="a-1")
        self.assertEqual(result.status, "accepted")
        events = self.fixture.store.read_events("p-1")
        self.assertTrue(any(event.type == "task.created" for event in events))
        incremental = self.fixture.store.read_projection("p-1")
        clear_projection_fixture(self.fixture.store, project_id="p-1")
        rebuilt = Projection.rebuild(events)
        self.assertEqual(rebuilt, incremental)
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests/m0/test_event_projection.py -v`
Expected: FAIL because `Projection` and projection storage are not implemented.

- [ ] **Step 3: Implement projection and sequencing**

Apply only known Event types, reject duplicate sequence or aggregate revision gaps, and rebuild by ascending sequence. The test-only cleanup helper lives under test utilities, not as a production lifecycle method; production exposes no arbitrary State mutation.

- [ ] **Step 4: Run GREEN**

Run: `python -m unittest tests/m0/test_event_projection.py -v`
Expected: PASS with identical state before and after projection deletion/rebuild.

- [ ] **Step 5: Record evidence**

Write `artifacts/m0-03-test-report.json` including the sequence list, replay hash and invalid-gap result.

## Task 4: Idempotency, revision conflict and concurrent claim

**Files:**
- Create: `src/aetp/core/idempotency.py`
- Create: `tests/m0/test_idempotency_concurrency.py`
- Modify: `src/aetp/core/commands.py`
- Modify: `tests/m0/support.py` (two-process claim fixtures)
- Record: `artifacts/m0-04-test-report.json`

**Interfaces:**
- `canonical_digest(command: Command) -> str`.
- `IdempotencyResult.lookup(scope, digest) -> CommandResult | None`.
- `CommandHandler(store: SQLiteStore)` binds the store used by the validated bootstrap/test fixtures.
- `CommandHandler.handle` must return the original result for a repeated same-key/same-content command and `IDEMPOTENCY_CONFLICT` for same-key/different-content.

- [ ] **Step 1: Write the failing tests**

```python
import unittest

from tests.m0.support import (
    make_claim_commands, make_task_create_command, open_command_fixture,
    run_two_processes_against_same_sqlite_file,
)


class IdempotencyConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = open_command_fixture(self)

    def test_same_key_same_content_returns_original_result_without_new_event(self):
        command = make_task_create_command(idempotency_key="same")
        first = self.fixture.handler.handle(command, authenticated_actor_id="a-1")
        first_events = self.fixture.store.read_events("p-1", after_sequence=self.fixture.after_sequence)
        self.assertEqual(first.status, "accepted")
        event_types = [event.type for event in first_events]
        self.assertIn("command.received", event_types)
        self.assertEqual([kind for kind in event_types if kind == "task.created"], ["task.created"])
        second = self.fixture.handler.handle(command, authenticated_actor_id="a-1")
        self.assertEqual(second, first)
        self.assertEqual(self.fixture.store.read_events("p-1", after_sequence=self.fixture.after_sequence), first_events)

    def test_two_processes_claiming_one_task_have_exactly_one_success(self):
        created = self.fixture.handler.handle(make_task_create_command(), authenticated_actor_id="a-1")
        self.assertEqual(created.status, "accepted")
        claims = make_claim_commands(task_id="t-1", expected_revision=created.aggregate_revision)
        results = run_two_processes_against_same_sqlite_file(self.fixture.db_path, claims)
        self.assertEqual(len(results), 2)
        self.assertEqual(sum(result.status == "accepted" for result in results), 1)
        self.assertEqual([result.error_code for result in results if result.status != "accepted"], ["REVISION_CONFLICT"])
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests/m0/test_idempotency_concurrency.py -v`
Expected: FAIL because repeated requests create duplicate events or concurrent claims have no durable conflict guard.

- [ ] **Step 3: Implement durable deduplication and optimistic concurrency**

Store the normalized digest and original `CommandResult` in the same transaction as the domain Event batch. Lock/serialize at the SQLite transaction boundary, recheck the task revision before commit, and return `REVISION_CONFLICT` to the loser. An in-process lock is not the correctness mechanism.

- [ ] **Step 4: Run GREEN and fault variants**

Run: `python -m unittest tests/m0/test_idempotency_concurrency.py -v`
Expected: PASS for same-key retry, same-key conflict and two-process claim; no duplicate domain event.

- [ ] **Step 5: Record evidence**

Write `artifacts/m0-04-test-report.json` with process IDs, command keys, result statuses and event count.

## Task 5: Restart, crash-after-commit and pure Replay

**Files:**
- Create: `src/aetp/core/runtime.py`
- Create: `tests/m0/test_replay_recovery.py`
- Modify: `src/aetp/core/projection.py`
- Modify: `tests/m0/support.py` (RuntimeHarness)
- Record: `artifacts/m0-05-test-report.json`

**Interfaces:**
- `SimulatedRuntime.execute(command: Command) -> CommandResult` performs only deterministic in-memory simulation and increments a test-observable invocation counter; M0 has no external side effects.
- `RuntimeRecovery.open(store_path: str) -> RuntimeRecovery`; `RuntimeRecovery.close() -> None` releases the opened store; `runtime_invocation_count: int` is a read-only count of actual simulated runtime invocations.
- `RuntimeRecovery.rebuild_project(project_id: str) -> dict[str, dict]`.
- `RuntimeRecovery.reconcile_pending(project_id: str) -> list[str]` returns persisted pending intent IDs without executing them.

- [ ] **Step 1: Write the failing tests**

```python
import unittest

from aetp.core.runtime import RuntimeRecovery
from tests.m0.support import RuntimeHarness, make_task_create_command, new_test_db_path


class ReplayRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.db_path = new_test_db_path(self)
        self.runtime = RuntimeHarness.open(self.db_path)
        self.addCleanup(self.runtime.close)
        self.command = make_task_create_command()

    def test_restart_rebuilds_same_state_and_does_not_invoke_runtime(self):
        before = self.runtime.run_demo_flow("p-1")
        self.assertTrue(before)
        self.runtime.close()
        recovered = RuntimeRecovery.open(self.db_path)
        self.addCleanup(recovered.close)
        after = recovered.rebuild_project("p-1")
        self.assertEqual(after, before)
        self.assertEqual(recovered.runtime_invocation_count, 0)

    def test_retry_after_response_loss_returns_original_result(self):
        before_count = self.runtime.domain_event_count("p-1")
        result = self.runtime.commit_then_drop_response(self.command)
        self.assertEqual(result.status, "accepted")
        retry = self.runtime.handle(self.command)
        self.assertEqual(retry, result)
        self.assertEqual(self.runtime.domain_event_count("p-1"), before_count + 1)
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests/m0/test_replay_recovery.py -v`
Expected: FAIL because recovery and crash-after-commit handling are absent.

- [ ] **Step 3: Implement recovery without side effects**

On open, load only Event Store and Projection metadata, rebuild deterministic state, and return pending intent IDs for later reconciliation. Replay never calls a model, shell, Runtime.start, or network. A simulated lost response reuses the original idempotency record.

- [ ] **Step 4: Run GREEN with forbidden-call spies**

Run: `python -m unittest tests/m0/test_replay_recovery.py -v`
Expected: PASS; forbidden-call spy count remains zero during replay and domain event count remains one after retry.

- [ ] **Step 5: Record evidence**

Write `artifacts/m0-05-test-report.json` with pre/post projection digests, forbidden-call counters and pending-intent handling.

## Task 6: M0 Conformance subset and handoff

**Files:**
- Create: `conformance/__init__.py`
- Create: `conformance/m0/__init__.py`
- Create: `conformance/m0/runner.py`
- Create: `conformance/m0/README.md`
- Create: `tests/m0/test_conformance_subset.py`
- Record: `artifacts/m0-conformance-report.json`
- Record: `artifacts/m0-handoff.json`

**Interfaces:**
- `run_m0_conformance(db_path: str) -> dict` returns `{test_id: {"status": "passed" | "failed" | "not_applicable", "evidence": str}}`.
- M0 executes only tests whose scope is Core Kernel; M1/M2/M3 tests remain explicitly `not_applicable`, never silently skipped.
- `TEST-011` (Approval expiry/escalation) is executed in M2-02, not M0-01/M0-03. M0-06 retains it only as a report registration with `not_applicable`; no Approval behavior is implemented or marked passed in M0. `TEST-014` and `TEST-015` likewise remain M1-scoped registrations. Before product execution, registered items remain `pending`, not product results.

- [ ] **Step 1: Write the failing conformance assertions**

```python
import unittest

from conformance.m0.runner import run_m0_conformance
from tests.m0.support import new_test_db_path


class ConformanceSubsetTests(unittest.TestCase):
    def setUp(self):
        self.db_path = new_test_db_path(self)

    def test_m0_report_never_claims_unimplemented_quality_gates(self):
        report = run_m0_conformance(self.db_path)
        self.assertEqual(report["TEST-003"]["status"], "not_applicable")
        self.assertEqual(report["TEST-028"]["status"], "not_applicable")
        self.assertEqual(report["TEST-001"]["status"], "passed")
```

- [ ] **Step 2: Run RED**

Run: `python -m unittest tests/m0/test_conformance_subset.py -v`
Expected: FAIL because the report runner does not yet distinguish M0 applicable tests from later quality gates.

- [ ] **Step 3: Implement the report runner**

Map each report entry to a real test output and evidence path. Mark Review/Verification/Acceptance and full idea-to-delivery scenarios `not_applicable` in M0. Do not derive pass from the presence of a test name or from a static JSON file.

- [ ] **Step 4: Run the full preparation and M0 suite**

Run:

```powershell
python -m unittest discover -s tests/preparation -v
python -m unittest discover -s tests/m0 -t . -v
python -m conformance.m0.runner --db .tmp/m0.sqlite --json artifacts/m0-conformance-report.json
```

Expected: all implemented preparation/M0 tests pass; the report contains explicit statuses and no `BOOTSTRAP_VERIFIED` claim.

- [ ] **Step 5: Independent review and handoff**

A different Agent checks the code diff, test output, fixture coverage and the 12 M0 report mappings. Record reviewer identity, commands and unresolved risks in `artifacts/m0-handoff.json`; only then may `M0-06` move to `done`.

## Self-review and exit condition

- The plan has no new Manager role, no A2A hard dependency, and no real external effect.
- Every production interface has a named test and a RED command.
- M0 deliberately leaves Review/Verification/Approval/Integration/Mission Acceptance to later milestones.
- Before starting implementation, verify the current `backlog.json` dependency state and the clean/shared worktree state; if Git is still unavailable, preserve evidence without inventing a commit.
- Restore the process-local `PYTHONPATH` after execution; do not persist environment changes.
- M0 exit does not imply M1/M2/M3 or `BOOTSTRAP_VERIFIED`; only the full §15.5 Bootstrap Acceptance and TEST-028 can make that claim.
