# 平等协作指南：候选规划示例

这是本地确定性夹具：脚本使用 writer、peer 两个身份互相质疑和回应，随后登记的 researcher 参与候选分工。没有调用真实模型，也没有正式完成 Task、Bootstrap 或 TEST-028。

原始想法：我想写一份短指南，让两个平等 Agent 直接讨论，并解释方案变化和恢复。

writer 建议先写草稿再独立评审。peer 指出需要恢复说明和明确的权限边界；writer 回应并采纳，peer 自行提出 recovery 任务，无需 Manager。

Mission v1、Team v1–v3 和 Blueprint v1–v5 都是提案。Team 从两人增到三人，再调整为 writer/researcher；peer 仍可发消息和提交 Change Request。原有 Agent 身份、Policy 和候选旧版本保留。

| 候选任务 | 依赖 | 预期产出 |
| --- | --- | --- |
| draft | guide-decision 提案 | 起草指南 |
| feedback | draft | 评审指南 |
| recovery | draft | 补充恢复案例 |

结构顺序为 draft → feedback/recovery。Decision 仍 proposed，正式 Bootstrap 与目标 Approval 尚未实现，因此没有可认领任务。

已实际拒绝：循环 DAG、过期 Blueprint 基线、正式激活、Core task.create 和恢复后的 tool.dispatch。暂停期间追加的候选修订可保留，执行能力仍 unavailable。

每个候选保存来源、内容摘要和 supersedes。Impact Analysis 只覆盖已知候选图；成本/延迟/风险为提案者声明，本例无模型费用。完整 SQLite 和仅含 Command/Event 的 SQLite 都经过只读逐前缀重放，文件字节未变。
