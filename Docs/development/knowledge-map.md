# AETP 知识图谱导览

更新：2026-09-06。`knowledge-graph.json` 是**开发期可追溯索引**，不是运行时事实源；权威规范仍是 `Docs/AETP-设计方案.md`。

## 核心链路

```text
用户想法
  → 平等 Agent 直接 Message / Discussion
  → Decision / Blueprint
  → Task（Command → Event Store → Projection）
  → Artifact → Review → Verification
  → Integration Gate / Mission Acceptance
  → 成果交付
```

Orchestrator 只提供确定性基础设施与恢复，不是隐藏的领导 Agent。Agent 的 Role 是职责/能力标签，不产生上下级或通信特权。A2A 仅是可选 Transport Adapter。

## 按问题查找

- **平级协作**：§§1.1、1.5、3 P1、5.11、8.5、13.1；`INV-008`；`TEST-015`、`TEST-028`。
- **事实链与重放**：§§10.4、13.4、13.10、14.1–14.2；`INV-005`、`INV-011`、`INV-014`、`INV-015`、`INV-016`、`INV-021`；`TEST-001`、`TEST-005`、`TEST-012`、`TEST-017`、`TEST-021`。
- **Task 执行/审查**：§§7.3、7.6、7.10、10.2–10.3、10.6；`INV-004`、`INV-017`；`TEST-003`、`TEST-006`、`TEST-008`、`TEST-009`、`TEST-019`、`TEST-022`、`TEST-024`。
- **审批/高风险**：§§9.3–9.7、14.11；`INV-006`、`INV-010`、`INV-020`；`TEST-004`、`TEST-007`、`TEST-011`、`TEST-023`、`TEST-027`。
- **外部效果与执行边界**：§§5.13、13.5、13.9、14.3–14.4；`INV-012`、`INV-013`；`TEST-014`、`TEST-016`、`TEST-020`、`TEST-026`。
- **版本/变更/冲突**：§§9.2、11.1–11.5、14.8–14.9；`INV-005`、`INV-007`；`TEST-018`、`TEST-022`、`TEST-023`、`TEST-024`。
- **开发前 Bootstrap**：§15.5、§17.2、§18.1–18.3、补充建议 §3；`TEST-001`–`TEST-028` 的实现状态均应以证据为准。

## 图谱规则

每个节点有稳定 `id`、`type`、`label`、`source` 和摘要；每条边必须指向已登记节点，并写明 `relation` 与来源。索引可以不覆盖所有实现细节，但不能发明规范中不存在的 Entity、INV 或 TEST。源章节变化时，先复核本文件、JSON 和 backlog 的映射，再更新摘要。

主要关系：`defines`、`contains`、`constrains`、`verified_by`、`implements`、`depends_on`、`optionally_uses`、`produces`、`reviews`、`hands_off_to`。
