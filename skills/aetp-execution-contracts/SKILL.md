---
name: aetp-execution-contracts
description: Use when implementing or reviewing AETP Command handling, Event Store transactions, projections, Replay, idempotency, leases, external effects, Runtime adapters, or Workspace boundaries.
---

# AETP 执行契约参考

本 Skill 只帮助定位和应用已批准的执行边界；它不是安全能力、权限授予或已通过 Conformance 的证明。改动前读 `Docs/AETP-设计方案.md` 的规范原文，并将适用测试写成可执行夹具。

## 不可跳过的事实链

```text
受信 Agent/Human/System → Command
  → actor / permission / expected_revision / idempotency 校验
  → 原子 Event Store 提交
  → State Projection
```

Agent 不直接写 State 或制造 Event。Event 历史不可变；`sequence` 由 Sequencer 赋值；Projection 可删除并由 Event 重建。Orchestrator 不得保存 Event Store 外的权威调度状态。

## 幂等与冲突

同一作用域 `(project_id, authenticated_actor_id, idempotency_key)` 的同键同内容返回原结果；同键不同规范化内容拒绝为 `IDEMPOTENCY_CONFLICT`。超时后的重试沿用原 Command，不用新 key 假装新业务意图。`expected_revision` 在最终提交处检查，冲突时新建表达修订意图的 Command，不改旧 Command。

## 外部效果与恢复

数据库事务只持久化待执行意图，不能包住不可回滚的外部调用。外部结果为 UNKNOWN 时查询/对账，禁止盲目新建 key 重试；纯 Replay 不调用模型、Shell、Runtime.start 或工具。旧 Lease epoch 的迟到报告只能留档，不能推进任务或合并成果。


## 跨进程认领的强制边界

本机进程锁最多只能作为性能优化或减少无效竞争的提示，不能替代 Event Store/数据库事务中的持久化版本检查、Lease fencing 或提交时条件写入。多个进程必须在共享持久化事实源上竞争；锁丢失、进程崩溃或锁实现不可用时，仍必须由提交边界拒绝旧版本或旧 epoch，不能把“本机锁成功”当作安全证明。

## 压力场景到验收映射

| 子场景 | 必查原则 | 对应定位 |
| --- | --- | --- |
| 外部调用超时为 `UNKNOWN` | 先查询/对账，沿用原 Command 与幂等键，禁止盲目新 key 创建 | §14.4；`TEST-020`、`TEST-026` |
| 纯 Projection Replay | 只消费历史 Event 重建 Projection，不调用模型、Shell、`Runtime.start` 或工具，不重新派发历史外部动作 | §§13.4、13.10；`TEST-005`、`TEST-021` |
| 恢复中的查询/对账 | 先完成重建并保持派发屏障，再受控查询 Session / Binding、对 UNKNOWN 对账；无法安全确认则阻塞，复查当前权限、凭证、审批与预算后，仅在 Project 非 PAUSED 且恢复条件满足时开放派发；不盲目重发 | §§13.10、14.4；`TEST-012`、`TEST-020`、`TEST-026` |
| 提交后内部响应丢失 | 原 Command 重试得到原结果，不制造第二个业务意图 | §§14.1、14.2；`TEST-017` |
| 两进程并发认领 | 共享持久化提交处做版本/Lease 条件检查，本机锁不能替代 | §§7.6、14.1；`TEST-006`、`TEST-019` |
| 旧 Lease epoch 迟到报告 | 只留档，不推进 Task、不合并成果 | §7.6；`TEST-022` |
## Lease、审查与边界

Lease/Binding 限制执行写入，不等于审查资格；Reviewer 不必接管作者 Task。Runtime Adapter 必须验证可信 actor、当前 Binding、Workspace 范围、暂停屏障和能力；越界或缺少 Enforcement 时拒绝，不以“本地测试通过”代替真实边界。

## 快速定位

| 场景 | 原文 | 验收 |
| --- | --- | --- |
| Command、事务、幂等 | §§14.1–14.2 | TEST-001、016–019 |
| 外部副作用、UNKNOWN | §§13.9、14.4 | TEST-020、026 |
| Replay、恢复 | §§13.4、13.10 | TEST-005、012、017、021、025 |
| Lease / epoch | §§7.6、7.10 | TEST-006、019、022 |
| Review / Verification | §§10.2–10.3 | TEST-003、008、015 |
| Workspace / Adapter | §13.9 | TEST-014、016、026 |

## 交付前问题

1. 这次写入是否有 Command、受信 actor 和 expected revision？
2. Event 批次是否原子、不可变、幂等，并能重放？
3. 是否存在外部 UNKNOWN、旧 epoch、暂停或跨进程竞争？
4. 运行时和 Workspace 边界是否真实执行，而非仅在提示词中声明？
5. 没有对应的失败夹具时，不称为兼容或完成。

