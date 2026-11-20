# M3-02 Integration Gate 实施计划（TDD 驱动）

日期：2026-09-17（Asia/Shanghai）。工作项：M3-02。
实施者：当前会话。交接对象：独立 Reviewer 与用户。

---

## 阶段一：测试先行（RED）

### 步骤 1.1：编写 Integration Gate 核心单元测试套件
- **文件**：`tests/m3/test_integration_gate.py`
- **用例**：
  1. `test_verified_to_ready_for_integration`：声明了集成的任务从 VERIFIED 迁移到 READY_FOR_INTEGRATION。
  2. `test_missing_declaration_cannot_enter_integration`：未声明集成的任务不能随意进入 READY_FOR_INTEGRATION。
  3. `test_merge_baseline_advanced_rejected`（TEST-024）：目标分支当前 commit 与 expected_commit 不匹配时拒绝合并。
  4. `test_merge_success_and_integrated_state`：基线一致时合并成功，产出 `integration.completed`，进入 INTEGRATED。
  5. `test_merge_conflict_event`：冲突检测产生 `integration.conflict`，不静默覆盖。
  6. `test_system_verification_required_for_system_verified`：针对 result_commit 验证通过后进入 SYSTEM_VERIFIED。
  7. `test_unexempted_task_cannot_complete_without_gate`（TEST-009）：未豁免任务尝试在 VERIFIED/INTEGRATED 直接 COMPLETED 必须被严格拒绝。
  8. `test_exempted_task_with_audit_trail_can_complete`（TEST-009）：显式 Policy 豁免并留痕后允许完成。
  9. `test_deterministic_replay`：包含门禁事件的历史纯重放状态一致，零外部调用。

---

## 阶段二：协议与纯校验实现（GREEN）

### 步骤 2.1：扩展契约常量与模型
- **文件**：`src/aetp/integration/contracts.py`
- 新增 Command：`task.integration_ready`, `git.merge`, `task.system_verify`
- 新增 Event：`task.integration_ready`, `integration.completed`, `integration.conflict`, `task.system_verified`

### 步骤 2.2：实现 Gate 状态机纯函数
- **文件**：`src/aetp/integration/gate.py`
- 纯函数校验逻辑：状态前置检查、基线一致性比对、豁免有效性判定。

### 步骤 2.3：更新 Service 与 Projection
- **文件**：`src/aetp/integration/service.py`、`src/aetp/integration/projection.py`
- 挂接 Command 事务与 Projection 状态更新，确保双 revision CAS 与 ResourceGate 保护。

---

## 阶段三：回归与全量验证

### 步骤 3.1：单元测试与集成测试验证
- 运行新增套件：`PYTHONPATH=src python -m unittest tests/m3/test_integration_gate.py -v`
- 运行 Integration 整体回归：`PYTHONPATH=src python -m unittest discover -s tests/m3 -p "test_integration*.py" -t .`

### 步骤 3.2：准备工具核验
- `python tools/devprep.py render`
- `python tools/devprep.py check`
- `python -m unittest discover -s tests/preparation -v`
