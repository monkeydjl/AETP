# AETP Project Bootstrap（Mission #0「Initialize Project」）设计方案

## 1. 规范定位与背景

依据《AETP-设计方案.md》§15.5、§5.2、§17.2 与核心不变量 INV-019：
正式业务开发之前，AI Team 必须自主完成项目初始化——不是人工准备好环境再让 Agent 写代码，而是由 AETP 协议管理的**第一个真实 Mission（Mission #0「Initialize Project」）**。

Bootstrap 自身完整走 AETP 事实链协议机制：
```text
Mission #0 (Initialize Project)
  └── Blueprint (Bootstrap Plan)
        └── Task DAG (B0 -> B1 -> B2 -> B3 -> B4 -> B5)
              └── Commands -> Events -> Store -> Projections
                    └── Verification -> Mission Acceptance (human_owner)
                          └── BOOTSTRAP_VERIFIED
```

---

## 2. B0–B5 阶段划分与职责契约

### B0 Discovery（环境侦察）
- **目标**：全面侦察运行环境事实（OS、CPU/内存/磁盘、Python/Node/Git/Docker、数据库、网络连接、可用 API 与凭据能力），生成结构化 `Environment Profile`。
- **纪律**：**环境信息必须是 Evidence，不是 Agent 的一句话**。例如「Docker 可用」必须来自真实探针命令输出，经受信任 Verification 标记为 `environment.docker = VERIFIED`（符合冻结区分⑤）。

### B1 Architecture（技术栈与架构决策）
- **目标**：不依赖人工提前写死，由对等 Agent 发起 Architecture Discussion / Meeting 产出 `Technology Selection Decision`（backend / frontend / database / event store / transport / runtime adapters）。
- **纪律**：技术选型是可追溯、可推翻的正式决策事实，由治理策略授权后固定入 Blueprint v1。

### B2 Environment（环境搭建）
- **目标**：按 Decision 拆解 Setup Tasks（目录骨架、存储初始、依赖配置、数据库就绪）。
- **权限边界**：工作区内创建目录/写入配置自动授权；涉及系统提权或破坏性操作严格受控于 Approval。

### B3 Knowledge（知识与能力装载）
- **目标**：
  1. 建立 Project Knowledge Base（规范、AGENTS.md、架构规范、已有代码索引）；
  2. 实例化 Project Knowledge Graph（协议概念、依赖关系、实体节点）；
  3. 装载与验证 Skill 模块（可验证能力模块，遵循 Discovery → Design → Specification → Implementation → Verification 闭环）。

### B4 Infrastructure（基础设施与质量门）
- **目标**：Git 仓库与分支策略声明、CI/测试框架夹具、Lint/Formatter、日志可观测性与迁移策略。

### B5 Verification & Acceptance（Bootstrap 终验）
- **目标**：**Bootstrap Acceptance**。逐项核验 `environment`、`dependency`、`build`、`test`、`git`、`knowledge` 准则，全部通过后生成固定版本证据。
- **终验门禁**：遵循 Mission Acceptance（§5.2 / INV-019），必须由拥有 `human_owner` 角色的主体执行最终 `mission.complete`，核验全部 criteria 为 `PASSED` 后，Project 的 phase 进入 `BOOTSTRAP_VERIFIED`（非改变基础 Project status）。

---

## 3. 核心领域对象与状态流转

```text
Project (status=planning, phase=preparation)
   │
   ▼ mission.propose ("mission-0-bootstrap", success_criteria=[B0..B5])
Mission #0 (status=proposed)
   │
   ▼ mission.activate (human_owner)
Mission #0 (status=active)
   │
   ▼ team.propose & blueprint.propose (B0..B5 Task DAG)
Team & Blueprint (status=proposed/active)
   │
   ▼ 依次执行 Task 并进行质量验证与受信任核验 (B0 -> B1 -> B2 -> B3 -> B4)
Tasks Completed & Verified
   │
   ▼ mission.acceptance_start (human_owner)
Mission #0 (status=acceptance)
   │
   ▼ mission.verify (逐项校验 B0_discovery_verified ... B5_acceptance_verified 为 PASSED)
All Criteria PASSED
   │
   ▼ mission.complete (human_owner)
Mission #0 (status=completed)
   │
   ▼ bootstrap.finalize
Project (phase=BOOTSTRAP_VERIFIED, bootstrap_status=verified)
```

---

## 4. 验收准则

1. `bootstrap_criterion_01` (Full Protocol Traceability): Bootstrap 完整走 Command → Event → Projection 事实链，不直接改写运行时状态；
2. `bootstrap_criterion_02` (B0-B5 Complete Coverage): 具备完整的 B0 侦察、B1 选型、B2 环境搭建、B3 知识图谱与 Skill 装载、B4 基础设施、B5 终验验证；
3. `bootstrap_criterion_03` (Evidence-based Assertions): 所有环境声明均持有结构化命令探针证据输出，非口头断言；
4. `bootstrap_criterion_04` (Human Owner Gated Completion): 最终 Bootstrap 验收严格由 `human_owner` 授权完成，使 Project 进入 `BOOTSTRAP_VERIFIED`；
5. `bootstrap_criterion_05` (Deterministic Replay): 整个 Bootstrap 产生的全部事件流在纯 SQLite 存储上纯重放一致。
