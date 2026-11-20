# M1-01：直接协作与候选成果证据链

工作项：M1-01。依据：用户要求继续推进既有 backlog，并明确不使用 ClaudeLink。实现者为主会话 Codex；独立复核者为本会话唯一子代理 `m1_reviewer`。这是开发期范围与实现选择，不改写协议，也不授予外部执行权限。

## 需求与阶段边界

落实 backlog 的三条验收：两个平等的已准入 Agent 直接发言、回复、质疑；没有 Manager 必经路径；低风险候选文档具有不可变 Artifact、独立 Review 和可复查 Verification 记录。

规范依据：主设计 §§7.3、7.6、8.2–8.5、10.1–10.3、13.4、14.1–14.2、14.7、14.10–14.11、17.2，以及 TEST-003/008/015/028。普通消息是过程材料，不产生领域 Event；被成果正式引用的消息快照才随 Command 固化。Review 不要求取得作者 Task 归属。

M1-02 尚未提供 Binding、Lease、Workspace、受限 Runner 授权与 Action 关联。本项不伪造这些对象或授权。候选登记、审查与预检查不推进 Task；既有 Task 阶段和归属保持其事实值。受信纯文档预检查实际执行并留下摘要与输出，但正式 Verification 记为 INCONCLUSIVE，明确缺少执行授权合同。VERIFIED / COMPLETED 请求拒绝。这样既留下真实检查证据，也不把内部检查冒充质量放行。成功质量门、真实执行和 M1 里程碑验收继续由 M1-02 完成。

## 方案选择

采用独立进程内 MessageBus，加上现有 CommandHandler / SQLiteStore 的增量协作处理器。相比把每条消息写成 Event，此方案符合 Message 与事实分离；相比复制一套数据库与事务处理器，它沿用原有身份、幂等、原子提交和 Projection。相比本轮同时实现完整 Runner / Lease，它保持 M1-01 与 M1-02 的依赖边界。

MessageBus 只保存当前进程的不可变过程记录，面向可信入口绑定的 actor 提供发送与收件查询。普通消息可丢弃；被引用的消息内容、作者、引用、来源标记和摘要会写入候选 Artifact 的来源快照，所以正式证据不依赖易失 MessageBus。进程内双身份夹具不等于真实模型接入或完整 TEST-028。

## 数据与写入路径

1. Message：项目、发送者、收件人、类型、正文、引用、被回复消息及来源标记。接收成员与引用都校验项目及可见性。发言不需要 Task 或 Manager。来源不明按不可信记录，引用或转述不能清除既有不可信标记。
2. Task：协作处理器创建低风险候选任务时固定验收文本与 Policy 版本，沿用 M0 创建/认领事实。验收标准摘要与其 Task revision 固定到 Artifact / Review / Verification。
3. Artifact：仅支持小型内联文档候选，以及受信检查器生成的报告。服务计算 UTF-8 内容摘要，保存完整不可变快照；修改使用新 ID 与 derived_from / supersedes。候选可由非 owner 登记，不改变 Task 归属。客户端摘要、执行身份、结果和任意代码不能取代服务计算。
4. Review：任何已准入成员可请求独立成员审查；作者不能审查自己的成果。指定 reviewer 才能提交结果。固定产物摘要、Task revision、验收标准摘要及 Policy；旧版本、错误目标、重复终结或伪造 reviewer 均拒绝。
5. Verification：受信固定文本检查器逐条检查验收文本是否存在，产生真实输出、检查套件摘要和环境摘要。系统将报告 Artifact 与正式 INCONCLUSIVE Verification 原子写入同一 Event 批次。正文中的指令不会执行。报告中的 observed_result 与正式 result 分开，缺少 Runner 授权不算 PASSED。
6. 所有事实写入继续使用 Command → SQLite BEGIN IMMEDIATE 内的最新 Event 校验 → 原子 Event 批次 / 幂等结果 → Projection。审查与验证对象独立于 Task 对象；Replay 只重建，不重新运行预检查。

## 固定低风险 Policy

版本为 `m1-document-candidate-v1`。只允许内联、有限大小的 public/internal 文档候选、过程消息、正式审查及无外部效果的预检查。支持的命令和字段显式列举；高风险、要求 Approval、未知 Policy、Git/路径/工具执行或敏感分级请求拒绝。`approval_required: false` 不是授权，客户端不能扩展 Policy。没有 Shell、模型、网络、发布或真实业务数据库动作。

## 文件范围与共享接口

新增 `src/aetp/collaboration/`、`tests/m1/`、本设计与计划、`artifacts/m1-01-test-report.json` 和本轮证据。共享改动限于 `src/aetp/domain/models.py` 的词汇扩展、`src/aetp/core/projection.py` 的增量归约/因果结果重建，以及 `src/aetp/core/commands.py` 的已知命令审计地址映射。后一处保证 M0 handler 对新词汇的拒绝也能被混合历史恢复正确解释；不改变身份、权限或 SQLite 事务逻辑。该接口调整已同步独立复核者。必要的 backlog/status 及 devprep 派生摘要由主代理维护。M0 历史证据与规范原文保留；用源码基线与当前候选摘要说明实现演进。

## 验收与失败场景

- 两个不同 actor 无 Manager、无 Task 直接对话、回复、质疑、提案；消息不会增加 Command/Event 或改变 Task。
- sender 伪造、未准入成员、跨项目/不可见引用、同 ID 换内容被拒；不可信引用不能洗成可信。
- 固定文档可读且服务摘要正确；新版本保留旧版本；非 owner 候选不会获取 Task。
- B 审查 A，无作者 Lease；自审、代审、陈旧 Task/产物/标准、同 Review 重复终结拒绝。
- 实际预检查成功和失败都留真实报告；正式 INCONCLUSIVE 不推进 VERIFIED；无 Review、无 Verification、自报 PASSED 或审批未实现均不能放行。
- 同 Command 重试不重复记录或检查；多对象写入失败完整回滚；跨连接版本竞争只允许一次终结；删除 Projection 后纯 Replay 等价且不运行检查器。
- M0 全量回归、准备检查通过；独立复核人核验固定候选后才能把 M1-01 置 done。完整 Conformance 和 Bootstrap 计数不因此改变。
