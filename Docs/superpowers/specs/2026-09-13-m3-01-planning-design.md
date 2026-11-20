# M3-01 候选组队与规划设计

日期：2026-09-13。执行者 `/root`；独立复核沿用 `/root/m1_reviewer`。本设计落实已确认主规范，不修改协议或用户基本设定。用户已授权继续开发，ClaudeLink 禁用。

## 规范与范围

依据主规范 §§4.2–4.3、5.1–5.2、5.8–5.12、6、7.1–7.4、7.8、9.3、11.1–11.5、14.1–14.2、15.5。正式 Team Formation 和正式 Planning 必须在真实 Bootstrap Acceptance 之后；初始讨论与方案提案不依赖它。现有 M2 只实现 decision/task 审批目标，不能把 Decision 的批准当成 Team/Blueprint 批准。

本项实现**候选规划级**三个 backlog 验收条件：平等 Agent 动态提出和修订团队、不可变且有完整 DAG 校验的 Blueprint 候选版本、无需 Manager 许可的 Task/Blueprint/Team 提案。候选能够持久化、重放、查看差异和交接；不会成为 ACTIVE Team、已批准 Blueprint 或可执行 Task Graph。

备选方案：

1. 同时实现完整 Bootstrap、目标审批和 Mission Acceptance，范围跨入 M3-02 及未接受的 M1 质量门。
2. 仅用内存草稿，无法检验 Command/Event、并发与持久来源。
3. 采用本设计的事件化候选规划，明确拒绝缺少实施能力的正式生效入口。独立预查认为此范围可以支持本项限定验收，正式候选仍需重新独立复核。

## 持久范围与执行边界

`project.planning.configure` 只接受当前 Governance Policy 的 human_owner，通过 Command 的 expected_revision 在最终 SQLite writer transaction 内确认：项目有效、未暂停、没有任何已有 Task，且尚未启用规划。仅允许 `mode=candidate_only`；不存在关闭、降级或自报 Bootstrap 成功的参数。

该 Project 的 `planning` 配置成为持久事实。所有候选命令要求它存在。任何 Agent 均不能借提案暗中改变项目调度；有旧执行任务的项目需未来显式迁移，本项拒绝直接切换。

公共 `CommandHandler.handle` 在 writer transaction 中检查该范围，覆盖 Core、Collaboration、Meeting/Governance、Execution 的 `task.create`、`task.claim`、`execution.start` 等新执行入口。不根据 caller 是否携带规划元数据决定保护。纯 Replay 同样拒绝配置时已有 Task，以及配置后产生的执行 Task 创建/认领/启动事实。配置与 legacy task.create 的两进程竞争只能有一种结果成功。

未启用规划的历史 M0–M2 项目保持原有限范围；本项不回写历史事实。`team.activate`、`blueprint.activate`、`blueprint.apply`、`mission.activate` 在当前实现中均拒绝 `ENFORCEMENT_UNAVAILABLE`。没有新 Bootstrap 成功接口，没有对 missing Approval 默认放行。

## 数据与命令

`PlanningService` 继承 `GovernanceService`。所有写入沿公共原子 Command 边界；每次新意图生成 receipt 和一个领域 Event。纯 evaluator 从历史事实重新计算完整 record；reducer 检验 Event 内容、原始请求、摘要、身份、版本、时钟与地址，不把 caller 提供的 record 当 State。

候选实体限于现有 Mission、Team、Blueprint；Role/Contract 嵌入团队版本，Task Proposal/Change Request/DAG 是 Blueprint 子资源，不新增顶层 Entity。

- `mission.propose`：固定 title/objective/constraints/success_criteria，生成 proposed Mission v1。无完成/验收入口。
- `team.propose` / `team.revise`：固定 Mission 引用、目的、结构、角色、成员、职责契约、协作接口、估计成本/时间/置信度、风险。只允许 flat/network/adaptive。模型引用从登记 Agent 派生；角色要求和能力匹配只是建议，未实现 Router 资格门或评分。
- `blueprint.propose`：固定 Mission、Team 候选引用及 requirements/architecture/technology/components/milestones/tasks/risks/acceptance_criteria。
- `blueprint.change.request`：提交完整新候选，必须绑定最新候选的 version/digest、唯一 change_id、原因、成本/延迟/风险声明；计算已知图的影响，保留原候选和全部请求历史。
- `task.propose`：目标地址是 Blueprint，提交新的 Task 子资源，服务在事务中构建完整候选 DAG 并校验。所有此范围内的 Task 新增都影响嵌入 Blueprint 的图，因此进入 Change Request 候选路径；不接受 caller 的 affects_blueprint=false 作为旁路。

每个 record 有 schema_version、aggregate revision、latest_proposal_version、`active_version=null` 和仅追加 versions。version 标识**候选提案版本**；它不是正式已批准 Blueprint vNext。每个候选记录 author、原 Command、时间、规范化 content、content_digest、来源与 supersedes。Team 修订、Blueprint Change Request 和 Task Proposal 只追加候选，不改变旧候选的状态，更不执行正式变更传播。后续正式流程仍须 Discussion → Decision → 目标 Approval → apply，并重查所有已引用版本。

`supersedes` 指向旧候选的 kind/id/version/content_digest。CAS 用 aggregate revision，内容引用用候选 version/digest，不混为一谈。Mission/Team 引用必须匹配同项目，Blueprint 的 Team 必须属于所引 Mission。引用错误或过时拒绝。

候选 ID 与引用统一限制为 512 个 UTF-8 字节；估计金额为 0 到 2**63-1 的有限数值，置信度为 0 到 1，布尔值不冒充数值。先检查范围再做浮点有限性检查，超大合法 JSON 整数应产生持久 typed rejection，不能以 OverflowError 逃出 Command 边界。

Team 的 Role 和 Contract authority 字段保留为建议职责，不写入治理 Policy 或 Agent 身份。无 manager_id、parent、reporting_to、priority_override 等层级字段。Manager 可以作为普通名称，但没有额外权限；离开候选团队的 Agent 身份、消息、旧角色/契约和全部历史保留。Role Graph 不要求无环，未画出的接口不限制直接沟通。

## DAG 与影响分析

Task 节点含 id/title/type/milestone_id、required_capabilities、dependencies、inputs、expected_outputs、acceptance_criteria。依赖明确区分 task 与 decision：Task 边只能指向本候选中的节点；Decision 固定已有提案 revision/content_digest。未知引用、跨项目引用、自依赖、重复 ID/边、错误 milestone、悬空边和完整图中的环均拒绝。暂不支持跨 Blueprint Task 边，不能将其假装成已验证依赖。

每个候选单独保存 DAG version/digest、确定性拓扑序和并行层。服务不把依赖方向变成 Agent 职级。任务内容本身和图结构共同进入候选摘要；仅校验新边而忽略完整图是不允许的。

Impact Analysis 计算变动及下游受影响 Task、其 Artifact 输入、Decision 依赖、依赖边、团队成员，并记录风险、估计成本、估计延迟。估计是提案者声明，不是真实费用或已验证影响；范围明确为已知候选图。重大方案修改不直接更新 active 图；旧候选、被移除任务的版本内容、旧成员和所有来源均保留。

`candidate(project_id, kind, id, version=None)` 返回独立副本；`preview(project_id, blueprint_id, version=None)` 展示结构、Decision 依赖及当前失效原因，`claimable_task_ids=[]`，execution_readiness 始终 unavailable。它不是正式 Task Readiness 或 Router 资格判定。

## 来源与暂停

规划文本均为带身份的提案材料，固定 `untrusted_input=true` / `authority=proposal_only`。Decision 来源绑定实际不可变提案，不继承 Decision activation 的授权；另一个 Agent 转述、工具结果、caller 的 trusted/approved 字样都不能提升权限。来源快照和摘要保留，不读取或重新派发模型/工具。候选版本之间继承来源，不能在新版本中洗去旧的来源历史。

启用配置在 PAUSED 拒绝；已启用项目可以在暂停期间保存初始方案、质疑和候选修订，符合继续记录材料的边界。所有执行/正式生效入口继续拒绝。时间取可信宿主观察，Replay 使用持久时间，禁止读取实时时钟。

## 失败夹具与影响清单

| 约束 | 改动接口 | 必测行为 |
| --- | --- | --- |
| 平等与无 Manager | Team/Role/Contract；现有直接 Message/Discussion | 两个 Agent 可分别提案、回复、提出新任务；层级字段拒绝；候选角色不给审批/任务写权 |
| 版本与图 | Blueprint 子资源及纯 evaluator | 完整环、自环、重复、悬空、错误版本/来源拒绝；两进程同旧版本最多一份接受 |
| 受管范围 | 公共 Command 接受与 Projection | 省略全部规划元数据仍拒绝 raw create/claim/start；配置/create 两进程竞争 |
| 历史与来源 | 不可变候选/Change Request | 旧版本字节保持；缩编不删除 Agent；Decision 批准不能批准 Team/Blueprint |
| 事实链 | domain vocab、core 路由及 pending/replay | 事务失败无部分效果；同键返回原结果；篡改 record/请求/actor/digest 拒绝 |
| 暂停与恢复 | 已有治理控制 + 候选提案 | 暂停可记录提案，重启仍不可派发；所有前缀纯重建，运行设施守卫零调用 |

## 写集、验证与交接

新增 `src/aetp/planning/`、`tests/m3/`。接入修改 `src/aetp/domain/models.py`、`src/aetp/core/commands.py`、`src/aetp/core/projection.py`。如发现必要的 Runtime 旁路再记录和扩展范围；当前设计通过公共 handle 覆盖，不预先修改旧执行实现。资料写集为本设计、同日计划、`2026-09-13-m3-01-*` 证据、`artifacts/m3-01-*`、backlog/status、MEMORY 和 devprep 派生输出。

修改前基线 `.tmp/m3-01-baseline/` 已核验 252 文件；索引 `Docs/development/evidence/2026-09-13-m3-01-baseline.json`。主 journal 串行追加，所有真实失败保留。独立 reviewer 使用独立准备检查副本。

验证：M3 行为测试、实际双 Agent 提案示例、新旧 SQLite 只读兼容及纯 Replay，M2/M1/M0 回归与三项准备检查；冻结候选后独立接受才能 done。完整 Conformance 28 registered / 0 passed，phase=preparation、product_completion_percent=0、bootstrap_status=not_started，完整 M1 not_accepted。正式 Verification、Task COMPLETED、Integration、Mission Acceptance、正式 Bootstrap 和完整 M2/M3 均不在本项成功声明中。

中途失败修正：纯 `PlanningCursor` 将 M3 effect 与此前 command.received 的请求摘要、地址和终结记录绑定，缺回执或重新封装作者时拒绝。该 cursor 仅由 Event 派生，旧 M0/M2 Event 格式不变；受管项目缓存缺完整 cursor 时从事实重建。`replay_concurrency_red` 的两项真实失败与后续 GREEN 均保留。
