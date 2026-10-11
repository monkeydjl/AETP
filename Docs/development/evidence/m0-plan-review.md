# M0 首批执行计划复核

- `reviewed_at`: `2026-09-06`
- `reviewer`: 当前协调 Agent（文档一致性复核，非产品行为验收）
- `status`: `recorded`

## 复核范围

文件：`Docs/superpowers/plans/2026-09-06-m0-first-slice.md`

检查了六个 Task 的文件写集、Interfaces、RED/GREEN 命令、证据路径、M0 边界与退出条件。

## 发现与修正

1. 原文“所有公开接口在 Task 1 中定义”会与后续 Task 自己定义 `CommandHandler`、`Projection`、`RuntimeRecovery` 等接口产生歧义；已改为“Task 1 定义共享模型/存储字段契约，每个后续 Task 先定义自己的接口”。
2. 计划示例中的 `task_create_command`、`clear_projection_for_test_only`、`run_two_processes_against_same_sqlite_file`、`run_demo_flow` 等名称此前没有来源；已新增 `tests/m0/support.py` 测试夹具契约，并将生产 State 清理明确排除在外。
3. Command Handler 示例原先没有显式传入受信 actor；已统一为 `handle(command, *, authenticated_actor_id=...)`，避免把 Command 内的 actor 字段误当作认证来源。
4. Projection、Conformance 和 RuntimeRecovery 示例补充了对应导入；A2A、Manager、真实外部效果仍明确不进入 M0。

## 复核结论

- 每个 Task 均有明确文件范围、接口、失败命令、成功命令和证据目标。
- M0 只包含五核心对象、事务事实链、幂等/版本/恢复/纯 Replay 和无副作用模拟；Review、Verification、Approval、Integration、Mission Acceptance 留到后续里程碑。
- 计划没有新增 Manager 角色，没有将 A2A 变为必需依赖，也没有把文档检查当作产品 Conformance。
- 仍需 M0 开始后由不同 Agent 审查实现与测试证据；本复核不能替代独立产品验收。
