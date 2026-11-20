# M3-02 第一批：受信文档 Verification

依据用户继续任务的授权推进 M3-02；使用既有 `/root/m1_reviewer` 独立复核。该批是新的验收子系统前置能力，M3-02 保持 in_progress，原三个验收条件不缩减。设计已结合原 reviewer 的只读规范核对；复核意见不是产品验收或人类治理 Approval。

## 范围与选择

采用独立 `AcceptanceService`，在现有 Planning/Governance host 上增加显式受信入口；第一批交付可真实运行的固定 JSON 文档检查、单次可撤销授权、持久执行审计、不可变报告与纯 Replay。新事件使用独立 schema，旧 `verification.run`/`verification.completed` 仍表示 M1 预检查。

比较过直接扩展旧预检查和复用裸 `action:*`：前者会改变已接受旧事实的语义；后者会被只认识文档写入的 Runtime 恢复逻辑误处理。这里将 Action 作为新 Verification 的可寻址子资源，保留稳定 action_id 和请求/派发/结果 Command 因果；全局恢复检查仍能看到未决 Action。

Task 成功迁移、正式 Integration、Mission Approval、Bootstrap、Team/Blueprint apply 与 TEST-028 正向验收按后续依赖实施。本批不放开 candidate_only，完整 M1/M2/M3 与完整 Conformance 不因新测试通过而获得验收。

## 规范与影响

- §§10.3、14.1、14.4：Runner 运行来源、Action、单次授权、事实事务与不可变证据；失败、未确定与检查不匹配分开。
- §§7.6、10.3、13.9：验证者使用独立 exec_task_id 的真实 Session、Binding、Lease，不取得作者 Task。默认验证者和 Case 作者均非产物作者。
- §§9.3–9.5、13.4：当前 human_owner 固定低风险质量 Policy，客户端风险标签只能收紧；暂停、撤权、Policy/Session/epoch 变化均在真实运行点重查。
- §§5.2、7.3、10.6、15.5、INV-004/017/019：本批的 PASSED 仅证明固定检查成立；不会自动完成 Task、Mission 或 Bootstrap，也不证明理解了自然语言准则。
- §§14.2、16.1：旧结果、失败和来源不重写；receipt/Command/报告/终结必须一致，Replay 不执行 Runner。

不改变用户平等 Agent 基本设定，不增加协议顶层实体。Action、Case-set 和执行授权是 Verification 的子资源。

## 输入与检查方法

只检查 Event Store 中可读取的不可变 document Artifact。输入固定 artifact_id/digest、所属 Task 的完整 revision、criteria_digest、逐条准则、独立 Case-set、质量 Policy 代次、Governance Policy 版本和 Runner 描述符。尚未增加 Task 生命周期迁移，因此保守绑定完整 Task revision；以后复用内容快照必须另行设计显式规则。

Case-set 随 `verification.request` 登记，不可变，其作者取 authenticated actor；不接受 `test_authorship` 自报。每条自然语言 criterion 恰好对应一个 Case，顺序和文本与目标快照相同。Case 为 `{criterion, path, equals}`：path 是最多16个字符串键/非负整数下标，equals 是有限 JSON 值；不解释表达式、不访问文件。最多32 Case，总规范化输入最多16384 UTF-8字节。

固定 Runner 严格解析 JSON，拒绝重复键、NaN/Infinity、非有限数值、非法Unicode和过深结构。缺失路径与 null 区分，true 与 1 区分。每项保存匹配结果、观察类型/摘要和有限诊断；总体 PASSED 当且仅当全部检查实际运行且通过。无效目标 JSON 或不匹配是 FAILED；Runner 异常、没有确定输出、授权丢失或快照变化是 INCONCLUSIVE。

Runner 只读内存快照，无用户代码、Shell、网络或 Workspace 路径能力。它的版本、实现文件摘要、Python环境和固定调用描述形成可复核输入；声明范围是该固定检查器，不认证通用隔离或任意测试执行。

增加窄 `artifact.capture` 入口，仅从已完成、非 historical 的固定 document.write Action 捕获当时生成的字节。重算 arguments/content/result/envelope 摘要，要求原 Action requested_task_revision 等于当前完整 Task revision，作者及当前真实 Session/Binding/Lease 一致。产物作者、内容、摘要、准则均从事实派生；本次 capture 的真实 InputAuthority 来源与原 Action 完整 authorization/source 合并，任何 unknown/marked 祖先保持标记。无须重读 Provider，不声称表示当前文件状态。此入口和新 Verification 都保持 candidate_only 执行门关闭。

## 授权和事实链

`project.quality.configure` 仅当前 human_owner 可执行，固定方法、大小、独立性和单次授权有效期；每次配置增加质量代次，旧授权不能自动继承。治理 Policy 变化同样使未执行授权失效。需要审批的风险请求保持拒绝。

Governance 与 Quality 取交集：新增显式 `verification.execute` 治理规则，旧 Policy 无规则时拒绝；首批只支持 selective/autonomous、有效 low、auto。Manual、显式较高风险或需审批路径均拒绝。依据 §§8.7、14.11，固定检查器只读不能清除 untrusted_input；request 使用既有 InputAuthority 对象能力，保留完整来源及 Artifact 的继承标记，marked/unknown 请求升级后本批拒绝。Quality 配置不是逐请求 Approval。

`verification.request` 固定独立验证者的 exec_task_id、binding_id、lease_epoch、session_id。验证 Task 必须真实 in_progress，Session 为同一 DocumentRuntime 注册对象，不能只是相同字段；绑定目标产物的作者 Task 不提供验证执行权。

`dispatch(project_id, verification_id, session=...)` 是宿主入口：ResourceGate → writer transaction，重新检查持久 grant、快照、Policy、暂停、会话与恢复屏障，提交单次 `verification.dispatched` 后才能执行 Runner。调用方不能直接提交 dispatch/report 获得受信上下文。同一 grant 的并发或重试最多一次实际运行。

结果保存为报告 Artifact 和 `verification.finished` 的同一事务。报告绑定 Action、完整输入摘要、逐条输出、实际时刻、执行状态与来源。结果事务失败留下 in_flight，不把未提交结果当事实；恢复产生有证据的 INCONCLUSIVE，不自动再次运行。已完成请求的重试返回原事实，不产生第二次检查。

撤销是新 Command/Event。未派发授权可撤销且不运行；派发后的撤销或期限/会话变化保留观察，但不能形成可用 PASSED。终结后不改写原结果；使用时重新检查其快照与授权适用性。

## Replay 与恢复

新 schema reducer 校验受理 Command、receipt digest、actor、地址、context、Action代次和报告内容摘要。报告为中间事实，必须紧接同因果合法终结；孤立报告、重封来源、重复终结和缺 receipt 拒绝。增量失败不发布 State 或游标。

新 capture 的顶层创建证明只由新 schema reducer 产生，旧 Artifact 的可扩展 source 字段不能伪装该证明。报告 ID 由宿主保留，公共创建入口及 Quality 启用后的事实回放都禁止抢占；Quality 启用前的历史碰撞在新授权前拒绝。合法前缀可以结束于中间报告，但该 Command 必须保持 pending，Verification 不获得结果；下一事实必须是对应终结。

新 Action 保存在 Verification 内，普通 document Runtime 不派发它；governance recovery_assessment 将其 in_flight/unknown 状态纳入 unknown_actions。Acceptance 宿主显式恢复这些记录，再让既有 Runtime 重建自己的会话/屏障。纯 Projection 和仅 Command/Event 恢复不调用 Runner、Session 注册、文件 Provider、Shell 或网络。

固定 Runner 的完整调用持有跨进程 ResourceGate。恢复只有取得同一个排他 gate 后才能把未决调用记为 abandoned：该固定内存调用已退出或原进程已终止，没有外部效果可继续执行。恢复报告记录这一明确终止依据和丢失输出，不仅凭 INCONCLUSIVE 字样清理未决状态，也不重新运行 Runner。此结论不可推广到任意外部工具。

## 验证与后续

测试必须包含真实 SQLite事务、双执行Task和真实注册Session，检查输入/输出与拒绝事实。失败场景覆盖作者身份、冒充Case作者、复制Session、借Lease、换epoch、暂停/Policy变化、失效快照、重复派发、结果事务失败、恢复不重跑、严格JSON边界、因果篡改及未决执行对全局恢复的影响。新旧示例均只读回放；固定脚本身份仍是夹具。

独立复核本批实现后，下一批首先设计内容版本与生命周期revision分离及Task质量迁移，再完成正式集成、逐条Mission验收、CRITICAL人类批准和真实双Agent演练。没有相关事实前 M3-02 不转 done，TEST-028 保持未通过。

工作环境保持本地 Windows、标准库、无Git初始化/commit/push、无安装/联网/全局配置变化。先归档 M3-01 接受输入，后续新实现不会覆盖其报告或历史证据。
