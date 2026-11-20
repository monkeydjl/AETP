# M3-02 Task 质量迁移与显式无集成面豁免

本批承接用户已授权的 M3-02 后续推进。首批固定 JSON Verification 已独立接受；本设计不改变主规范、原三个工作项条件或首批历史结论。设计意见由原 `/root/m1_reviewer` 只读核对；正式候选仍需另行独立复核。

## 依据与范围

依据主规范 §§7.3、7.6、10.2–10.3、10.6、13.4、13.9、14.1–14.2，INV-004、INV-017、INV-019。M3-02 原 Integration Gate、逐条 Mission Acceptance、真实平等 Agent 自主交付三个条件保留。本批提供它们需要的 Task 质量状态链，只适用于受信固定文档 Runtime。

- `phase=preparation`、`product_completion_percent=0`、`bootstrap_status=not_started`。
- 完整 Conformance 28 registered / 0 passed；完整 M1 `not_accepted`。
- 不使用 ClaudeLink，不创建新代理，只复用 `/root/m1_reviewer`。
- 不初始化/提交/推送 Git，不安装依赖、联网或修改全局配置。
- 不覆盖首批报告、示例、原始日志；MEMORY 只追加。修改前基线为 `Docs/development/evidence/2026-09-15-m3-02-quality-baseline.json`，498 文件、7 pins。

## 方案选择

采用显式质量轮次、固定提交快照和逐次适用性记录，保留完整 `Command.expected_revision`。Artifact 已有不可变内容摘要，因此暂不增加通用 `content_revision`。仅删除 revision 比较会放行换代或改准则的旧证据；另增内容版本仍不能表达 Policy、来源、Session 与执行代次变化。

新 `TaskQualityService(AcceptanceService)` 承担新命令。纯 `quality` reducers 复算事实；既有 Acceptance Runner、来源证明、QA Task/Session/Lease 和单次派发契约保持。旧 Review 和旧 Verification 不因新状态链自动获得完成权限。旧 M1 `verification.run` 仍是 INCONCLUSIVE。

## 版本化规则与显式加入

当前 human_owner 通过 `project.task_quality.configure` 配置不可变版本：`version`、按墙钟计算的 `max_evidence_age_ms`（1 至 86,400,000）以及 `integration_exemptions`。

每项豁免必须显式填写 Task ID、`standalone_fixed_json_document` 范围与原因；设施固定该 Task 的准则摘要、作者/Binding/epoch、Workspace Provider 与配置者/Command。空列表允许推进到 VERIFIED，但不能 COMPLETED。它是人类对该具体任务没有集成面的声明和版本化许可，不是从 JSON 内容或 document 类型推导集成面不存在。本批没有集成目标/required 的权威表示，不声称系统已能识别真实集成需求；真实 Integration Gate 仍是未实现的原工作项条件。

所有新质量操作还须匹配当前 Governance 的显式 LOW/auto 规则：`task.quality.transition`、`task.quality.review`、`task.quality.evaluate`、`task.integration.exempt`。manual、marked/unknown、非 LOW 或需审批路径拒绝；本批不增加这些操作的 Approval adapter。

作者在 IN_PROGRESS 通过 `task.quality.enroll` 显式加入，提交自身注册 Session、Binding/epoch 与当前 revision。Task 中留下契约、启用 Command/revision、固定 `work_revision` 和执行上下文。从 enroll/rework 起就固定实施工作期；首次提交前的任何非白名单 Task revision 增长同样使工作期失效，须显式 block/rework。已存在的 Artifact 或旧验证结果不自动加入；本轮正式成果须由启用后的真实执行生成。

## 正式提交、轮次与证据

`task.quality.submit` 是明确的本轮执行结束报告。它包含成果 Artifact ID 集合和非空总结，最多 8 份，不接受后态或结论。每份必须来自启用后、当前作者/Binding/epoch/current Task revision 的真实已完成 document.write，具有新 capture_origin 和完整清洁来源。该集合必须覆盖本次 revision 的全部已完成文档写入，不把一次工具返回视为任务执行结束。

提交排除目标 Task 的 pending/in_flight/unknown 实施动作，以及以该 Task 为执行任务或目标的未结束 Verification。所有成果内容、准则、来源、capture_origin、源 Action/result、作者与执行代次固定在新 `quality_cycle` 中。Task 进入 READY_FOR_REVIEW；之后 Runtime 拒绝新的文档执行。本轮实施结束不要求销毁 Session。

轮次保存初始 Task revision、当前可使用 revision、准则摘要、实施上下文、规则版本、提交 Command、Artifact 集合、Review IDs 和每次适用性检查。白名单仅包含本批质量迁移；其他 Task revision 增长不被静默忽略。旧 `lease.renew` 或 observation 导致 revision 变化时需要显式阻塞、重新接受工作并重新提交，不能无记录继承旧轮次。此保守限制不影响旧任务的原始行为。

`acceptance.records.target_snapshot` 对显式本轮 Artifact 提供相同原始 Task revision 加 `quality_cycle_id`，并检查轮次仍适用于当前 Task。旧路径仍用完整 revision 相等。新的 Verification 只能在 IN_REVIEW 为本轮指定独立 Reviewer 创建；既有 QA `execution_snapshot` 仍要求其自己的 Task 在 IN_PROGRESS。不得全局放宽该检查。

## 状态与权限

| Command | 前态 → 后态 | 授权与事实 |
| --- | --- | --- |
| task.quality.enroll | IN_PROGRESS → IN_PROGRESS | 当前作者实际 Session、Lease、完整 revision；建立契约 |
| task.quality.submit | IN_PROGRESS → READY_FOR_REVIEW | 当前作者实际 Session；固定全部成果和执行结束报告 |
| task.quality.request_review | READY_FOR_REVIEW → IN_REVIEW | 有明确 review 操作权限的参与者；逐 Artifact 指定独立 Reviewer，原子创建新 Review 和 Task 迁移 |
| review.quality.submit | Task 保持 IN_REVIEW | 指定 Reviewer 自身身份与权限；保存意见、反馈和来源，不借作者 Lease |
| task.quality.evaluate | IN_REVIEW → VERIFIED / REJECTED / IN_REVIEW | 有明确 evaluate 权限的参与者请求确定性判定，不能指定后态；记录所有适用证据与检查依据 |
| task.quality.block | 非终止质量阶段 → BLOCKED | 当前作者受控操作；明确原因，保存 blocked_from |
| task.quality.rework | REJECTED / BLOCKED → IN_PROGRESS | 当前作者实际 Session/Lease；归档旧轮次并开始新工作；不得复用旧轮次成果 |
| task.quality.complete | VERIFIED → COMPLETED | 独立 Review、PASSED 与本轮再次适用；当前执行上下文、显式治理许可和本 Task 无集成面声明 |

操作权限与目标执行代次分开校验。Review 请求/提交及质量判定保留请求者的真实身份。`requester_live` 只观察调用者实际传入的 Session；`target_live` 只从同一 Runtime 注册表读取作者当前 Session 来观察目标实施上下文。后者不能补足作者方法缺失的实际凭据：enroll/submit/block/rework 即使已认证且 Runtime 有其 Session，传入 session=None 仍拒绝；独立参与者不传作者 Session 请求 evaluate 可以成立。绝不以公开 fence 字段授予请求者作者权限，也不重新 register 历史 Session。作者可以请求判定，但通过条件必须包含不同 Agent 的 Review 与受信 Verification；允许 Reviewer 与 Verifier 为同一位独立同行。

本批采取保守活动 Session 边界：当前作者 Session 丢失/过期、Lease 撤销/到期、换作者/Binding/epoch、恢复屏障关闭时不推进受控质量阶段，历史证据仍保留。完成时原子撤销 Lease 并退役 Binding，避免其 Session 到期持续阻塞其他任务恢复。旧执行入口和 reducer 不能把 COMPLETED/CANCELLED 重新排队或改成 BLOCKED。

## 判定与证据适用性

每个正式 Artifact 必须有本轮指定 Review。旧 candidate Review 没有质量轮次来源，不能替代。Verification 全集先按持久 `quality_cycle_id + artifact_id` 收集本轮全部已受理记录，再逐条验证指定独立 Reviewer、自己的真实 QA 执行来源及当前适用性；每份 Artifact 至少一条。不可先过滤有效或 PASSED 再聚合；不适用、撤销、过期、来源异常的记录不得消失。判定顺序固定为：不适用先拒绝使用；有效负面结果导致 REJECTED；否则全部有效通过才 VERIFIED，缺少/未决/INCONCLUSIVE 保持原阶段。

- 任一有效 Review 要求修改/拒绝，或有效 Verification 为 FAILED：REJECTED。
- 全部 Review approved 且各 Artifact 至少一条验证、全部为 PASSED：VERIFIED。
- 缺记录、pending 或 INCONCLUSIVE：保留 IN_REVIEW，记录本次检查；不算失败或成功。
- 输入、来源、规则、执行代次或有效性不适用：拒绝使用，保留独立拒绝审计，不回写历史结论；可显式阻塞后返工。

完成证据检查与 Runner `authorization_error()` 分开实现。后者继续约束派发和记录；后续使用检查报告/Action/输入/Runner/Case 集合的完整性、原运行身份、当前 Governance/Quality 版本、轮次、独立性和规则最大年龄。墙钟 `now - finished_at_ms` 用于最大年龄；派发 grant TTL 过期不重写已有 PASSED。QA 任务在运行完成后的生命周期不被当作当前派发资格；其原运行证明仍须完整，Verifier 当前权限不得撤销。当前受信 Runner 描述符不一致时要求新验证。

在 final-use 记录中保存证据 ID/摘要、轮次、原始与当前 revision、规则版本、使用时刻和判定结果。暂停期间允许在途 Runner/旧 Runtime 报告按原事实入口留存；新增成功阶段不自动推进，恢复后需要新 Command 重新校验。独立 Review 只保存意见，不自动推进 Task。

## 无集成面完成与原子性

`task.quality.complete` 重新检查 VERIFIED 使用的完整证据、当前 Task 上下文、未决动作、规则版本和明确豁免。先产生 `task.integration_exempted`，其投影仍是 VERIFIED 且标明未决完成；紧接 `task.completed`，才设为 COMPLETED 并撤销/退役执行权。第一 reducer 从原始 State 和受理 Command 推导全部效果，在 r+1 记录已验证的预期终态续接证明。第二 reducer 核验这一已验证证明、同一 Command/context 和 r+2，不信任第二 payload 中提供的旧 Task 副本，不倒退 revision 重跑普通评估。两者与 Command/幂等结果在同一 SQLite 事务。任何中间前缀不得代表完成；缺失、替换、交错或重复终结事实必须被因果游标拒绝。

所有新事实嵌入完整 Command、设施观测、服务器时刻、确定性 effect index/count 与 record。新 Projection 游标校验 receipt、request digest、地址、revision、compound 连续性和终态。失败验证不发布 State 或 cursor。纯 Replay 不读取当前时钟、Runtime/Session 注册表、InputAuthority、Runner 或文件；只能使用事实内的已认证观测重新计算。

## 兼容、证据与验收

只增加新 quality 模块，并在固定共享入口接入词汇、reducer、pending Command 校验与目标适用性。修正首批 Minor M3-02-R1 的过时注释。保留旧源码归档，原示例/报告/数据库和日志不可覆盖。

本批独立验收条件：

1. 明确启用、真实执行结束、正式集合、独立 Review 和受信验证驱动合法 Task 阶段，禁止跳级及历史记录自动升级。
2. 每次证据复用固定轮次与当前适用性；处理版本/来源/Policy/Session/Lease/年龄变化，区分 FAILED 与 INCONCLUSIVE。
3. 仅显式具体 Task Policy 无集成面许可可完成；双事实原子、执行权退役且终止态不能被旧入口复活。
4. 真实提交回滚、响应丢失幂等、并发 revision 竞争、因果篡改和新旧逐前缀纯 Replay 均有证据。

未覆盖：真实 git.merge/分支保护/结果 commit 系统验证、Mission 逐条验收及 human_owner Approval、Bootstrap、真实模型调用/费用与 TEST-028 自主交付、通用 OS sandbox、待审后完全脱离作者 Session 的新授权模型。首批 accepted 保持，M3-02 整项仍 in_progress。
