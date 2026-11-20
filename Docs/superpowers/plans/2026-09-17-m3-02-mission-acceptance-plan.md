# M3-02 Mission Acceptance 实施计划 (Plan)

## 一、实施目标
根据 `Docs/superpowers/specs/2026-09-17-m3-02-mission-acceptance-design.md`，实现 Mission Acceptance 状态跃迁、逐条准则验收与 TEST-010 交付门禁。

## 二、任务步骤与 Acceptance Criteria

### Step 1: 编写测试套件 `tests/m3/test_mission_acceptance.py`（TDD RED）
- **accept [c1]**: 未进入 acceptance 状态的 Mission 提交 complete 拒绝并返回 `MISSION_NOT_IN_ACCEPTANCE`。
- **accept [c2]**: 存在未验证准则的 Mission 提交 complete 拒绝并返回 `CRITERIA_UNVERIFIED`（TEST-010 / INV-019）。
- **accept [c3]**: 准则验证失败（FAILED）或未决（INCONCLUSIVE）时提交 complete 拒绝并返回 `CRITERIA_UNVERIFIED`。
- **accept [c4]**: 缺少 CRITICAL 级 human_owner 授权时提交 complete 拒绝并返回 `CRITICAL_APPROVAL_REQUIRED`。
- **accept [c5]**: 全部准则 PASSED 且经 human_owner 交付时，成功跃迁至 `completed`。
- **accept [c6]**: 全流程事件支持纯 Projection 重放一致性。

### Step 2: 领域定义与门禁逻辑实现
- 在 `src/aetp/planning/contracts.py` 注册相关命令与事件；
- 在 `src/aetp/acceptance/mission.py`（或 `src/aetp/planning/acceptance.py`）中实现纯函数门禁校验 `validate_mission_acceptance_start`、`validate_mission_verify`、`evaluate_mission_delivery`；
- 在 `src/aetp/planning/service.py` 或对应 Service 中集成命令调度与事务提交；
- 在 `src/aetp/core/projection.py` 中更新 Mission 投影 Reducer。

### Step 3: 回归测试与静态规范核验
- 运行 `tests/m3/test_mission_acceptance.py` 达到 GREEN 状态；
- 运行全量 integration/acceptance 专项测试；
- 运行 `tools/devprep.py render`、`tools/devprep.py check` 与 preparation 测试。
