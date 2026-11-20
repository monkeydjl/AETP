# M3-02 Mission Acceptance 设计规范 (Spec)

## 一、规范依据与目标

依据 `Docs/AETP-设计方案.md` §§ 5.2, 7.3, 9.4, 10.3, 16.1 (INV-019), 18.3 (TEST-010)：
1. **INV-019**：Mission 不得仅依据 Task 完成状态进入 COMPLETED。进入 ACCEPTANCE 后，必须针对 `success_criteria` 逐条产生 Acceptance Verification，并经 CRITICAL 级人类批准才能交付——Task 不能自己宣布 VERIFIED，Mission 更不能自己宣布完成。
2. **TEST-010**：Mission Acceptance 失败不得 Delivery。当任何一条准则未经验证、验证失败（FAILED/INCONCLUSIVE）、或缺少 CRITICAL 级人类授权时，交付必须被严格拒绝。

## 二、命令与领域事件

### 1. 命令扩展
- `mission.activate`
  - 目标：将处于 `approved` 状态的 Mission 激活为 `active`。
- `mission.acceptance_start`
  - 目标：将处于 `active` 状态的 Mission 转入 `acceptance` 阶段，准备逐条准则验收。
- `mission.verify`
  - 目标：针对 Mission 指定的 `criterion` 提交客观 Acceptance Verification 凭证。
  - Payload：
    - `criterion`: 匹配 Mission `success_criteria` 中的文本或索引
    - `result`: `"PASSED"` | `"FAILED"` | `"INCONCLUSIVE"`
    - `evidence`: 包含 `artifact_id`、`content_digest`、`runner_id`
    - `verifier_id`: 验证执行 Agent ID
- `mission.complete`
  - 目标：提交 Mission 交付请求，触发 TEST-010 / INV-019 门禁核验。
  - 权限要求：CRITICAL 级人类批准（必须由 `human_owner` 授权/执行）。

### 2. 领域事件
- `mission.activated`: Mission 状态变更为 `active`
- `mission.acceptance_started`: Mission 状态变更为 `acceptance`
- `mission.criteria_verified`: 记录某条 criterion 的验收凭证事实
- `mission.completed`: 门禁核验通过，Mission 状态变更为 `completed`

## 三、门禁校验规则与错误码

1. **状态前置规则**：
   - 尝试在非 `acceptance` 状态提交 `mission.complete`：拒绝并返回 `MISSION_NOT_IN_ACCEPTANCE`。
2. **逐条验收全覆盖（INV-019 / TEST-010）**：
   - 检查 Mission 定义的所有 `success_criteria`；
   - 若存在任何一条未验证，拒绝并返回 `CRITERIA_UNVERIFIED`；
   - 若存在任何一条的最新验证结果不为 `"PASSED"`（例如 FAILED 或 INCONCLUSIVE），拒绝并返回 `CRITERIA_UNVERIFIED`。
3. **人类授权核验（§ 9.4）**：
   - 交付操作必须由项目的 `human_owner` 发起或附带经核验的 CRITICAL 人类审批凭证；
   - 若由非人类或非 human_owner Agent 擅自发起，拒绝并返回 `CRITICAL_APPROVAL_REQUIRED`。
4. **不可变事实与重放**：
   - 所有事件均记录于 SQLite 事件存储；
   - 投影 Reducer 支持幂等与确定性回放，确保回放状态与运行时完全一致。
