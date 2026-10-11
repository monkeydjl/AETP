# 候选组队与规划

`PlanningService` 在已有 Command → Event Store → Projection 路径上保存 Mission、Team、Blueprint 和 Task Proposal。M3-01 的范围是候选规划；正式 Bootstrap、Team/Blueprint 目标审批和生效流程尚未接入。

宿主先用当前 Governance Policy 中真实 `human_owner` 的身份提交 `project.planning.configure`，唯一模式为 `candidate_only`。最终 writer transaction 确认项目还没有 Task，配置后不能关闭或降级。相同 Project 即使经过旧 Core、Collaboration 或 Execution 入口并省略规划字段，`task.create`、`task.claim`、`execution.start`、`tool.request`、`tool.dispatch` 也会被持久范围检查拒绝。

| 命令 | 候选结果 |
| --- | --- |
| `mission.propose` | Mission v1 |
| `team.propose` / `team.revise` | Team 初版或下一候选版本 |
| `blueprint.propose` | 含完整 Task DAG 的 Blueprint v1 |
| `blueprint.change.request` | 绑定最新候选基线的完整新版本和影响分析 |
| `task.propose` | 向目标 Blueprint 提交新 Task 子资源，生成 Change Request 候选 |

`task.propose` 的 `target_id` 是 Blueprint ID；CAS 使用 Blueprint aggregate revision。内容引用另用 `{type, id, version, content_digest}`，不能拿 aggregate revision 代替内容版本。旧候选只保留，不改写；`supersedes` 关联历史，`active_version` 始终为 `null`。正式 `team.activate`、`blueprint.activate`、`blueprint.apply`、`mission.activate` 返回 `ENFORCEMENT_UNAVAILABLE`。

Team 支持 flat/network/adaptive。Role 和 Contract 表示职责、所需能力与建议，不授予 Policy 权限；Manager 名称没有特权。候选缩编保留 Agent 身份和直接通信权。Role 协作图可以成环，Task DAG 必须无环；跨 Blueprint Task 边目前拒绝。

每次 DAG 新增或修改都校验全图，包括重复、自依赖、间接环、悬空引用、milestone 和引用版本。Task 依赖区分当前 Blueprint 内的 Task 与固定提案 revision/digest 的 Decision。影响分析推导变动及下游任务、关联 Artifact/Decision/依赖和成员；费用、延迟、风险是提案者声明。

读取 API：

```python
candidate = service.candidate(project_id, "blueprint", blueprint_id,
                              authenticated_actor_id=actor_id)
preview = service.preview(project_id, blueprint_id,
                          authenticated_actor_id=actor_id)
```

返回候选副本，不能由调用者修改持久事实。`preview` 只展示结构顺序、当前 Decision 授权和失效原因，永远返回 `claimable_task_ids=[]`、`execution_readiness="unavailable"`。暂停期间已配置项目可保存提案。规划材料始终为 `untrusted_input=true`、`authority=proposal_only`；已激活 Decision 的来源也不能使候选自动获批。

候选 ID 和引用上限为 512 UTF-8 字节；每个对象最多 64 候选版本，Team 最多 32 成员/角色、128 契约/接口，Blueprint 最多 128 Task 和 64 milestone。金额为有限 `0..2**63-1`，confidence 为 `0..1`，布尔值不能代替数值。

Replay 从 Event 重新计算结果，并将规划效果绑定此前 receipt 的请求摘要、身份、地址和终结记录。旧 Event 格式保持；含 governance/planning 的缓存通过完整事实重建，性能和多宿主部署未验证。

示例入口：`Docs/development/evidence/2026-09-13-m3-01-demo.py`。传入未使用的 `m3-01-...` 名称可生成独立 SQLite、仅含 Command/Event 的 SQLite、JSON 和中文说明。它使用确定性本地身份夹具，没有真实模型调用；不构成 TEST-028、正式 Task COMPLETED 或 Mission Acceptance。

验证：`python -m unittest discover -s tests/m3 -t . -v`，运行前设置 `PYTHONPATH=src`；现有 recorder 会自动设置。规范/边界与验收证据见同日 M3-01 设计、计划和固定候选报告。
