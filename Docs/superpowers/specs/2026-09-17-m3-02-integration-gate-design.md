# M3-02 Integration Gate 与执行边界详细技术设计

日期：2026-09-17（Asia/Shanghai）。工作项：M3-02。
阶段：详细设计（Spec），遵循平等协作与严格事实链原则。

---

## 1. 目标与非目标

### 1.1 核心目标
1. **完整落地 Integration Gate 状态机流转**（§7.3、§10.6）：
   - `VERIFIED → READY_FOR_INTEGRATION → INTEGRATING → INTEGRATED → SYSTEM_VERIFIED → COMPLETED`；
   - 彻底践行 `VERIFIED ≠ INTEGRATED`（INV-004、INV-020）：模块级别验证通过不等于系统集成通过。
2. **强制豁免留痕与防绕过拦截（TEST-009 / INV-004）**：
   - 存在集成面的任务，未经 Integration Gate 绝对禁止流转至 `COMPLETED`；
   - 无集成面任务的豁免必须基于版本化 Governance Policy 显式留痕（`task.integration_exempted`）；
   - 历史豁免不得绕过后来的集成需求声明（`project.integration.declare` 与豁免互斥）。
3. **合并基线检查与冲突检测（TEST-024 / §10.6）**：
   - 受理 `git.merge` Command 时，强制校验目标分支基线 commit 与 expected_commit；
   - 目标分支一旦前进（基线变更），立即拒绝（`BASELINE_ADVANCED`），防止脏合并或旧验证误放行；
   - 冲突检测：冲突产生 `integration.conflict` 事实，禁止静默覆盖或强行 rebase。
4. **合并后系统级 Verification 事实挂接（§10.3 / §10.6）**：
   - 合并成功产生 `integration.completed` 后，针对 `result_commit` 触发系统级验证；
   - 产生独立的 `verification.completed` 事实，通过后方可推进至 `SYSTEM_VERIFIED`。
5. **外部执行边界与 UNKNOWN 对账机制（TEST-020 / §14.4）**：
   - 数据库事务绝不包住外部调用；在途外部调用持久化 `in_flight` Action；
   - 超时或结果为 `UNKNOWN` 时必须查询对账，沿用原 Command 与幂等键，禁止盲目新建 key 重试。

### 1.2 非目标
- 不引入外部远程网络依赖（所有 Git 操作或沙箱均在本地隔离受控环境中运行）；
- 不修改宿主全局 Git 配置；
- 不跳过既有事实链（严禁绕过 Command → Event Store → Projection 临时写状态）；
- 不由单个 Agent 伪装两个独立审查者（遵循平等 Agent 与独立 Review 原则）。

---

## 2. 权威约束与基线对齐

| 约束项 | 规范条款 | 强制要求 |
| --- | --- | --- |
| 状态机顺序 | `Docs/AETP-设计方案.md` §7.3 | 必须严格按序迁移，禁止从 `IN_PROGRESS` 或 `VERIFIED` 直接跳至 `COMPLETED` |
| 集成门禁原则 | 同上 §10.6, INV-004 | `VERIFIED ≠ INTEGRATED`；合并是一条 Command，合并后必须针对 result_commit 跑系统 Verification |
| 基线前进拒绝 | 同上 §10.6, TEST-024 | 目标分支基线改变时，旧基线验证自动失效并拒绝合并 |
| 事实链完整性 | 同上 §§14.1–14.2 | Command → Event Store → Projection，幂等键冲突与 expected_revision 严格 CAS |
| 外部对账 | 同上 §§13.9, 14.4, TEST-020 | 外部效果持久化 Action，UNKNOWN 必须对账查询，不建新 key 重试 |
| 纯重放隔离 | 同上 §§13.4, 13.10, TEST-021 | Replay 纯内存消费 Event 重建 Projection，不产生外部副作用 |

---

## 3. 核心机制设计

### 3.1 Task 状态迁移与条件守卫

```text
[VERIFIED] 
   │
   ├─► (声明了集成需求) ──► Command: task.integration_ready ──► [READY_FOR_INTEGRATION]
   │                              │
   │                              ▼ Command: git.merge
   │                        [INTEGRATING]
   │                              │
   │                              ├─► 基线前进 ──► REJECTED (BASELINE_ADVANCED)
   │                              ├─► 产生冲突 ──► Event: integration.conflict
   │                              └─► 合并成功 ──► Event: integration.completed ──► [INTEGRATED]
   │                                                                                     │
   │                                                                                     ▼ Command: system_verification.record
   │                                                                               [SYSTEM_VERIFIED]
   │                                                                                     │
   │                                                                                     ▼ Command: task.completed
   │                                                                                [COMPLETED]
   │
   └─► (显式 Policy 豁免) ──► Command: task.integration_exempted ──► Command: task.completed ──► [COMPLETED]
```

### 3.2 Command 契约与校验规则

1. **`task.integration_ready`**
   - 前提：Task 处于 `VERIFIED` 状态；
   - 检查：该 Task 必须存在已登记的 `project.integration.declare` 且 `requirement == "required"`；
   - 产生事件：`task.integration_ready`，状态迁移至 `READY_FOR_INTEGRATION`。

2. **`git.merge`**
   - 前提：Task 处于 `READY_FOR_INTEGRATION` 状态；
   - 参数校验：
     - `source.ref`、`source.commit`
     - `target.ref`、`target.expected_commit`
     - `execution.binding_id`、`execution.lease_epoch`
   - 基线检查：比对当前 target ref 的当前 commit 与 `expected_commit`，若不一致则抛出 `BASELINE_ADVANCED` 拒绝；
   - 产生事件：
     - 成功：`integration.completed`（记录 `source_commit`, `target_commit`, `result_commit`, `merged_at`），Task 进入 `INTEGRATED`；
     - 冲突：`integration.conflict`（记录 `conflicting_paths`, `base_commit`），Task 保持或记录冲突。

3. **`task.system_verify`**
   - 前提：Task 处于 `INTEGRATED` 状态；
   - 校验：系统级 Verification 必须针对 `result_commit` 运行，且结论为 `PASSED`；
   - 产生事件：`task.system_verified`，Task 状态迁移至 `SYSTEM_VERIFIED`。

4. **`task.completed`**
   - 前提：
     - 若为集成任务：必须处于 `SYSTEM_VERIFIED` 状态；
     - 若为豁免任务：必须已有显式 `task.integration_exempted` 事实，且未被后续集成声明覆盖；
   - 任何处于 `VERIFIED`、`READY_FOR_INTEGRATION`、`INTEGRATING` 或 `INTEGRATED` 的任务尝试调用 `task.completed`，一律抛出 `INTEGRATION_GATE_REQUIRED` 拒绝（满足 TEST-009）。

---

## 4. 模块结构与实现分工

1. **`src/aetp/integration/gate.py`**：
   - 负责 Integration Gate 状态机校验规则（迁移守卫、基线比较、豁免互斥）；
   - 纯函数逻辑，供 Service 与 Projection 共享复用。
2. **`src/aetp/integration/service.py`**：
   - 扩展 `IntegrationContractService`，支持 `git.merge`、`task.integration_ready`、`task.system_verify`；
   - 严格在 ResourceGate 与 SQLite writer transaction 中执行双 revision 检查；
   - 外部合并操作解耦，支持可注入的 Git Execution Boundary。
3. **`src/aetp/integration/projection.py`**：
   - 确定性更新 Task 状态与 Project 集成事实；
   - Replay 纯函数消费事件，零外部副作用。

---

## 5. 验收标准与测试矩阵

1. **TEST-009 验证**：
   - 针对未豁免任务，尝试直接跳过门禁完成，断言必须拒绝；
   - 针对豁免任务，验证显式留痕事件后方可完成；
   - 针对被新集成声明覆盖的任务，验证旧豁免失效。
2. **TEST-024 验证**：
   - 模拟目标分支基线前进（目标 commit 与 expected_commit 不符），断言 `git.merge` 拒绝；
   - 模拟合并后代码变更，断言旧验证不放行，强制要求新基线 Verification。
3. **确定性重放验证**：
   - 全程事实通过纯 SQLite 回放，100% 状态一致。
