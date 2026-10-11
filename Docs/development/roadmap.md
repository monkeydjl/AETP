# AETP M0–M3 路线图

更新：2026-09-06。产品实现完成度当前为 **0%**；下表是拆分与验收定义，不是已完成声明。

## 里程碑

| ID | 目标 | 交付范围 | 退出验收（必须有证据） | 前置 |
| --- | --- | --- | --- | --- |
| M0 | Core Kernel | Project / Agent / Task / Command / Event；模拟 Runtime；事务、版本、幂等、重启、纯 Replay | `TEST-001`、`002`、`005`、`012`、`016`、`017`、`018`、`019`、`021` 的 M0 适用部分；不伪造质量完成或 Bootstrap | PREP-001…008；环境最低检查 |
| M1 | 双 Agent 最小成果 | Message、Artifact、Review、Verification、Lease、Checkpoint、Runtime/Workspace 边界；固定版本低风险 Policy | 无 Manager 直聊并交付低风险小成果；Review/Verification/Lease/隔离失败场景；需要 Approval 的操作拒绝 | M0 done |
| M2 | 结构化讨论与治理 | Discussion、Meeting、Decision、Approval、Governance、预算/升级/暂停 | 决策可追溯，审批主体分离、过期/撤销、暂停屏障与预算门禁可复现 | M1 done |
| M3 | 想法到成果闭环 | Team Formation、Blueprint、Task DAG、Integration、Mission Acceptance、完整 Bootstrap | `TEST-028`：至少两个平等 Agent 从粗糙想法直接讨论到可追溯方案并交付；无 Manager 必经路径 | M2 done |
| M4 | 正式 Acceptance | Project Bootstrap（B0–B5）、Full-protocol Conformance、M1–M3 整里程碑验收 | Bootstrap Acceptance、28 项 conformance passed、各里程碑 accepted，最终 product_completion 抬升 | M3 done |

## 执行顺序

1. 先完成开发准备资料内部检查，不把它写成 `BOOTSTRAP_VERIFIED`。
2. 按 `M0-01 → M0-02 → M0-03 → M0-04 → M0-05 → M0-06` 纵向贯通，每项完成独立测试和复核。
3. M0 的模拟 Runtime 不执行 Shell、发布或真实外部副作用；外部 UNKNOWN、对账和 Workspace 强边界留到对应 M1/M3 工作项。
4. 每个里程碑只能在对应验收证据齐全且由不同 Agent 复核后置为 `done`；文档条目存在不等于测试 `passed`。

## M4 正式 Acceptance（v0.1 收尾，本期新增）

按用户决定，M4 是产品整体交付验收，拆三个 work_item：M4-01 Project Bootstrap（§15.5 B0–B5 → `BOOTSTRAP_VERIFIED`）、M4-02 Full-protocol Conformance（§17.4/§18.3 28 项 registered→passed）、M4-03 里程碑整体验收（M1/M2/M3 accepted + product_completion 抬升）。退出验收必须由独立复核人证成的 Evidence；正式计数（phase/bootstrap/conformance）在证据闭合前保持 preparation 冻结。

## 未纳入 v0.1 首批

Dynamic Team Evolution、Agent Evolution、Advanced Consensus、Ephemeral Agent Generation、Kafka/RabbitMQ/Redis、A2A 必需接入和前端体验；这些不应偷偷进入 M0。
> M0 退出列表仅列 M0 可执行的适用部分。`TEST-011`（Approval 过期后的升级路径）实际执行归 M2-02，不属于 M0 的五核心对象测试；M0-06 仅保留其 `pending/not_applicable` 登记。`TEST-014`（Runtime/Workspace 跨边界与 Provider 隔离）归入 M1-02，`TEST-015`（无 Manager 中转的 Agent 直接对话与独立审查）归入 M1-01；M0-06 可以登记这些 TEST 的 `pending/not_applicable` 状态，但不能把它们写成 M0 已通过。

