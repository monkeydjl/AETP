# Skill 应用证据：aetp-execution-contracts

- `skill`: `skills/aetp-execution-contracts/SKILL.md`
- `tested_at`: `2026-09-06`
- `verification_status`: `pending_independent_application`
- `static_check`: `passed`（由 `python tools/devprep.py check` 报告）
- `behavioral_application`: `not_claimed`

## 待验证压力场景

外部创建资源的调用超时，返回结果为 `UNKNOWN`。提议使用新的幂等键重试；同时在 Replay 阶段重新调用 `Runtime.start`；两个进程依靠本机锁竞争认领。

## 预期导航结论（待独立 Agent 复核）

- 超时后的重试沿用原 Command 和幂等键；先查询/对账，禁止盲目创建新资源。
- 事务只能持久化待执行意图，不能包住不可回滚的外部调用。
- Replay 只消费 Event，不调用模型、Shell、`Runtime.start` 或工具。
- Lease/epoch 与认领必须在持久化提交处确定性校验，不能用单机进程锁替代跨进程边界。
- 预期对应 §§7.6、13.4、13.9、14.1、14.4；`TEST-005`、`TEST-006`、`TEST-017`、`TEST-019`、`TEST-020`、`TEST-021`、`TEST-022`、`TEST-026`。

## 未覆盖与限制

- 当前只完成了 Skill 文件静态入口检查；没有把静态检查当作行为通过。
- 已请求独立 Agent 做只读应用检索，但该请求因 `429 Too Many Requests` 未返回结果；因此 PREP-003 仍为 `todo`。
- 尚无 Runtime、外部副作用、UNKNOWN 对账或跨进程竞争的产品实现证据。

## 独立只读应用复核（Mill）

- 复核者：Mill（`01a07535-69d0-7ea3-b87d-5453b341684b`）；日期：2026-09-06；方式：读取 Skill、原始设计文档、backlog/status 与证据，不修改共享文件。
- 结论：`pending`。Skill 的执行方向正确，但这份准备材料不能替代 Runtime、UNKNOWN 对账或跨进程竞争的产品夹具，因此不得写成产品 Conformance 通过。
- 规范定位：§§14.1、14.2（Command、幂等、事务与 Event 消费幂等）；§§13.4、13.10（Source of Truth、纯 Replay 与恢复）；§§13.9、14.4（Runtime 边界、外部 UNKNOWN）；§§7.6、7.10（Lease epoch 与权威 Task）。
- 精度修正：已在 Skill 中补充“本机进程锁只能作优化，不能替代持久化事务/版本检查/Lease fencing”，并增加逐子场景映射：`UNKNOWN → TEST-020/026`、`Replay → TEST-005/021`、`响应丢失 → TEST-017`、`跨进程认领 → TEST-006/019`、`旧 epoch → TEST-022`。
- 未覆盖：尚无 Runtime、外部副作用、UNKNOWN 对账或跨进程竞争产品实现证据；`PREP-003` 仍需后续复核确认，且不能将本条记录误作产品行为通过。

## 接续复核尝试（记录于 2026-09-06T22:42:03.6891324+08:00）

- 本轮通过当前会话多 Agent 工具复用 Mill（`01a07535-69d0-7ea3-b87d-5453b341684b`），请求对修正版 Skill 做只读检索与场景应用；不是 ClaudeLink 通信。
- 初次请求与一次重试均以 `stream disconnected before completion: Our servers are currently overloaded. Please try again later.` 结束，没有返回可采用的独立结论。
- 该失败是复核工具的服务可用性问题，不是 Skill 场景通过或失败的证据；既不沿用旧的 pending 判断为新 pass，也不虚构产品夹具。
- 本文件 `verification_status=pending_independent_application`、`behavioral_application=not_claimed` 保持不变；依赖完成和独立应用复核仍待后续确认。

## 2026-09-08 准备级独立复核与接纳（取代前述 pending）

- 工作项：PREP-003；记录时间：2026-09-08T21:39:28.471232+08:00；当前准备级状态：`done`。
- 执行者：主会话 Codex；独立复核者：Kant（`01a07cac-b6db-7393-ae38-bce13d69c67d`），与执行者不同；早先报告的 Codex 别名是同一个 reviewer。
- 权威证据：`Docs/development/evidence/2026-09-08-prep-corrections-review.json`；全部三项验收条件为 `preparation-level pass`，场景答复、规范定位、实际命令/退出码/时间及 SHA-256 在报告中。
- F-001 已关闭：纯 Projection Replay 不派发外部效果；恢复查询/对账必须遵守当前权限、凭证、审批、预算与派发屏障，不能混同于重放外部效果。
- 静态准备复现：`python Docs/development/evidence/2026-09-08-preparation-corrections-probe.py`；实际 exit 0 与时间见 `2026-09-08-preparation-resume-validation.json`。准备检查不代替独立应用复核。
- 本条只取代旧准备级 pending，不抹去旧错误或服务失败；不是产品行为通过。产品 0%，Conformance 28 registered / 0 passed，Bootstrap not_started。
- 下一步：PREP-008 独立总审查；不得据此启动 M0 或放宽授权。
