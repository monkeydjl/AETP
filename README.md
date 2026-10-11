# AETP · AI Engineering Team Protocol

**一个想法 → 平等 Agent 直接讨论 → 形成方案 → 协作产生成果。**

本仓库当前处于设计与开发准备阶段，尚无产品实现。Agent 没有上下级；Manager 可选，不能成为通信、提案或审查的必经路径。

## 从这里开始

1. AI 开发者先读 [AGENTS.md](AGENTS.md)。
2. 查 [开发准备入口](Docs/development/README.md)：环境、Skills、知识索引、进度、验证命令。
3. 看 [M0–M3 路线图](Docs/development/roadmap.md)，从 `M0-01` 开始；首批具体步骤见 [M0 首批计划](Docs/superpowers/plans/2026-09-06-m0-first-slice.md)。
4. 规范以 [设计方案](Docs/AETP-设计方案.md) 为准；[补充建议](Docs/AETP-设计方案-补充建议.md) 是背景和实施路线，不是第二套冲突规范。

## 不安装依赖也能检查准备材料

在仓库根目录执行：

```powershell
python tools/devprep.py check
python -m unittest discover -s tests/preparation -v
python tools/devprep.py environment
```

这些命令检查开发资料与本机工具；**不代表产品 Conformance、Runtime 接入或 Bootstrap Acceptance 已通过**。

`Docs/Docs.zip` 为历史归档，不作为当前规范。所有进度以证据为准，不以文档篇数或 Agent 自述代替成果。

