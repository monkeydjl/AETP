---
name: aetp-protocol-navigation
description: Use when changing or reviewing AETP protocol entities, task states, agent relationships, communication permissions, or architectural boundaries and the governing sections or acceptance tests need to be located.
---

# AETP 协议导航与变更影响

这是项目规范的参考索引，不取代原文或授予变更权限。所有路径从仓库根目录解析；只加载与当前问题有关的章节。

## 查找表

主规范：`Docs/AETP-设计方案.md`。其 §§16、16.1、18.3 分别定义不变量、十一条冻结区分和 Conformance 要求。

| 问题 | 原文章节 | 必查约束 / 验收 |
| --- | --- | --- |
| Agent 平等、Manager 是否必经、直接对话 | §§1.1、1.5、3、5.11、8.5、13.1 | INV-008；TEST-015、TEST-028 |
| Reviewer 是否必须取得作者 Task 归属 | §§7.6、10.2、10.3、14.1 | INV-004、INV-017；TEST-003、TEST-008、TEST-015 |
| 新增顶层对象还是子资源 | §§4.2、4.3 | 19 个实体封顶；Lease / Checkpoint 等不是新顶层 Entity |
| Task 状态、Integration 与 Mission 验收 | §§7.3、10.3、10.6、5.2 | INV-004、INV-017、INV-019；TEST-009、TEST-010、TEST-024 |
| 变更、撤销、替代与历史 | §§9.2、11.1–11.5、14.2 | INV-005、INV-007；保留旧版本与溯源 |
| Runtime / Transport / Workspace 边界 | §§2.4、5.13、7.10、13.9 | TEST-013、TEST-014、TEST-016、TEST-026；A2A 可选 |
| 里程碑是否可以缩减要求 | §17.2；补充建议 §3 | M0–M2 仅有限阶段，最终基本设定由 TEST-028 检验 |

## 输出一个可复核的影响单

读命中的原文后，列出：需求、当前规范、受影响的实体/不变量/命令/事件、需要补的有效与无效夹具、覆盖工作项，以及是否改变用户基本设定。具体编码方案可选，不把这张表变成新增协议规则。

`Docs/development/knowledge-graph.json` 可按稳定 ID 查关系；`Docs/development/backlog.json` 可按 `conformance_tests` 找工作项。两者都是开发期派生资料，不是运行时事实源。

示例：有人要求“Reviewer 先接管 Task 才能审查，以减少冲突”。定位 §§7.6、10.3、14.1 与 TEST-015：执行 Lease 限制的是执行写入，不是独立审查的资格。应测试“审查者不接管 Task 也能提交受校验 Review”，而非加一个 Reviewer 抢占步骤；普通讨论不绕经 Manager。

## 易混淆处

- 平级不等于不校验 Command，不等于绕过人类治理。
- 临时记录者/协作者不等于领导 Agent；工具会话关系不决定产品角色等级。
- 图谱边、旧 ZIP 和补充建议里的历史“建议”不覆盖主规范。
- 原文不足以决定时写出歧义及备选，不发明不存在的 INV 或 TEST 编号。

改动后同步图谱来源、受影响计划与测试映射，并运行 `python tools/devprep.py check`；通过只说明资料一致，不说明协议行为正确。
