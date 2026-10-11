# M3-02 下一批 Task 质量迁移输入核对

这是首批候选冻结后的只读规范与代码核对，供下一批设计使用；不是已实现功能、独立接受或新的授权。首批固定候选保持原样，M3-02 仍为 in_progress。本文未改变原规范、知识图谱、原三个验收条件或产品源码。

## 目前能确认的依赖

| 需求 | 原始依据 | 当前实现与缺口 |
| --- | --- | --- |
| 执行结束最多进入待审 | 主规范 §7.3、§13.9 | 受信 document.write 的完成事实及不可变 capture 已具备；Task 尚无 READY_FOR_REVIEW 正向入口。不能把工具完成直接当作任务执行结束或 Task 完成。 |
| 审查与验证指向同一不可变产物 | §10.2–10.3、INV-017 | Review 绑定 Artifact 摘要、准则及 Task revision；新 Verification 还绑定独立 Case-set、Runner、Policy、来源与执行上下文。当前全量 revision 比较会使任何 Task revision 增长失效。 |
| 只按明确规则复用旧证据并留痕 | §10.3 的验证有效性绑定 | 不能简单删除 `artifact.task_revision == task.revision`。需区分生命周期迁移与改变被审输入的修订，并记录新使用点为何仍适用。 |
| 审查不借作者 Lease | §7.6、§10.3、§14.1 | 原 Review 独立成员权限、新 Runner 的独立 QA Task/Session 已具备；Task 自身的受控写入仍需当前执行权，不能把 Review 资格误当任务写权。 |
| 无集成面需显式 Policy 豁免 | §7.3、§10.6、INV-004 | `_quality_gate` 仍拒绝全部成功迁移，没有 `task.integration_exempted`。固定 JSON 文档不自动证明没有集成面，Review/Verification 均不可豁免。 |
| 暂停只接收事实，不推进成功阶段 | §13.4 | Governance 与 Acceptance 有暂停/恢复检查；新增 Task 质量迁移必须在提交边界复查，不能从在途 PASSED 自动推进。 |
| Integration 固定真实源/目标/结果版本 | §10.6 | 尚无 git.merge、分支保护、冲突处理和结果 commit 的系统 Verification。本机无 Git repository，首批不创建 Git 或替代真实集成验收。 |
| Mission 不由 Task 完成推断成功 | §5.2、§9.3、§10.3、INV-019 | 需独立逐条 success_criteria 证据、固定 Mission revision/交付摘要和 CRITICAL human_owner 批准；首批 Artifact 验证没有该能力。 |

## 当前版本比较位置

- `src/aetp/collaboration/service.py` 的 `_target`：Artifact 中的 Task revision、criteria_digest、policy_version 必须与当前 Task 一致；`_request_review` 和 `_submit_review` 都使用它。
- 同文件 `_quality_gate`：检查 Artifact/Review/Verification 后仍返回 ENFORCEMENT_UNAVAILABLE，没有成功事件。末尾旧注释称“没有实现能到达该分支/没有 Runner”，在新 AcceptanceService 下已过时；此处只是保留旧成功门的实现，不是首批缺少 Runner。已向独立 reviewer 披露，冻结候选未修改。
- `src/aetp/acceptance/records.py` 的 `capture`：源 Action 的 requested_task_revision 必须等于当前 Task revision，且是当前作者 Session/Binding/Lease。
- 同文件 `target_snapshot`、`authorization_error`：Artifact 与目标 Task 完整 revision/准则/来源、质量与治理 Policy、执行上下文和 Runner 描述符固定并重查。
- `src/aetp/collaboration/records.py` 的 Artifact/Review/旧 Verification schema 都保留 `task_revision`；新旧历史不能因下一批迁移而改写或自动获得新权限。

## 下一批设计必须回答的事项

1. 用独立内容/准则版本表达质量输入，还是保留完整 Task revision 并通过显式证据复用事件跨越允许的生命周期迁移；两种方案都必须保留 Command expected_revision 的并发校验。不能把 status、owner、Lease 变化全部视为无关。
2. 旧 Task 如何显式进入新的质量契约；旧 Artifact、Review、M1 INCONCLUSIVE 记录不应无条件升级。旧事实必须仍能按原 schema 纯重放。
3. 执行结束报告如何固定本轮成果集合、当前作者与 epoch，以及尚未确定的 Action；不能仅凭一次 document.write 完成即推断整项执行结束。
4. 新审查流程何时产生 READY_FOR_REVIEW、IN_REVIEW、VERIFIED/REJECTED；谁能请求迁移、谁的权限在提交处核验；审查资格与任务归属应分开。
5. 正式使用已完成 Verification 时检查什么：当前输入、撤权/Policy 适用性、Runner 证据、来源、Case 作者独立性。grant 的单次派发截止时间与结果事后可用性应分清，不能无限续用，也不能无依据把所有历史 PASSED 改写成失败。
6. 显式无集成面声明如何获得版本化 Policy 的许可，如何保存 `task.integration_exempted`，何种输入变化要求重新评估；无法证明时继续拒绝完成。

## 最小失败与成功场景

- 成功：固定受信 Artifact、明确本轮执行结束、独立 Review approved、新 PASSED 对相同输入有效、真实 Policy 无集成面豁免，逐阶段提交和前缀 Replay 一致。
- Review 未通过、Verification FAILED 或 INCONCLUSIVE 分开处理；INCONCLUSIVE 不能推动成功或当作测试失败率。
- 仅生命周期前进的合法复用有记录；改准则、换产物或来源、换治理规则、旧 epoch/迟到报告及缺少复用依据必须拒绝或失效。
- 拒绝跳过 READY_FOR_REVIEW/IN_REVIEW、缺 Review/报告、M1 预检查冒充 PASSED、作者自评、Reviewer 借作者 Lease、未决 Action、暂停期成功迁移。
- 两个相同 expected_revision 的迁移竞争至多一个生效；提交回滚、响应丢失重试、receipt/effect 因果篡改、旧/新库逐前缀 Replay 均覆盖。
- 真实有集成面时即使 Task Verification PASSED 仍不可走豁免；Mission/Bootstrap/TEST-028 保持未接受。

下一步先消费真实首批独立结论，必要时修复并重新冻结；随后按以上问题形成单独设计与实现计划，再推进测试和产品代码。本文的场景尚未执行，不计入首批555方法或Conformance通过数。
