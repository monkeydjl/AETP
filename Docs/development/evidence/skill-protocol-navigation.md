# Skill 应用证据：aetp-protocol-navigation

- `skill`: `skills/aetp-protocol-navigation/SKILL.md`
- `tested_at`: `2026-09-06`
- `agent`: Mill (`01a07535-69d0-7ea3-b87d-5453b341684b`)
- `verification_status`: `recorded_application`
- `independent_of_preparation_writer`: `true`
- `mode`: 只读规范检索；未修改产品源码或运行时

## 场景

评估两个有风险的提议：

1. 要求 Reviewer 先接管作者的 Task 才能审查。
2. 要求所有 Agent 提案必须经过 Manager 中转。

## Skill 应用结果

- Reviewer 接管不是审查前置条件。Lease 限制执行写入，不授予通用指挥权；独立 Review/Verification 可针对不可变 Artifact、内容摘要和输入快照提交。
- Manager 是可选协调职责，不是通信、提案或成果提交必经路径；Agent 可以直接发言、回复、质疑和提案。
- 建议使用 `expected_revision`、Command 校验、内容快照和确定性冲突检测，不能添加隐藏的层级或中转步骤。

## 定位结果

- Agent 平等与直接通信：§§1.1、1.5、3（P1）、5.11、8.5、13.1。
- Lease、Review 与 Verification 边界：§§7.6、10.2、10.3、14.1。
- 对应不变量：`INV-004`、`INV-008`、`INV-017`。
- 对应验收：`TEST-003`、`TEST-008`、`TEST-015`、`TEST-028`。

## 未覆盖与限制

- 该记录验证导航和判断是否命中规范，不是产品行为的 Conformance 通过证据。
- `ClaudeLink` inbox/resource 接口在当前工具面不可用，未进行跨客户端同步。
- 仍需在 M1/M3 以可执行夹具验证“无 Manager 直聊”和“不接管 Task 的独立审查”。
