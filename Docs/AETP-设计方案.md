# AETP 设计方案

**AI Engineering Team Protocol**

- 版本：v0.1（Draft / Architecture Freeze Candidate）
- 类型：多 Agent 协作与自主软件工程协议
- 领域：Multi-Agent Software Engineering
- 治理模式：Human-in-the-loop / Autonomous
- 更新日期：2026-09-05
- 内容来源：第一轮至第十七轮设计对话，第十八轮文档一致性评审，第十九轮架构边界修订、第二十轮基本设定确认与执行契约修订的汇总整理，逐轮溯源见附录 A

## 修订记录

| 版本 | 日期 | 说明 |
| --- | --- | --- |
| v0.1 | 2026-09-02 | 依据 14 轮设计对话汇总成稿：项目定位与背景调研（1）、协议边界与设计原则（2–3）、协议架构与核心实体（4）、组织 / 规划 / 协作 / 治理 / 执行五层机制（5–10）、变更恢复与记忆（11–12）、运行时架构（13）、协议底层机制（14）、标准工作流（15）、核心不变量（16）、版本范围（17）、下一步计划（18） |
| v0.1（规范性修订） | 2026-09-02 | 第十五轮规范性审查并入：Task 状态机扩展集成门禁（7.3）、Integration Gate（10.6）、Mission 验收升 P0（5.2 / INV-019）、输入信任边界（14.11 / INV-020）、失败归因与选型维度拆分（5.6 / 6.4）、会议预算（8.14）、Task `due_at` 与 `CANCELLED` 语义（7.2 / 7.3）、统一 `supersedes`（11.5）、数据分级 Schema 预留（10.1 / 12.1）、INV 扩充至 INV-020 并标注执行层（16）、冻结区分增至十条（16.1）、最小实现分层（17.2）、故障注入增至 13 类（18.2） |
| v0.1（Runtime 对接修订） | 2026-09-02 | 第十六轮审查并入：Runtime Adapter Contract（13.9）、Task 权威归属与执行映射（7.10）、Execution Binding 与 Effective Capability（5.13）、Capability Negotiation 两阶段路由（6.4）、Failure Domain 归因（11.4）、Conformance Test Specification 与冻结前工程顺序（18.3）、冻结区分①升级为四层分离（16.1）、优先级表同步（17.6） |
| v0.1（Bootstrap 修订） | 2026-09-02 | 第十七轮并入：Project Bootstrap 成为协议标准初始化阶段（15.5，B0–B5 + Bootstrap Acceptance）、Mission #0 概念（5.2）、主流程插入 Bootstrap（15.1）、M0 首个真实 Mission 定为 Bootstrap（17.2）、Skill 定义为可验证能力模块（15.5 / 14.6） |
| v0.1（一致性修订） | 2026-09-04 | 第十八轮并入：Approval 委托与事后否决、`on_expire` 与 EXPIRED 升级路径、审批角色枚举（9.3）、Governance Policy 新增 `delegated` 取值（9.5）、Governance Clock（5.1，过期计时在 PAUSED 期间冻结，凭证为例外）、Orchestrator 无状态恢复（13.10 / INV-021，INV 扩充至 INV-021）、新增 `approval.*` 与 `project.resumed` 事件（10.4）、故障注入扩至 15 类（18.2）与 Conformance 扩至 12 例（18.3）；一致性修正：Team Formation 不再占用 Mission 编号（6.1）、17.6 中 P0 序号引用与 P1 计数、轮次计数与附录 A 溯源 |
| v0.1（架构边界修订） | 2026-09-04 | 第十九轮并入（不新增实体，只钉死边界）：协作层与执行层分离、平级不等于无协调者（1.5）、第一阶段改为共享 Project 而非共享 Workspace 的六件事（1.6）、调研对象按层重新归类（1.4）、Runtime 策略改为「通过 Adapter 驱动 Runtime 执行 Task」（13.5）、Adapter 三分与 Workspace Provider 契约、Execution ≠ Session 与 Task ↔ Binding 一对多（13.9 / 5.13）、Agent Initiated Action 正名（8.7）、`Agent ≠ Orchestrator` 立为 P10 与 `Collaboration ≠ Shared Workspace` 立为 P11（3、5.11、13.1）、冻结区分增至十一条（16.1 ⑪）、`protocol/` 新增 runtime-adapter 与 workspace 两篇（18.1）、Conformance 扩至 14 例并新增 `workspace/` 组（18.3）、17.6 新增两项 P1（P1 v0.1 计十五项） |

| v0.1（平级协作与执行契约修订） | 2026-09-05 | 第二十轮：确认「想法 → 平等 Agent 直接讨论 → 方案 → 成果」为基本设定；移除层级团队与 Manager 必经路径（1.1、5.11、6.2、8.5、13.1）；补齐事务与幂等、外部动作 UNKNOWN / 对账、Runtime 强制边界、Lease fencing、审批与验证版本绑定、暂停语义；统一 Task 迁移与 Command 契约；修正 M0 Bootstrap 范围，故障注入扩至 22 类、Conformance 扩至 28 例。实体清单、不变量编号与十一条冻结区分不变 |
| v0.1（开发准备一致性修订） | 2026-09-06 | 补充开发期可追溯索引、M0–M3 工作包、准备检查入口；将 §15.5 的 A2A 关系明确为可选 Transport Adapter（optionally_uses），不改变协议语义或实体清单。 |

## 目录

1. 项目定位
2. 协议边界：AETP 不做什么
3. 设计原则
4. 协议架构分层
5. 组织层
6. 动态组队（Dynamic Team Formation）
7. 规划层
8. 协作层
9. 决策与治理层
10. 执行层
11. 变更与恢复
12. 上下文与记忆
13. 运行时架构
14. 协议底层机制
15. 标准工作流
16. 核心不变量
17. 版本范围
18. 下一步计划
19. 一句话定义
附录 A：设计演进溯源

---

## 1. 项目定位

AETP 是一套**面向 AI 工程组织的 Agent 协作协议**，以及基于该协议实现的**个人 AI 开发基础设施**。

它要解决的不是「让多个 Agent 一起聊天」，而是：

> 让多个使用不同模型、不同 Runtime、不同能力的 Agent，像一个真正的工程团队一样工作。

### 1.1 核心工作方式

```text
用户投入想法
    ↓
多个平等、独立的 Agent 直接交流、质询、提出备选方案
    ↓
形成可追溯的设计方案（Decision / Blueprint）
    ↓
按方案协作执行、互相审查、验证与集成
    ↓
产生成果并验收；需要时继续讨论与修订方案
```

**这是 AETP 不可被后续机制改变的基本设定：Agent 之间没有上下级或主从关系，可以互相直接对话。** 不存在一个必须经过的主 Agent；用户也不需要先把想法写成完整需求、手工拆解任务或指定指挥者。

协议把这条体验映射为 `Idea → Mission → Discussion → Decision / Blueprint → Task → Execution → Artifact → Review / Verification / Integration → Delivery`。系统可先从已登记的少量 Agent 开始讨论，再按能力需要形成或调整 Team；正式组队、完整任务图和 Meeting 不是首次交流的前置条件。具体启动顺序见 6.1、15.1 与 15.5。

**平等不等于能力、职责或资源权限完全相同。** 主持、协调、实施、审查是可分工、可轮换的职责，不产生对其他 Agent 的通用命令权。任何 Agent 都可以提出方案、请求协助、质疑结论并通过协议申请认领任务；Manager / CTO 只能作为可选职责名称，不能成为上级、唯一发言入口或唯一决策者。

权限、审批、Lease 和质量门约束的是资源操作与权威状态的改变，不是普通讨论资格。人类保留关键决策与风险边界的治理权（v0.1 目标仍为 L2），不必参与每条消息或逐个指挥 Agent。

### 1.2 核心理念

> **Agent 负责思考与执行，Protocol 负责协作与秩序，Project State 负责记录事实，人类负责关键决策。**

### 1.3 自主等级

| Level | 描述 |
| --- | --- |
| L0 | 人类亲自指挥每个 Agent |
| L1 | Agent 执行人类下达的具体任务 |
| L2 | Agent Team 自主协作，人类审批关键决策 |
| L3 | Agent Team 自主开发，人类只看里程碑 |
| L4 | 人类只提出想法，AI 团队自行交付产品 |

L4 是项目的最终目标，v0.1 的目标是稳定跑通 L2。

### 1.4 背景：现有方案调研

项目起点是对当时多 Agent 协作开发工具的一次调研：

| 项目 | 多模型 | 独立 Agent | 共享项目 | Agent 间通信 | 定位 |
| --- | --- | --- | --- | --- | --- |
| ClaudeLink | ⭐⭐⭐⭐⭐ | ✅ | ✅ | ✅ | 多个 Coding Agent 组成开发团队 |
| OpenHands | ⭐⭐⭐⭐⭐ | ✅ | ✅ | 部分 | 工程化开发 |
| DeerFlow 2.0 | ⭐⭐⭐⭐ | ✅ | ✅ | ✅ | 通用 Agent 编排 |
| Agent Team | ⭐⭐⭐⭐⭐ | ✅ | ✅ | ✅ | 多模型团队，每个成员都是独立 Root Agent |
| AutoCodeAI | ⭐⭐⭐⭐ | ✅ | ✅ | ✅ | 自动代码流水线 |
| Conclave | ⭐⭐⭐⭐⭐ | ✅ | ✅ | ✅ | 多模型讨论 / 决策 |

这些项目各自解决了问题的一部分，但没有一个给出「AI 工程团队如何围绕一个项目协作」的完整语义：任务怎么派发、意见怎么收敛、决策谁批准、产物怎么验证。这正是 AETP 要补的位置。

**按层归类比按「是不是多 Agent 工具」归类更有用。** 后续对 Codeg 的深入分析（第十九轮）表明，把这些项目一律归入「多 Agent 协作工具」会掩盖它们各自所处的层次，进而让人误以为它们是 AETP 的替代品：

| 项目 | 核心能力 | 所处层 | AETP 可借鉴 / 接入部分 |
| --- | --- | --- | --- |
| ClaudeLink | Agent Communication Mesh | Transport | Agent 间通信 |
| Codeg | Coding Workspace / Runtime 管理 | Runtime + Workspace | Workspace / Worktree / Session / Diff / Review / Merge |
| OpenHands | Agent Runtime / Sandbox | Runtime | Execution / Sandbox 隔离 |
| DeerFlow | Agent Orchestration / Research | 编排（超级 Agent 式） | Research 流程 / Workflow |
| Claude Code | Coding Runtime | Runtime | Coding Execution |
| Codex CLI | Coding Runtime | Runtime | Coding Execution |
| Gemini CLI | Coding Runtime | Runtime | Coding Execution |

结论只有一句：**上表没有一个项目与 AETP 处于同一层。** 它们是 AETP 的传输、运行时或工作区实现，是 Adapter 的对接对象（13.9），不是竞争协议。由此确定的工程方向是**先定死 AETP Core，再为每个工具分别写 Adapter**；反过来让某个工具的现有能力塑造协议，换工具时协议就得跟着重构。

### 1.5 关键架构选择：平级团队，而非超级 Agent

调研中出现了两种根本不同的多 Agent 架构：

```text
A. 超级 Agent + Sub-Agent（DeerFlow 一类）

主 Agent
 ├── 产品分析 Agent
 ├── 架构 Agent
 ├── Coding Agent
 ├── Research Agent
 └── Testing Agent
       ↓
  主 Agent 汇总结果
```

```text
B. 平级独立 Agent 团队（Agent Team / ClaudeLink 一类）

Agent A      Agent B      Agent C
（各自的模型 / 上下文 / 工具 / 权限）
    │            │            │
    └────────────┼────────────┘
                 ↓
      Shared Workspace / Git
```

A 方案里「团队」只是一个 Agent 的内部实现细节：成员没有独立身份，无法各自接入不同模型与权限。B 方案才是「多个真正平级的 Agent 像一个软件公司一样共同开发」。**AETP 选择 B**，并把「每个 Agent 接入不同 API、使用不同模型」作为第一性需求写进协议——这正是 Agent ≠ Model、Role ≠ Agent 两条冻结区分（16.1）的来源。

**但 B 图是调研对象的形态，不是 AETP Team 的定义。** 照抄它会产生一个很贵的误解：

> 「几个 Agent 共享同一个 Git / Workspace，并且能互相发消息，就是一个 AETP Team。」

不成立。共享目录只说明它们看得到同一份代码，不说明它们在同一个组织里工作。AETP Team 的成立条件是**协作事实进入同一份 State**：

```text
协作层  AETP Team

Agent A        Agent B        Agent C
   ↕              ↕              ↕
   └────────── AETP Collaboration ──────────┘
                        │
                   Orchestrator
                        │
                 Command / Event
                        │
                   Project State
```

```text
执行层  Execution Layer

Agent A → Execution Binding → Runtime A → Workspace A ┐
Agent B → Execution Binding → Runtime B → Workspace B ├→ Git（同一 Project）
Agent C → Execution Binding → Runtime C → Workspace C ┘
```

两层分开之后，两个问题各有归属：**「Agent 之间如何协作」由协作层回答**（Message / Meeting / Decision / Task），**「Agent 如何操作代码」由执行层回答**（Execution Binding / Runtime / Workspace / Git）。这是第十一条冻结区分 `Collaboration ≠ Shared Workspace`（16.1）的来源——共享 Workspace 对协作既不充分也不必要：不充分，因为它不产生任何协作语义；不必要，因为各 Agent 完全可以在独立 Worktree 中工作，而这正是 14.8 的推荐默认模式。

**平级不等于无协调者。** 读到「平级 Agent 团队」必然会问：那谁负责调度？答案不是「其中某个 Agent 兼任队长」：

```text
              AETP Orchestrator（Protocol Infrastructure）
                 调度 / 权限 / 状态 / 事件 / 任务 / 恢复
        ┌───────────────┬───────────────┐
        ↓               ↓               ↓
     Agent A ←────→ Agent B ←────→ Agent C
              Agent 间直接协作（第 8 章）
```

Orchestrator 是**基础设施，不是成员**：它没有 Agent 身份、不参与讨论、不做技术决策、不是 Lead Agent，只负责调度、权限、状态、事件、任务与恢复（13.1）。反向约束同样成立——任何 Agent，包括 Manager Agent，都不得获得 Orchestrator 的权限：**`Agent ≠ Orchestrator`**（设计原则 P10）。

### 1.6 通往 v0.1 的路径：先跑通的六件事

完整愿景（丢一个想法 → 开会 → Blueprint → 批准 → 并行开发 → 交付）不可能一步实现。v0.1 之前的第一阶段刻意保持克制，只跑通六件事：

```text
① 多个独立 Agent 接入 AETP
② 每个 Agent 可绑定不同 Model / Runtime
③ Agent 围绕同一个 Project 协作
④ Task / Message / Command / Event 能驱动协作
⑤ 每个 Agent 可拥有独立 Workspace / Worktree
⑥ 执行结果能进入 Review → Verification → Integration
```

其中 ③ 与 ⑤ 是刻意分开的：**共享的是 Project，不是 Workspace。** Project 是协作单位，Workspace 是执行环境（1.5）；`Agent A → Worktree A`、`Agent B → Worktree B` 同属一个 Project 不仅合法，而且是推荐默认（14.8）。⑥ 是这一阶段与「几个 Agent 一起改代码」的分界线——没有 Review → Verification → Integration，跑通的只是并发编辑，不是团队交付。

第一阶段不重新实现 Coding Agent，而是通过 Runtime Adapter 驱动既有 Runtime 执行 AETP Task（13.5）。这六件事跑通之后，才进入协议驱动的完整工作流（第 15 章）。

---

## 2. 协议边界：AETP 不做什么

AETP 是**上层协作协议**，明确不重新发明以下内容：

| 领域 | 复用方案 |
| --- | --- |
| Agent ↔ Agent 底层通信 | A2A（Agent2Agent，v1.0） |
| Agent ↔ Tool / Data | MCP（Model Context Protocol） |
| Agent ↔ 项目指令 | AGENTS.md |
| 代码与版本 | Git |
| LLM 调用 | 各 Provider API |

一句话区分：

```text
A2A   → Agent 怎么和 Agent 说话
MCP   → Agent 怎么使用工具
Git   → 代码怎么保存
AETP  → 整个 AI 工程团队怎么工作
```

AETP 只负责：**AI 工程团队的组织、任务、讨论、决策、审批、执行与生命周期。**

### 2.1 与现有协议的对象映射

| AETP 对象 | A2A | MCP | Git / 文件 | 处理方式 |
| --- | --- | --- | --- | --- |
| Agent | AgentCard | — | AGENTS.md | 扩展 |
| Agent Capability | AgentCard Skill | Tools | — | 扩展 |
| Message | Message | JSON-RPC | — | 扩展 |
| Task | Task | — | Issue / PR | 扩展 |
| Artifact | Artifact | Resource | Git | 扩展 |
| Workspace | — | Roots | Git / FS | 扩展 |
| Project | — | Resources | Repository | AETP 自定义 |
| Team / Role | — | — | — | AETP 自定义 |
| Mission | — | — | — | AETP 自定义 |
| Blueprint | — | Resource | Docs | AETP 自定义 |
| Discussion | Context + Message | — | Docs | AETP 自定义 |
| Meeting | — | — | — | AETP 自定义 |
| Decision | — | — | Docs | AETP 自定义 |
| Approval | — | Elicitation 可辅助 | Git / DB | AETP 自定义 |
| Review | Task + Artifact | Tool 可辅助 | PR | AETP 自定义 |
| Event | Task status | Notifications | — | AETP 自定义 |
| Memory | Context / Artifact | Resources | Files | AETP 自定义 |

### 2.2 AGENTS.md 的定位

明确写入协议：**AGENTS.md 是 Project Instruction Layer，不是 AETP Communication Layer。**

它解决的是「Agent 来到这个项目之后应该知道什么、遵守什么」：项目说明、架构、构建方式、测试方式、规则与禁止事项。许多 Coding Agent（如 Codex）已支持按目录层级发现并合并 AGENTS.md，更深层文件可覆盖上层指导。

因此关系是 **AETP 生成并维护 AGENTS.md**：

```text
/project
├── AGENTS.md
├── backend/AGENTS.md
└── frontend/AGENTS.md
```

五层组合后的完整体系：

```text
A2A         → Agent ↔ Agent
MCP         → Agent ↔ Tool / Resource
AGENTS.md   → Agent ↔ Project Context
Git         → Code Truth
AETP        → Team Organization / Workflow
```

由此带来的开放性：平台不关心 Agent 背后是什么模型，任何 Agent 只要支持 A2A 并实现 AETP 扩展，就可以加入团队。

### 2.3 扩展方式

沿用 A2A 原生对象，仅挂载 `aetp` 命名空间的工程元数据，不另造一套 Agent Card / Message 格式：

```json
{
  "name": "Atlas",
  "description": "System Architect",
  "skills": [
    { "id": "architecture", "name": "System Architecture" }
  ],
  "aetp": {
    "role": "architect",
    "project_roles": ["architecture", "review"],
    "permissions": {
      "code": "write",
      "production": "deny",
      "decision": "propose"
    }
  }
}
```

分工原则：**Transport 负责 Task 的通信与生命周期，AETP 负责 Task 在软件工程组织里的意义。**

### 2.4 Transport Adapter：A2A 不是必需依赖

AETP 不与 A2A 绑定。A2A 是**一种 Transport / Agent Communication Adapter**，而不是 AETP 的前置条件：

```text
AETP
  │
  ├── Transport Adapter
  │       ├── A2A
  │       ├── HTTP
  │       ├── WebSocket
  │       ├── Local IPC
  │       └── Message Queue
  │
  └── AETP Envelope
```

于是两种形态都完全符合 AETP：

```text
本地 Agent      Agent A → Local IPC → Orchestrator
远程 Agent      Agent A → A2A → Remote Agent B
```

这条边界很重要：v0.1 的最小实现完全可以只用进程内调用与 WebSocket 跑通，不必先接入 A2A；而未来接入远程 / 第三方 Agent 时，也只是换一个 Adapter，协议语义不变。上表中「Agent ↔ Agent 底层通信 → A2A」应理解为**默认推荐的远程 Adapter**，而非唯一选项。

---

## 3. 设计原则

### P1 — Agent 是独立参与者

Agent 不是一次 LLM 调用，而是拥有 Identity、Role、Runtime、Model、Capabilities、Tools、Permissions、Memory、Workspace 的实体。所有 Agent 在协作关系上平等；Role、任务归属与审批职责不得解释为上下级，直接对话和提案不依赖 Manager 授权（1.1、8.5）。

### P2 — Communication 与 State 分离

Agent 说「数据库应该用 PostgreSQL」只是意见。只有按策略批准后，经 `Command → Event Store → Projection` 才改变对应的项目事实。

Agent 不允许凭空改变项目事实。Architect 声称「我们已经决定用 PostgreSQL」不成立，必须走 `Proposal → Decision → Approval → Project State Changed`。

协议原则表述：

> **Conversation is not State.**
> **Agent claims are not Facts.**
> **Only verified artifacts and approved decisions can mutate authoritative project state.**

### P3 — Agent Claim ≠ Fact

Agent 声称「测试全部通过」不算通过，必须存在 `Test Artifact → Verification → Task VERIFIED`。

### P4 — 所有重要状态可追溯

```text
Decision → Discussion → Messages → Evidence → Agent
Artifact → Task → Agent → Decision → Blueprint
```

系统必须能回答：「为什么现在的项目状态是这样的？」

### P5 — 人类是最高治理权威

AI 可以分析、提议、执行、审查、推荐；高风险决策由 Governance Policy 决定是否需要人类批准。

### P6 — Runtime 与 Protocol 解耦

协议不关心 Claude / GPT / Gemini / Qwen / DeepSeek / Hermes / Codex，只要 Runtime 实现 AETP Adapter。

### P7 — 默认可暂停、可恢复、可干预

`Running → Pause → Human Intervention → Resume`，人工插手不得丢失上下文。

### P8 — Immutable History

Event、Decision、Approval 不得被静默修改，任何变更都产生新的 Event。

### P9 — Controlled Autonomy

```text
Autonomy ≠ Unlimited Authority
```

### P10 — Orchestrator 是基础设施，不是成员

```text
Agent ≠ Orchestrator
```

平级团队需要确定性调度设施，也可以由成员轮换承担协调职责，但不存在「队长 Agent」。Orchestrator 属于 Protocol Infrastructure：没有 Agent 身份、不参与讨论、不做技术决策、不能被列为 Team 成员，只负责调度、权限、状态、事件、任务与恢复（1.5、13.1）。反向也成立：任何 Agent——包括 Manager Agent——都不得取得 Orchestrator 的权限。

### P11 — 协作在 State 里，不在共享目录里

Agent 之间的协作事实必须经由 Command / Event 进入 Project State。共享同一个 Workspace 或 Git 目录不构成协作语义，独立 Workspace 也不妨碍协作（1.5、16.1 ⑪）。

---

## 4. 协议架构分层

```text
┌──────────────────────────────────────┐
│              Human Layer             │
│          Owner / Approval / UI       │
├──────────────────────────────────────┤
│          Governance Layer            │
│   Permission / Risk / Approval       │
├──────────────────────────────────────┤
│          Organization Layer          │
│   Team / Role / Agent Formation      │
├──────────────────────────────────────┤
│            Planning Layer            │
│ Mission / Blueprint / Task Graph     │
├──────────────────────────────────────┤
│         Collaboration Layer          │
│ Message / Discussion / Meeting       │
├──────────────────────────────────────┤
│           Execution Layer            │
│ Artifact / Review / Verification     │
├──────────────────────────────────────┤
│          Infrastructure Layer        │
│ Command / Event Store / State Store  │
│ Resource Ledger / Credential Broker  │
│ Context Engine / Git / MCP / Runtime │
└──────────────────────────────────────┘
```

横向分层之外还有一条**纵向主线**，把治理、协作与执行串成一条可追溯的链。协议的完整形态是这两张图的合成：

```text
     Organization          Collaboration          Governance
     Team/Role/Agent       Message/Meeting        Decision/Approval
           └─────────────────────┼─────────────────────┘
                                 ↓
                             Planning
                    Mission / Blueprint / Task DAG
                                 ↓
                  Orchestrator（基础设施，非成员，P10）
                                 ↓
                         Command / Event
                                 ↓
            Runtime Adapter / Workspace Provider（13.9）
                                 ↓
        ┌────────────────────────┼────────────────────────┐
   Claude Code                 Codex                  Gemini CLI
        └────────────────────────┼────────────────────────┘
                                 ↓
              Execution：Session / Workspace / Git
                                 ↓
                       Artifact → Review
                                 ↓
                          Verification
                                 ↓
                          Integration
                                 ↓
                       Mission Acceptance
```

读法只有一句：**上半段是 AETP 自己的语义，下半段是外部工具的执行；两段之间只有一个接口——Command / Event 加 Adapter 契约。** 换掉下半段的任何一个工具，上半段不动；这就是 P6（Runtime 与 Protocol 解耦）在整体结构上的样子，也是 1.4 那句「先定死 Core，再写 Adapter」的依据。

### 4.1 实体关系

```text
                     Project
                        │
              ┌─────────┴─────────┐
              ↓                   ↓
             Team              Mission
              │                   │
              ↓                   ↓
            Agent              Blueprint
                                  │
                                  ↓
                                Task
                                  │
              ┌───────────────────┼──────────────────┐
              ↓                   ↓                  ↓
          Discussion            Review            Artifact
              │                   │                  │
              ↓                   └────────┬─────────┘
           Message                         ↓
              │                      Verification
              ↓
           Decision
              │
              ↓
          Approval
```

Event 横向贯穿所有对象，Command 是所有状态变更的入口。其中必须严格区分：**Discussion 是过程，Decision 是结果；Review 是判断，Verification 是证据。**

### 4.2 核心实体清单

| ID | Entity | ID | Entity |
| --- | --- | --- | --- |
| AETP-001 | Project | AETP-011 | Decision |
| AETP-002 | Mission | AETP-012 | Approval |
| AETP-003 | Team | AETP-013 | Artifact |
| AETP-004 | Role | AETP-014 | Review |
| AETP-005 | Agent | AETP-015 | Event |
| AETP-006 | Blueprint | AETP-016 | Intervention |
| AETP-007 | Task | AETP-017 | Command |
| AETP-008 | Message | AETP-018 | Resource Ledger |
| AETP-009 | Discussion | AETP-019 | Verification |
| AETP-010 | Meeting | — | — |

按层归位：

```text
AETP
│
├── Organization
│   ├── Project
│   ├── Team
│   ├── Role
│   └── Agent
│
├── Planning
│   ├── Mission
│   ├── Blueprint
│   └── Task
│
├── Collaboration
│   ├── Message
│   ├── Discussion
│   └── Meeting
│
├── Governance
│   ├── Decision
│   ├── Approval
│   └── Intervention
│
├── Execution
│   ├── Artifact
│   ├── Review
│   └── Verification
│
└── Infrastructure
    ├── Command
    ├── Event
    ├── Resource Ledger
    ├── Credential Broker
    └── Context Engine
```

其中 AETP-017 Command 是 Project State 唯一的写入口（14.1），AETP-018 Resource Ledger 记录成本与配额消耗（14.5），AETP-019 Verification 是客观验证结果的可追踪对象（10.3）。

**实体表到此封顶。** 以下结构虽然在协议中有正式 Schema，但**明确不升格为顶层 Entity**，而是作为 sub-resource、对象字段或 Event payload 存在：

```text
Claim        Message 的一种类型（8.2）
Action       工具调用记录（14.4）
Capability   能力定义（14.6）
Error        统一错误对象（14.9）
Provenance   Artifact 的来源字段（14.7）
Lease        Task 的占用凭据（7.6）
Checkpoint   Task 的执行快照（7.7）
```

原因很直接：继续扩张实体表会让 AETP 逐渐变成 ERP，而不是 Agent 协作协议。

### 4.3 标识符与 Schema 版本

格式 `<entity>_<unique_id>`，例如 `project_01JXYZ`、`task_01JDEF`。ID 必须唯一、不可复用、不随状态变化而改变。

除协议整体版本（`AETP v0.1`）之外，**每个对象还必须携带自身的 Schema 版本**：

```yaml
task:
  schema_version: "0.1"
  id: task_01JDEF
  ...
```

协议版本与对象 Schema 版本解耦：AETP 0.2 中可能只有 `task` 与 `event` 的 schema 升到 0.2，其余保持 0.1。这使后续 Migration 可以按对象逐个进行，而不是整库一次性升级。

### 4.4 四个核心 Graph

协议中的实体关系最终收敛为四张图，它们共同构成系统的核心数据模型：

| Graph | 构成 | 回答的问题 |
| --- | --- | --- |
| Organization Graph | Team → Role → Agent | **谁在工作？** |
| Task Graph | Task → Dependency → Task | **做什么？** |
| Knowledge / Decision Graph | Evidence → Discussion → Decision → Blueprint → Artifact | **为什么这样做？** |
| Event Graph | Command → Event → Event → Event | **实际上发生了什么？** |

```text
                 PROJECT
                    │
       ┌────────────┼────────────┐
       ↓            ↓            ↓
 Organization      Task       Knowledge
    Graph          Graph        Graph
       │            │            │
       └────────────┼────────────┘
                    ↓
                Event Graph
```

前三张图描述**结构与意图**，Event Graph 描述**已发生的事实**。任何时候两者出现分歧，以 Event Graph 为准。

### 4.5 完整数据流视图

本章开头的分层是静态结构，落到实际数据流则是：

```text
                 ┌───────────────┐
                 │     Human     │
                 └───────┬───────┘
                         ↓
                 ┌───────────────┐
                 │   Governance  │
                 └───────┬───────┘
                         ↓
      ┌──────────────────┴──────────────────┐
      │                                     │
 Organization                           Planning
      │                                     │
 Team / Role / Agent                  Mission / Task
      │                                     │
      └──────────────────┬──────────────────┘
                         ↓
                  Collaboration
                         │
               Message / Meeting
                         ↓
                     Decision
                         ↓
                     Execution
                         │
       ┌─────────────────┼─────────────────┐
       ↓                 ↓                 ↓
    Artifact           Tool             Runtime
       │                 │                 │
       └─────────────────┼─────────────────┘
                         ↓
                    Verification
                         ↓
                       Event
                         ↓
                Memory / Knowledge
```

整条链路由以下基础设施承载：

```text
Command            状态写入口
Event Store        事实历史
State Store        当前状态
Resource Ledger    成本与配额
Credential Broker  凭证边界
Context Engine     上下文装配
```

注意 Execution 层同时包含 Artifact、Tool 与 Runtime——**工具调用与产物同级**，两者都必须留下可审计记录（见 14.4）。

### 4.6 核心事实链

前面三张图分别描述结构、关系与数据流。而 AETP 真正要回答的问题只有一个：

> **一个最终交付的软件，是怎么从人类的一句话变成现实的？**

答案是一条完整的、每一环都可追溯的事实链：

```text
Human Intent
     ↓
Mission
     ↓
Proposal
     ↓
Decision
     ↓
Approval
     ↓
Command
     ↓
Event
     ↓
Task
     ↓
Artifact
     ↓
Review
     ↓
Verification
     ↓
Integration
     ↓
Delivery
```

这条链是 AETP 全部设计的收敛点。它同时说明了几件事：

- **没有断点。** 任何一段交付的代码都可以沿链上溯到某一句人类意图，反之亦然。
- **意图与事实分离。** `Proposal → Decision → Approval` 是意图的形成，`Command → Event` 是意图变成事实的那一步。
- **完成与验证分离。** `Artifact → Review → Verification` 三段不可合并，Review 是判断，Verification 是证据；其后的 Integration（10.6）是另一道独立门禁——模块正确不等于集成后正确。

任何新增机制如果无法挂到这条链上，就应当怀疑它是否属于 AETP。

---

## 5. 组织层

### 5.1 Project

顶层工程容器。

```yaml
project:
  schema_version: "0.1"
  id: project_xxx
  name: Example Project
  status: planning
  phase: planning
  revision: 17
  repository:
    type: git
    url: ...
  workspace:
    path: ...
  team_id: team_xxx
  governance:
    mode: selective
```

状态：`PLANNING / ACTIVE / PAUSED / COMPLETED / FAILED / CANCELLED / ARCHIVED`

**Project Clock。** `status` 描述项目是否在运行，而 `phase` 与 `revision` 共同构成项目自身的时间坐标：

```text
Phase 0   Mission          目标确立
Phase 1   Planning         蓝图与任务图成型
Phase 2   Implementation   并行执行
Phase 3   Verification     验证与集成
Phase 4   Delivery         交付
Phase 5   Maintenance      维护与演进
```

`revision` 在 Blueprint 变更、Decision 被推翻、Team 结构调整等结构性事件发生时递增，用来标识"当前这版项目是第几版"。

**Project Phase ≠ Event Sequence。** Event `sequence` 是全局单调递增的事实计数（14.2），不会因为回退而减小；而 Phase 是可以回退的——Phase 3 发现架构问题，项目可以回到 Phase 1，此时 `revision` 递增，`sequence` 继续前进。两者不可互相推导。

**Governance Clock：治理时间与墙钟时间分离。** 一切带过期语义的治理与调度对象——Approval 的 `expires_at`（9.3）、Task Lease 的 `expires_at`（7.6）、Task 的 `due_at`（7.2）——按**治理时间**计时，而不是墙钟时间。项目进入 `PAUSED` 时治理时间冻结，恢复后继续，冻结区间由 `project.paused` / `project.resumed` 事件界定，消费方据此重算过期时刻。

原因是两种时间衡量的东西不同：墙钟时间衡量真实世界过了多久，治理时间衡量**项目在多久之内没有推进**。人类周五暂停项目、周一恢复，若按墙钟计时，回来会看到审批全部 `EXPIRED`、Lease 全部过期、Task 被重新分配一轮——暂停本身制造了一次故障。

唯一的例外是凭证：Credential 的 `expires_in`（14.3）同时受墙钟约束，**暂停不得延长一份短期凭证的实际有效期**。安全边界优先于调度便利，否则「短期 scoped credential」会被一次长暂停变成长期凭证，INV-012 名存实亡。

### 5.2 Mission

项目要实现的战略目标。

```yaml
mission:
  id: mission_xxx
  project_id: project_xxx
  title: Build Example Platform
  objective: |
    ...
  constraints:
    - budget
    - technology
    - deadline
  success_criteria:
    - ...
  status: proposed
```

生命周期：`PROPOSED → APPROVED → ACTIVE → ACCEPTANCE → COMPLETED`，异常态 `CANCELLED / FAILED`。

**Mission 不得仅依据 Task 完成状态进入 COMPLETED（INV-019）。** 进入 `ACCEPTANCE` 后，必须针对 `success_criteria` 逐条产生 Acceptance Verification（10.3），并经 CRITICAL 级人类批准（9.4）才能交付——Task 不能自己宣布 VERIFIED，Mission 更不能自己宣布完成。

项目通常以 **Mission #0「Initialize Project」** 开始：Project Bootstrap（15.5）由 AI Team 自主完成环境侦察、技术栈决策、开发环境、Skills、知识库 / 知识图谱与工程基础设施建设，经 Bootstrap Acceptance 后才进入正式开发。

### 5.3 Agent

```yaml
agent:
  id: agent_xxx
  name: Atlas
  runtime:
    type: claude-code      # codex-cli / gemini-cli / opencode / hermes / custom
    version: "1.0"
  model:
    provider: anthropic
    name: claude-opus
  capabilities:
    - architecture
    - backend
    - testing
  permissions:
    - filesystem.read
    - filesystem.write
    - git.read
    - git.commit
  workspace:
    root: ./backend
    readonly: false
  status: available
```

Agent 拥有独立的 Identity、记忆、上下文、模型、API、工具与权限，是长期存在的团队成员，而非一次调用即消失的实例。

**Agent Identity 与 Model Identity 必须分离：**

```text
Role → Agent → Runtime → Model → Provider
```

例如 `Backend Engineer → Atlas → Codex Runtime → GPT-5.x → OpenAI`。更换模型时 Agent Identity 不变。

### 5.4 Agent 生命周期

```text
OFFLINE → AVAILABLE → RESERVED → WORKING → WAITING
        → BLOCKED → RECOVERING → AVAILABLE
```

另有 `PAUSED / DISABLED / FAILED / TERMINATED`。

区分 `WAITING`（等其他 Agent）与 `AVAILABLE`（没活干）对 Orchestrator 的调度至关重要。

### 5.5 三层权限模型

不要只做 read / write，粒度太粗。

| 层 | 含义 | 示例 |
| --- | --- | --- |
| Capability | Agent 会什么 | `coding` `research` `architecture` `testing` |
| Permission | Agent 能操作什么 | `filesystem.write` `git.push` `task.create` `production.deploy` |
| Authority | Agent 有权决定什么 | `decision.propose` `decision.approve` `blueprint.approve` `project.pause` |

Permission 还应支持**路径级作用域**，让不同 Role 只能改自己负责的目录：

```text
Architect  查看全部 / 修改架构 / 创建任务 / 审核 PR      ✗ 直接改生产代码
Backend    backend/  database/  tests/                  ✗ frontend/
Frontend   frontend/  UI                                ✗ backend/
Reviewer   全部读取 / 运行测试                            ✗ 修改代码（readonly）
Tester     tests/  sandbox / 运行项目 / 提交 Bug          ✗ 修改核心代码
```

Capability 推荐 0~1 评分而非布尔值：

```yaml
capabilities:
  backend: 0.92
  architecture: 0.87
  testing: 0.81
  frontend: 0.34
```

### 5.6 Agent Performance

历史表现独立于 Capability，由系统根据真实工程事件累积形成，**Agent 不得自行修改**。

```yaml
performance:
  backend:
    success_rate: 0.94
    average_review_rounds: 1.4
    average_completion_time: 1080
  architecture:
    success_rate: 0.87
    average_review_rounds: 1.8
```

长期运行会逐渐形成 Agent Reputation / Engineering Reputation，并反向影响后续 Team Formation。

**失败必须归因。** Recovery 与 Performance 事件携带 `failure_cause: capability / infra / dependency / external`。API 限流、欠费、网络中断、Runtime 崩溃属于 `infra`，不计入 capability `success_rate`——与 10.3 中 `INCONCLUSIVE` 不计入失败率是同一思想。否则便宜但不稳定的 Provider 会被系统性歧视，信誉机制反而摧毁多模型这个前提。Selection Score（6.4）引用的是归因后的能力失败率。

**必须防止历史偏见。** 如果 Agent A 一直做 Python，系统就永远不派 Rust 任务给它，它也永远无法积累 Rust 经验。因此 Capability 需要区分三级：

| 类型 | 含义 |
| --- | --- |
| verified capability | 有充分历史数据支撑 |
| estimated capability | 推测值，历史数据不足 |
| experimental capability | 探索性尝试 |

于是 `Rust: 0.42` 的语义不是「不会」，而是「**没有足够历史数据**」。这与 6.4 的 exploration / exploitation 策略配合，使系统能持续发现新的能力匹配。

### 5.7 Agent Resources

能力之外，资源约束同样决定 Agent 是否可被选中：

```yaml
resources:
  concurrency:
    max: 4
    current: 2
  budget:
    daily_limit: 10
  rate_limit:
    requests_per_minute: 30
  context:
    max_tokens: 200000
```

于是 Router 可以在「GPT 很强但 Rate Limit 已满」时自动切换到可用的 Claude 或 Gemini。

### 5.8 Role

Role 定义「当前任务需要什么职责」，与 Agent 彻底分离。

```yaml
role:
  id: role_xxx
  name: Backend Engineer
  required_capabilities:
    - backend
    - api
    - database
  authority:
    - task.propose
```

```text
Role ≠ Agent    Agent ≠ Model    Model ≠ Provider
```

Role 由需求动态产生，而不是系统预先固定。做记账 App 与做自动驾驶仿真系统所需的 Role 完全不同；纯分析类项目可能根本没有 Frontend。Role 表达职责和作用域，不表达职级；任何角色都不能仅凭名称指挥其他 Agent、限制其直接交流或替其认定成果完成。

### 5.9 Agent Contract

Agent 加入 Team 时签订契约，明确它在**当前团队**中的具体工作协议（Role 是职责，Contract 是落地约定）：

```yaml
agent_contract:
  agent_id: agent_001
  team_id: team_001
  role: backend
  responsibilities:
    - implement_api
    - write_tests
    - maintain_backend
  authority:
    can:
      - modify_backend
      - create_branch
      - run_tests
    cannot:
      - modify_architecture
      - deploy_production
  deliverables:
    - source_code
    - tests
    - documentation
  acceptance:
    reviewer_required: true
```

### 5.10 Team

```yaml
team:
  id: team_xxx
  project_id: project_xxx
  mission_id: mission_xxx
  purpose: |
    Build the target system.
  structure:
    mode: adaptive
  roles: [architect, backend, frontend, qa]
  members: [agent_001, agent_002, agent_003]
  lifecycle:
    mode: dynamic
```

### 5.11 团队结构

AETP 的 Agent 关系始终是平级协作关系。结构选项只描述协作拓扑与职责划分，不描述组织职级：

| 结构 | 形态 | 适用 |
| --- | --- | --- |
| Flat | 所有成员可直接交流，按能力认领职责 | 小型项目、工具 |
| Network | 围绕问题、任务和证据动态建立协作关系 | 软件开发、研究、调查 |
| Adaptive | 在平级关系内调整成员、分工与沟通拓扑 | 默认推荐 |

`Adaptive` 不得生成上下级；大型或高风险项目通过明确依赖、独立审查与操作级治理控制复杂度，而不是引入主 Agent。**`Hierarchical` 不是 AETP Team 的合法结构**，此前草案中的 CTO → Architect → 开发者指挥链不再适用。

可以指定或轮换会议主持、协调人与审查者，也可以完全不设置 Manager。职责持有者与其他成员平等，其提案同样可被质疑；没有自动覆盖他人意见或越过质量门的权力。Orchestrator 不属于任何 Team 结构，因为它不是 Agent 成员（P10、13.1）。

### 5.12 Team 生命周期

```text
FORMING → ACTIVE → SCALING → ADAPTING → SHRINKING → COMPLETED
```

### 5.13 Execution Binding

Agent 是长期身份，不等于某一次运行。同一个 Agent 今天用 Codex、明天用 Claude Code；甚至同一 Agent 的不同 Task 可以落在不同 Runtime 上。每一次执行是一次绑定：

```yaml
execution_binding:
  id: binding_xxx
  lease_epoch: 2                # 与 Task 当前 Lease 绑定，见 7.6
  agent_id: agent_atlas
  task_id: task_042
  runtime:
    type: codex-cli          # claude-code / gemini-cli / opencode / hermes ...
  model:
    provider: openai
    name: gpt-5.x
  workspace:
    worktree: ./.worktrees/task-042
  session:
    id: session_182
  credentials:
    via: credential_broker    # 14.3，短期 scoped credential
  resource_limits:
    max_tokens: 200000
    timeout: 45m
```

由此得到冻结区分①的完整形态：**Agent ≠ Model ≠ Runtime ≠ Execution**（16.1）。故障恢复的语义随之清晰——`Atlas → Codex Session #182 → 崩溃 → Checkpoint → Claude Code Session #91 → 继续 Task`：**Agent 没死，只是 Execution Binding 换了**（7.7 Checkpoint 在 Binding 之间传递，不传 Agent 内部状态）。

**Task 与 Binding 是一对多，Binding 与 Session 是一对一。** Binding 在认领或分配时建立，Runtime 启动确认后补录 Session 关联事件；Session 尚未取得不赋予额外执行权。 上面这条恢复链意味着一个 Task 在生命周期里可以经历多次执行，每次一个新的 Binding；`session.id` 是 Runtime 侧的执行上下文标识，登记在 Binding 里供审计与恢复使用，**不是 Task 状态的来源**（13.9）。

**Effective Capability 也由 Binding 决定。** 能力有三个来源——**Agent Capability**（Agent 会什么）、**Runtime Capability**（所在的 Runtime 支持什么操作，13.9）、**Model Capability**（当前模型的强弱项）。Router 看到的不是其中任何一层，而是三者的交集：

```text
Agent Atlas + Claude Code Runtime + GPT-5.x
        ↓
Effective Capabilities
├── architecture
├── code.write
├── shell.execute
├── git
└── test
```

Binding 变化，Effective Capability 随之重算——这就是「Atlas 换 Runtime 后能做什么不同的事」的协议表达。

---

## 6. 动态组队（Dynamic Team Formation）

### 6.1 流程

```text
MISSION
   ↓
MISSION ANALYSIS
   ↓
CAPABILITY DECOMPOSITION
   ↓
ROLE GRAPH
   ↓
AGENT DISCOVERY
   ↓
TEAM PROPOSAL
   ↓
APPROVAL
   ↓
TEAM CREATED
```

正式 Team Formation 可建模为 Mission（`Form Engineering Team`），由一个或多个平等 Agent 承担组队分析职责，而非由上级任命下属。初始讨论和 Bootstrap 使用项目准入策略允许的少量已登记 Agent，不依赖完整组队流程；正式执行团队在 Mission #0「Initialize Project」通过 Bootstrap Acceptance 后组建或扩充（15.5）。**`#0` 这个编号只属于 Bootstrap**，组队 Mission 不占用编号。成员在正式组队前后都可直接讨论、提出候选角色与质疑分工。

### 6.2 Capability Decomposition → Role Graph

先问「完成这个目标需要哪些能力」，再判断哪些必须、哪些可共享、哪些可由同一 Agent 承担、哪些可并行，最后生成 Role Graph（此时仍不是 Agent）：

```text
Product ↔ Architecture ↔ Research / Data / AI
                  ↕              ↕
          Backend ↔ Frontend ↔ Database
                  ↕              ↕
                 QA ↔ Security
```

图中的边表示协作接口，不是指挥或汇报关系；任意两个相关角色都可直接交流，图中未绘出的边不构成通信禁令。交付物依赖另由 Task DAG 表达（7.4），不得从依赖方向推导 Agent 职级。协调与技术综合可以由上述成员兼任，不要求配置 CTO 或 Manager。

### 6.3 Agent Pool 与 Agent 分配

Agent Pool 相当于「人才市场」，每个 Agent 拥有画像（capabilities / cost / speed / reliability / experience / availability）。Role 确定后再做 Agent Assignment，最终形成多模型混编团队：

```text
Team
├── Product      → GPT
├── Architect    → Claude
├── Backend      → GPT
├── Frontend     → Gemini
├── Probability  → Claude
├── QA           → DeepSeek
└── Security     → Qwen
```

一个 Agent 可以承担多个 Role（小项目常见），因此还需要 **Team Size Optimizer**：目标是用最少的 Agent 完成任务。

原因是 Agent 数量与协作成本非线性相关：

```text
Agent 越多 → 通信越多 → Token 越多 → 冲突越多 → 管理复杂度越高
```

默认策略：**最小有效团队。**

### 6.4 Agent Selection

```text
SelectionScore =
    Capability
  × TaskFit
  × Reliability
  × Availability
  − Cost
  − Load
```

（早期草案中公式还含 `× AuthorityFit`，最终 spec 将其归入下方的必须考虑维度，不写入公式本身。）

协议只规定 Router 必须考虑 Capability、Task Fit、Reliability、Availability、Permission、Cost、Latency、Current Load、Historical Performance 这些维度，不强制具体算法。

这些维度**不得揉成一个不透明的总分**。`Capability Performance`（能不能做好，来自 5.6 归因后的成功率）与 `Reliability Performance`（稳不稳定，来自 Provider 可用性与延迟历史）必须分开记录——「这个模型能力最好，但 API 此刻不稳定」与「这个模型做不了这个任务」是两种完全不同的落选原因：前者应选第二名顶替，后者应直接过滤。

落到实现上，**Capability Negotiation 分两阶段——先资格门，后评分**。「谁有资格做」先于「谁更适合做」：

第一阶段（资格门），任一不满足即淘汰：

```text
Task Requirements → Effective Capability 匹配（5.13）→ Permission Check（5.5）→ Resource Check（5.7）
```

第二阶段（评分），对通过资格门的候选计算 SelectionScore：

```text
Task → Capability → Cost → Latency → Availability → Quality → Agent Selection
```

其中 `Cost` 的事实来源是 Resource Ledger（14.5），`Capability` 的定义来源是 Capability Registry（14.6）与 5.13 的 Effective Capability。Agent Router 不只是选择「谁比较聪明」，而是先判断「谁有资格做」。

为避免「模型固化」（所有任务永远给最强 Agent），Router 应支持 exploration / exploitation，例如 80% 选历史最优、20% 尝试其他 Agent，以持续发现更合适的分工。

### 6.5 Agent Discovery

Agent 不应持有全量 Agent 列表，而是按需发起发现请求：

```json
{
  "required_capabilities": ["security-audit", "web-security"],
  "task_type": "review"
}
```

Router 返回候选，由 Router 决定最终人选。这样本地 Agent、远程 Agent、云 Agent、临时 Agent、第三方 Agent 可以统一接入。

### 6.6 动态扩容与 Ephemeral Agent

团队规模随任务演进：

```text
START → GROW → SHRINK → COMPLETE
```

当出现能力缺口时通过 `ROLE_REQUEST` 招募：

```json
{
  "type": "ROLE_REQUEST",
  "role": "Security Engineer",
  "required_capabilities": ["security-audit", "web-security"],
  "duration": "task",
  "priority": "high"
}
```

若 Agent Pool 中没有合适人选，可由 Agent Generator 创建临时 Agent（如 Stripe Integration Specialist），完成任务并通过 Review 后离队。

Agent 离队 ≠ Agent 被删除，其 Memory、Performance、Artifacts、Decisions、Experience 必须全部保留。

### 6.7 Team Evolution

```text
MISSION → TEAM FORMATION → TEAM → EXECUTION → RESULTS
        → PERFORMANCE → TEAM EVOLUTION → NEW CAPABILITIES
        → REPLANNING → TEAM
```

典型演进：初期 Architect / Backend / Frontend / QA；进入数据阶段追加 Data Engineer；上线阶段追加 DevOps、Security；上线完成后释放 Frontend、Product、Architect，仅保留 Operations、Security、Monitoring。

### 6.8 Team Proposal

组队结果以提案形式呈现给人类，包含 Mission、推荐团队与各 Role 的模型及置信度、预估成本、预估工期、风险等级，操作项为 `Approve Team / Modify / Auto Optimize`。开启 Auto Approve 时系统直接开始。

---

## 7. 规划层

### 7.1 Blueprint

Blueprint 是 Mission 的工程实现方案，由 AI 团队讨论产出，是人类第一次介入审批的关键对象。

```yaml
blueprint:
  id: blueprint_xxx
  version: 1
  project_id: project_xxx
  mission_id: mission_xxx
  requirements: ...
  architecture: ...
  technology: ...
  components: ...
  milestones: ...
  tasks: ...
  risks: ...
  acceptance_criteria: ...
  status: draft
```

生命周期：

```text
DRAFT → PROPOSED → REVIEWING → PENDING_APPROVAL → APPROVED → ACTIVE → SUPERSEDED
```

Blueprint 可被新版本取代（v1.0 → Change Request → v1.1 → Approved），**旧版本不得删除**。

### 7.2 Task

工程执行的基本单位。

```yaml
task:
  id: task_xxx
  project_id: project_xxx
  mission_id: mission_xxx
  milestone_id: milestone_xxx
  title: Implement API
  type: development
  status: pending
  priority: high
  assignee:
    agent_id: agent_xxx
    role: backend
  created_by:
    agent_id: agent_xxx
  dependencies:
    - task_xxx
    - decision_xxx
  inputs:
    - artifact_xxx
  expected_outputs:
    - artifact_xxx
  acceptance_criteria:
    - API works
    - Tests pass
  approval_required: false
  due_at: 2026-09-10T18:00:00   # 可选：调度截止时间
  recovery:
    max_retries: 3
```

Task 依赖不限于其他 Task，也可以依赖 Decision。Milestone 在 v0.1 中不是独立顶层实体，而是 Blueprint 的组成字段，Task 通过 `milestone_id` 引用。

`due_at` 与 Lease（7.6）是两种时间：Lease 管活性（Agent 挂了任务不被锁死），`due_at` 管进度。**`due_at` 过期不是 FAIL 条件**，而是产生 `task.overdue` 事件并触发 Replanning 评估（11.3）——deadline 是进度信号，不是熔断器。两者都按治理时间计（5.1）。

### 7.3 Task 状态机

```text
PENDING → ASSIGNED → IN_PROGRESS → READY_FOR_REVIEW
        → IN_REVIEW → VERIFIED → READY_FOR_INTEGRATION
        → INTEGRATING → INTEGRATED → SYSTEM_VERIFIED → COMPLETED
```

异常路径：

```text
IN_PROGRESS → BLOCKED → IN_PROGRESS
IN_PROGRESS → FAILED → PENDING
IN_REVIEW   → REJECTED → IN_PROGRESS
```

终止态另有 `CANCELLED`：Mission 变更需求或 Replanning 后，尚未完成且已无意义的 Task 进入 `CANCELLED` 而非 `FAILED`——它不是失败。`CANCELLED` 必须携带原因，例如 `reason.superseded_by: task_093`（见 11.5），使重规划后的 Task Graph 保持干净可追溯。

**完成规则：** Task 不得从 `IN_PROGRESS` 直接跳到 `COMPLETED`，必须经过 `Artifact → Review → Verification`；`VERIFIED` 之后还必须经过 Integration Gate（10.6）——**VERIFIED ≠ INTEGRATED**，「这个模块是正确的」与「这个模块和整个系统放在一起仍然正确」是两回事。无集成面的单体任务可由 Governance Policy 豁免 Integration 阶段。

**规范性迁移表。** 流程图是摘要，下表与 14.1 的 Command 契约共同定义允许的迁移；表外迁移拒绝。所有事件均由受理 Command 的协议实现产生，Runtime 不能直接选择后态。`RESUMED` 是恢复动作、`RECOVERY` 是恢复流程，不是可持久化的 Task 状态。

| 前态 | 触发与必要条件 | 后态 |
| --- | --- | --- |
| PENDING | 合格认领或接受分配；依赖已就绪，原子建立归属与 Binding / Lease | ASSIGNED |
| ASSIGNED | 当前 Binding 的执行开始报告通过校验 | IN_PROGRESS |
| ASSIGNED | 拒绝分配、释放或交接；撤销旧执行权后重新排队 | PENDING |
| IN_PROGRESS | 提交固定版本 Artifact 并报告执行结束；仅表示待审，不表示完成 | READY_FOR_REVIEW |
| READY_FOR_REVIEW | 创建独立 Review 请求 | IN_REVIEW |
| IN_REVIEW | Review 通过且当前版本的 Verification 为 PASSED（10.3） | VERIFIED |
| IN_REVIEW | Review 要求修改或 Verification 为 FAILED | REJECTED |
| REJECTED | 修订工作被接受；重新检查归属与 Lease | IN_PROGRESS |
| VERIFIED | 需要集成，且质量证据、源与目标版本仍有效 | READY_FOR_INTEGRATION |
| READY_FOR_INTEGRATION | 集成请求获准；锁定源 commit、预期目标 commit 与当前执行权 | INTEGRATING |
| INTEGRATING | 已确认合并成功，记录结果 commit | INTEGRATED |
| INTEGRATING | 已确认冲突或失败、无未知外部结果；记录原因并重新处理 | READY_FOR_INTEGRATION |
| INTEGRATED | 针对结果 commit 的系统 Verification 为 PASSED | SYSTEM_VERIFIED |
| SYSTEM_VERIFIED | 最终复核所有适用质量门、版本和交付关系 | COMPLETED |
| VERIFIED | 确认无集成面，记录 Policy 版本与 `task.integration_exempted`；Review / Verification 不得豁免 | COMPLETED |
| ASSIGNED / IN_PROGRESS / READY_FOR_REVIEW / IN_REVIEW / VERIFIED / READY_FOR_INTEGRATION / INTEGRATED / SYSTEM_VERIFIED | 出现依赖、权限或质量阻塞；记录 `blocked_from` 与原因 | BLOCKED |
| BLOCKED | 阻塞解除，重新检查版本、证据、执行权；恢复到仍有效的 `blocked_from`，否则回到需重做的阶段 | 原阶段或 IN_PROGRESS / PENDING |
| ASSIGNED / IN_PROGRESS | 确认执行失败；与结果 UNKNOWN 区分 | FAILED |
| FAILED | Recovery Policy 允许重试；撤销旧 Binding 后重排 | PENDING |
| 任意有归属的非终止态 | Lease 到期或交接；废止旧代次；先对账在途动作，再保留 Checkpoint 重排 | PENDING |
| 任意非终止态 | 取消获准；撤销执行权，在途动作继续对账 | CANCELLED |

`INCONCLUSIVE` 不推动成功或失败迁移；应保留原阶段或按原因 BLOCKED。系统验证失败保留失败证据并 BLOCKED，修订后重新经过适用质量门。`COMPLETED / CANCELLED` 是终止态；成果事后失效使用有效性标记和替代任务（11.3、11.5），不得改写历史完成事实。任务暂停期间的迁移还受 13.4 的暂停屏障约束。

### 7.4 Task DAG

Task 不是列表而是有向无环图，依赖完成时由 Orchestrator 重算 Task Readiness，从而最大化并行开发。

```text
TASK-001
   ├────────→ TASK-003
   └────────→ TASK-004
                  │
TASK-002 ─────────┘
                  ↓
               TASK-005 → TASK-006
```

关键规则：**Agent 可以自主选择候选任务并提交 `task.claim`，但不能绕过协议宣称拥有任务。** Orchestrator 只按任务依赖、能力、资源和并发规则受理认领或提出分配；分配可被拒绝（7.9），不代表某个 Agent 对另一个 Agent 的命令。

```text
task.completed → Orchestrator → 更新依赖图 → 发布可认领任务
Agent 自主申请 / Task Router 提议 → 校验 → task.claimed / task.assigned
```

项目始终由 Project State 驱动，而非 Agent 的个人判断驱动。

### 7.5 Task Claim / Handoff

不是简单地把 Task 推给 Agent，而是引入认领语义：

```text
Task → CLAIM → Agent → WORK
```

Agent 可执行 `CLAIM` / `RELEASE` / `HANDOFF`。发现自己不适合时应正式 HANDOFF 给他人，而不是留下一句「这个我不会」。

### 7.6 Task Lease

长期无人值守既要避免任务永远锁定在失联执行上，也要避免旧执行恢复后继续行使已经失去的权限：

```yaml
lease:
  owner: agent_a
  binding_id: binding_042_2
  lease_epoch: 2
  expires_at: 2026-09-05T22:30:00  # 按项目治理时间解释
```

`lease_epoch` 是每个 Task 单调递增的执行代次，由 Orchestrator 随归属变更原子分配，不由 Agent 自报生成。续租保持代次；重新分配、交接或创建替代 Binding 时增加代次。Task 的当前归属、Binding 与 Lease 必须在同一事件批次内一致改变。

```text
Lease Expired → 撤销旧执行权 → 对账在途动作 → 分配新 Binding / 新 epoch
旧执行恢复 → 可提交历史报告 → 不得推进当前 Task 或执行新的受控写入
```

认领前不要求持有 Lease；认领成功后的任务执行命令必须携带 `binding_id + lease_epoch`。最终受控写入点（状态提交、成果正式接受、受保护分支更新、外部动作派发）校验当前代次，不能只在消息入队时检查。旧执行返回 `STALE_EXECUTION`；其产物可留档供参考，但不能自动成为当前任务的有效成果。Agent 身份未变也不能绕过检查。

本节 Lease 约束的是当前 Task 的实施归属，不赋予 owner 对其他 Agent 的指挥权。独立 Review / Verification 校验提交者自身的操作权限、适用执行上下文与被审目标快照，不要求审查者接管被审 Task 的 Lease；运行验证工具仍须通过受信 Runner 的独立动作授权（10.3、14.4）。

Fencing 由 Command Handler 与实际资源访问边界共同实施（13.9）。仅发送 stop、检查 owner 或持有短期凭证都不能替代最终代次校验；已经在外部执行的动作无法靠换代次撤回，必须按 14.4 对账。

`expires_at` 按治理时间计（5.1）：项目 `PAUSED` 期间 Lease 不过期。但暂停不恢复已失效的代次，凭证仍受墙钟到期约束；恢复派发前必须重新检查执行权、审批及在途动作。

### 7.7 Checkpoint

避免「连续工作 4 小时后崩溃、全部丢失」。Checkpoint 至少保存：当前 Task 状态、Agent 状态、Git Commit、Artifacts、Decision、Context Snapshot、未完成工作。

```text
Agent A → Crash → Agent B → Load Checkpoint → Continue
```

由此支持**换模型继续干**：Claude Agent 做到 70% 时 API 失效，GPT Agent 读取 Checkpoint 继续完成。

设计理念：**工作属于 Team / Project，不属于某一个模型。**

### 7.8 Task Proposal

Agent 可提出新 Task，但默认不得绕过 Orchestrator 直接修改 Task Graph：

```yaml
task_proposal:
  proposed_by: agent_xxx
  title: Add caching layer
  reason: |
    Current architecture may have performance issues.
  impact:
    architecture: medium
  affected_tasks: [task_003, task_007]
```

```text
Agent → TASK_PROPOSAL → Impact Analysis → Orchestrator
      → 是否影响 Blueprint？
        ├── 否 → Task Created
        └── 是 → Blueprint Change Request
```

### 7.9 Task 拒绝与阻塞

`ASSIGNED` 不意味着 Agent 必须接受，能力不匹配时可 `TASK_DECLINED`：

```json
{ "reason": "insufficient_capability", "required": ["kubernetes", "devops"] }
```

遇到依赖缺失时应标记 `BLOCKED` 并给出结构化原因，而不是陷入死循环：

```json
{ "reason_type": "DEPENDENCY", "blocking_tasks": ["task_021"] }
```

依赖任务完成后的 `task.completed` 事件触发阻塞重评估；只有全部阻塞条件解除，且版本、执行权及证据仍有效时，才按 7.3 恢复。项目 PAUSED 时只记录与评估，不自动恢复执行（13.4）。

### 7.10 Task 的权威归属与执行映射

接入外部 Runtime 后，同一个「任务」会在多个系统中各有投影：

```text
AETP Task          task_001「实现 Market Data Service」
   ├── runtime_binding    → Runtime Task（Codeg / Codex 会话任务）
   └── transport_binding  → A2A Task（远程委托时）
```

规则只有一条：**AETP Task 是工程语义上的权威 Task，Runtime Task 与 A2A Task 都是执行映射**（与 2.3 的分工原则一致：Transport 负责 Task 的通信与生命周期，AETP 负责 Task 在工程组织里的意义）。状态的唯一写入口是 AETP 状态机（7.3）：Runtime / A2A 侧的状态变化通过 Runtime Adapter（13.9）上报为报告类 Command，由协议校验后产生 Event 并映射回 AETP Task，不允许反向覆盖。否则接 Codeg、OpenHands、DeerFlow 时，会出现三个系统都认为自己拥有 Task 状态的问题。

---

## 8. 协作层

### 8.1 五层通信职责分离

这是整个系统最核心的技术决策：**「说话」和「留下资料」必须分开。**

```text
              Message Bus
                   │
       ┌───────────┼───────────┐
       ↓           ↓           ↓
    Message      Task        Event
       │           │           │
       └───────────┼───────────┘
                   ↓
             Shared State
                   ↓
          Knowledge Base
          Documents / Git
```

| 层 | 职责 |
| --- | --- |
| Message | 交流（意见、提议、质疑） |
| Task | 工作的载体 |
| Event | 触发与系统事实 |
| Document | 长期记忆 |
| Git | 事实（代码） |

本地文件只能作为 Artifact / Context / Project Memory，**不能作为唯一通信机制**。推荐链路：

```text
Agent → AETP Message → Event Bus → State Store → Context Engine → Agent
```

### 8.2 Message

```yaml
message:
  id: msg_xxx
  sender:
    agent_id: agent_xxx
  recipients:
    - agent_yyy
  channel: architecture
  type: proposal
  content: |
    ...
  references:
    - decision_xxx
    - msg_xxx
  context:
    project_id: project_xxx
    task_id: task_xxx
    discussion_id: discussion_xxx
  timestamp: ...
```

类型：`QUESTION / PROPOSAL / CLAIM / CHALLENGE / AGREEMENT / DISAGREEMENT / EVIDENCE / CLARIFICATION / REQUEST / RESPONSE / NOTIFICATION`

按语义归为六类：

```text
Opinion        主观判断，可以被质疑
Question       信息请求
Proposal       行动建议，可以进入 Decision 流程
Claim          事实断言，必须能被验证
Request        请求他人行动
Notification   状态通报
```

带 `target_message` 与 `evidence` 的质疑消息示例：

```json
{
  "message_type": "CHALLENGE",
  "content": "这个方案无法满足实时查询要求。",
  "target_message": "msg_103",
  "evidence": ["artifact_22"]
}
```

消息类型同时服务于 UI 语义（Challenge / Agreement / Proposal / Risk 可用不同视觉标识区分）。

**Claim 的标准结构。** `Artifact ≠ Claim` 是协议的冻结区分之一（16.1），但此前 Claim 只是一个概念。既然 Agent 会不断说"我做完了"、"测试通过了"、"这个 API 是幂等的"，Claim 就必须有可判定的结构：

```yaml
claim:
  schema_version: "0.1"
  id: claim_xxx
  actor:
    agent_id: agent_backend_001
  statement: "Auth module implemented and all tests pass."
  target:
    task_id: task_042
  evidence:
    - artifact_051
  status: unverified
```

`status` 只有三个取值：`unverified / verified / refuted`。

```text
Claim
  ↓
Verification（10.3）
  ↓
Verified Fact
```

**Claim 不是顶层 Entity**，它是 Message 的一种类型。这样处理的原因是：Claim 的价值全部在于"它能不能被 Verification 消掉"，而不在于它自己有生命周期。一个永远停留在 `unverified` 的 Claim，在协议里等价于没有发生——它不能推动 Task 进入 VERIFIED（INV-003）。

### 8.3 AETP Envelope

Transport 层（A2A / HTTP / WebSocket / Local IPC / Message Queue，见 2.4）负责把消息送到，AETP Envelope 负责说明「这条消息在 AI 工程组织里是什么意思」。所有 AETP 消息统一封装：

```json
{
  "protocol": "AETP",
  "version": "0.1",
  "message_id": "msg_123",
  "project_id": "project_001",
  "sender":   { "agent_id": "architect" },
  "receiver": { "agent_id": "backend" },
  "type": "TASK_REQUEST",
  "payload": { "task_id": "task_034" },
  "context": {
    "mission_id": "mission_001",
    "decision_id": "decision_012"
  },
  "timestamp": "..."
}
```

Envelope 使消息自带工程语境（属于哪个项目、哪个 Mission、依赖哪个 Decision），这正是原生 Transport Message 无法表达的部分。Envelope 同样用于承载 Command（14.1），此时 `type` 为对应的 Command 名。

### 8.4 引用与回复链

Message 必须支持引用，使讨论形成可追溯的链条而非平铺的聊天记录：

```text
Message #183  Architect: API 应该采用 REST
        ↓ reply
Message #191  Backend: 我认为 GraphQL 更适合……
        ↓ reply
Message #194  Architect: 根据 #191 的意见，我重新评估……
```

任一参与 Agent 都可以据此提出 Decision Proposal；可轮换的记录者或协调者负责汇总意见与引用，而非替团队拍板。按 8.13–8.16 与第 9 章形成的 Decision 落盘为知识库文档（如 `/docs/decisions/032-api-architecture.md`）。

### 8.5 通信规则与通道

**项目内已准入的 Agent 可以互相直接对话、回复、质询、发起 Discussion 和提出方案，不需要 Manager 转发或批准，也不需要先拥有 Task。** 传输可经共享消息设施，但逻辑上是成员之间的直接交流；Orchestrator 不是讨论对象或意见裁决者。

消息优先定向发送给相关成员或主题频道；确需全员知晓时可以广播。速率、预算与敏感数据范围按公开的项目策略约束，对相同条件的 Agent 一视同仁，不得按「上级 / 下级」设置发言权。会议的限时独立分析阶段可暂不互看答案（8.10），但不能变成永久的角色通信隔离。

普通 Message 不需要走任务执行审批，也不得作为外部工具授权。只有把讨论结果变为正式 Proposal、决定、任务归属或其他权威事实时，才进入相应 Command 校验与事件链；被引用为依据的发言需按 14.10 固化。

通道类型：`DIRECT / TASK / DISCUSSION / MEETING / TEAM / SYSTEM / HUMAN`

项目内可按主题划分频道，Agent 按需订阅：

```text
#general  #architecture  #backend  #frontend  #research  #qa  #incident
```

支持 `@mention` 定向：消息中出现 `@backend` 时创建定向 Message，而不是广播。

### 8.6 Subscription

这是控制 Token 消耗的关键机制。不能让所有 Agent 一直「在线聊天」——10 个 Agent 全量广播上千条消息会迅速撑爆上下文。

每个 Agent 只接收自己关心的内容：

```yaml
architect:
  subscribe:
    - architecture.*
    - decision.*
    - task.failed
    - project.*

backend:
  subscribe:
    - backend.*
    - api.*
    - architecture.approved
    - task.assigned

frontend:
  subscribe:
    - frontend.*
    - api.*
    - architecture.approved

qa:
  subscribe:
    - code.merged
    - build.*
    - deployment.*
```

原则：**不是所有 Agent 都需要知道所有事情。**

### 8.7 Assistance Request

Agent 不能私下调用另一个 Agent，必须走协议：

```yaml
assistance_request:
  id: request_xxx
  from: agent_backend
  required_capabilities: [probability, statistics]
  task_id: task_xxx
  reason: |
    Need independent verification.
  urgency: normal
```

由 Agent Router 负责寻找协助者。

**这是 Agent Initiated Action 的标准形态，不是一个边缘补充机制。** 协议要成立的最终形态不是 `Human → Orchestrator → Agent` 单向下发，而是 Agent 在执行中发现问题后主动拉起协作：

```text
Backend Agent 发现「Migration 与当前 Schema 冲突」
        ↓  assistance_request（本节）
Architecture Agent 接手分析
        ↓  subscription（8.6）
Security Agent 主动加入
        ↓
Discussion（8.8）→ Meeting（8.9）→ Decision（9.1）
        ↓
Task Replanning（11.3）
```

因此协议明确：**Message、Assistance Request、Task Proposal、Replanning 触发都允许 Agent 作为发起方**，不限于 Orchestrator 下发。Orchestrator 在这条链上的角色是路由与校验，而不是持有发起权——它不能因为「没有人给它下命令」就压掉一个 Agent 的求助。缺了这一条，系统只是一个任务分发器，不是团队。

约束仍在原处，不因主动发起而放松：发起本身是一条 Command，要过 Permission 校验（14.1）；由此产生的 Task 与 Decision 照常受风险分级与审批约束（9.4）；带 `untrusted_input` 标记的发起自动升级审批等级（14.11）。**主动权在 Agent，授权边界在协议。**

### 8.8 Discussion

围绕一个问题的结构化消息集合。

```yaml
discussion:
  id: discussion_xxx
  topic: Database Architecture
  participants: [architect, backend, data]
  status: open
```

生命周期：`OPEN → SYNTHESIZING → CLOSED`

### 8.9 Meeting

有明确目标、参与者、流程和输出的结构化协作过程，是 AETP 的重点设计之一。

```yaml
meeting:
  id: meeting_xxx
  topic: Architecture Review
  objective: |
    Determine system architecture.
  moderator:
    agent_id: agent_xxx
  participants: [agent_xxx, agent_yyy]
  rounds:
    - individual_analysis
    - debate
    - synthesis
  output:
    decision_id: decision_xxx
```

状态机：

```text
CREATED → OPEN → INDIVIDUAL_ANALYSIS → DEBATE
        → SYNTHESIS → DECISION_PROPOSED → CLOSED
```

DEBATE 阶段内部包含两个动作：**交叉质询**（Architect ↔ Backend，Security → Everyone）与**方案竞争**（如方案 A PostgreSQL、方案 B PostgreSQL + Redis、方案 C ClickHouse + PostgreSQL，各 Agent 分别论证）。SYNTHESIS 阶段由参与者共同检查证据，并由任一提案者或轮换记录者汇总技术合理性、成本、复杂度、风险、项目目标与各方意见，生成可被质疑的 Decision Proposal。主持人只管理议程，不拥有额外决定权；Meeting 是结构化讨论选项，不是所有成员交流的必经入口。

### 8.10 Independent Analysis

第一轮**必须**独立作答，Agent 不得看到其他 Agent 的答案，以避免群体偏见（第一个 Agent 的观点带偏全场）：

```text
Question
   ├──→ Agent A
   ├──→ Agent B
   ├──→ Agent C
   └──→ Agent D
          ↓
   Independent Results
          ↓
        Debate
```

### 8.11 Evidence

必须区分意见与证据。「我认为 Redis 不适合」是 Opinion；「压测显示 Redis 在当前 workload 下 P99 达到 430ms」是 Evidence。

```yaml
evidence:
  id: evidence_xxx
  type: benchmark
  source:
    artifact_id: artifact_xxx
  claim: |
    Redis configuration X causes...
  confidence: 0.94
```

层级：`Opinion → Evidence → Inference → Recommendation → Decision`

于是辩论从「Claude 觉得 A，GPT 觉得 B」升级为基于 Evidence 的对比与综合。

### 8.12 Opinion Weight

不同专业领域的 Agent 意见权重不同（架构问题上 Architect 0.9、安全问题上 Security 1.0）。但权重**不是投票权或职级**，而用于 Evidence-weighted synthesis。证据质量与适用领域可以影响推荐理由，不能剥夺其他 Agent 的提案、反对或复核权；简单多数票不适用于专业分工场景。

### 8.13 Consensus

Consensus Engine 输入 Opinions、Evidence、Agent Expertise、Project Goals、Constraints、Risks，输出：

```yaml
consensus:
  recommendation: PostgreSQL
  confidence: 0.86
  supporting_agents: [architect, security]
  concerns: [scalability]
  unresolved: [...]
```

**Consensus 只是 Recommendation，不是 Decision。** 即使 100% Agent 同意，也不代表系统状态已改变。

### 8.14 会议终止条件

防止 Agent 无限争论：

```yaml
meeting_policy:
  max_rounds: 3
  consensus_threshold: 0.80
  no_new_evidence_rounds: 2
  token_budget: 100000
  time_budget: 20m
```

另有 `moderator_decision`、`human_intervention`。满足任意条件即进入 SYNTHESIS。`token_budget` 与 `time_budget` 是成本护栏：会议是系统里最贵的协作行为，成本约随「参与者² × 轮数」增长，任一预算耗尽必须强制收敛，账单由 Resource Ledger（14.5）归集。过程发言按 14.10 走 Ephemeral，只有产出的 Decision / Evidence 进入 Event Store。

### 8.15 Disagreement 而非强制共识

不强制达成共识——真实工程团队也并非事事统一。允许记录少数意见：

```text
Decision
Consensus: 0.62
Position:  Agent A → A, Agent B → B, Agent C → A
Minority Opinion: Agent B → B
Risk: Medium
```

反对意见被**永久记录**，日后出问题可以追溯「当时其实有人反对」。

### 8.16 Consensus 失败与升级

无法达成共识时，任何 Agent（包括协调者、Manager / CTO 职责承担者）都不得凭角色名称「随便选一个」：

```text
CONSENSUS_FAILED → ESCALATION
```

按风险升级：

| Risk | 升级对象 |
| --- | --- |
| LOW | 未参与该提案的合格同行复核；可做受限实验补充证据 |
| MEDIUM | 按 Policy 选择独立同行审查并通知人类；仍无可执行结论则请求人类裁定 |
| HIGH | Human |
| CRITICAL | Human |

这里的「升级」是增加证据、独立审查或请求人类治理，不是向上级 Agent 汇报。无充分依据时保留 Disagreement，不得伪造共识。

这也为 Human-in-the-loop 提供了真正的触发机制——系统只在需要时叫人，而不是每一步都问。人类看到的是结构化决策请求：冲突问题、可选方案、失败原因、风险等级、受影响任务数、推荐选项，操作项为 `Approve A / Choose B / Ask Agents Again`。

---

## 9. 决策与治理层

### 9.1 Decision

```yaml
decision:
  id: decision_xxx
  title: Database Selection
  proposal:
    choice: PostgreSQL
  alternatives: [MongoDB, SQLite]
  reasoning: ...
  evidence:
    - artifact_xxx
  proposed_by:
    agent_id: agent_xxx
  risk_level: medium
  status: pending_approval
```

生命周期：

```text
PROPOSED → REVIEWING → PENDING_APPROVAL ──→ APPROVED → ACTIVE
                                       └──→ REJECTED
```

人类修改时走 `PROPOSED → MODIFIED → REVIEWING`，**不得覆盖原 Decision**，每次修改都留下历史。

### 9.2 Decision Reversal

Decision 并非永远正确。事实变化时不修改原决策，而是新建决策取代它：

```text
Decision #12 → Challenge → Reevaluation → Decision #21 → Supersedes #12
```

项目由此形成 **Decision Graph**。

### 9.3 Approval

治理层的授权对象。

```yaml
approval:
  schema_version: "0.1"
  id: approval_xxx
  target:
    type: decision
    id: decision_xxx
    revision: 3
    content_digest: sha256:decision_revision_3_digest
  scope:
    action: decision.activate
    arguments_digest: sha256:canonical_arguments_digest
  policy_version: governance_7
  requested_by:
    agent_id: agent_architect_001
  authority:
    type: human
    required_role: human_owner
  approver:
    type: human
    id: human_owner_001
  delegated_to:                  # 可选：实际代批主体
    type: agent
    id: agent_reviewer_001
  revocable_until: ...           # 委托批准后人类仍可否决的窗口
  status: pending
  expires_at: ...                # 治理时间（5.1），PAUSED 期间不计
  on_expire: escalate            # escalate / reject / renew
```

`target.type` 是一个受限枚举，而不是自由字符串——审批对象的类型直接决定审批权限如何路由：

```text
decision        技术或架构决策（9.1）
blueprint       蓝图变更（11.1）
deployment      部署与发布
budget          预算追加（14.5）
credential      凭证授权（14.3）
task            高风险任务执行
team            Team 组建或结构调整（6.8）
mission         Mission / Bootstrap Acceptance（5.2 / 15.5）
```

`requested_by` 是发起审批的一方，`approver` 是权限归属方，`delegated_to` 是可选的实际代批主体。发起者不得与实际批准者相同：未委托时检查 `requested_by ≠ approver`，委托时检查 `requested_by ≠ delegated_to`，并验证委托权限与作用域。委托可以改变谁来批，不能取消「发起与批准分离」。

`expires_at` 对应 `EXPIRED` 状态：审批请求不能无限期悬挂。审批按动作风险与作用域分工——低风险由策略自动放行，中风险可由独立同行审查者批准，高风险必须人类批准。审批职责不是对其他 Agent 的上下级权力，不能限制其讨论或提案。

状态：`PENDING / APPROVED / REJECTED / EXPIRED / REVOKED`

**审批委托与事后否决。** 审批职责按 Governance Policy（9.5）委托时必须留痕：`delegated_to` 记录实际代批主体，并产生 `approval.delegated` 事件。委托有两种模式：

```text
事前委托    低于阈值的动作由 Policy 指定的合格同行代批，人类不逐次参与
事后否决    Agent 先批准放行，人类在 revocable_until 之前仍可否决
```

事后否决落为 `REVOKED`，而**不是回改原 Approval**——已经放行的动作可能产生了 Artifact 与 Event，撤销的正确表达是一次新的治理行为，附带 Impact Analysis（11.2），必要时触发 Replanning（11.3）。CRITICAL 级审批（9.4）不得委托：任何模式下都必须由人类行使。

**多审批者。** `delegated_to.type` 可以是 `agent` 也可以是 `human`——个人基础设施长大后自然会出现第二个人（所有者 + 协作者），委托模型对人和 Agent 是同一套。`authority.required_role` 因此也是受限枚举：

```text
human_owner          最终治理权威，CRITICAL 级只接受它
human_collaborator   可批 HIGH 及以下
agent_reviewer       可批 MEDIUM 及以下，仅限 Policy 明示的动作与作用域
independent_reviewer 按 8.16 承接独立复核，不代表职级或通用决定权
```

这样「多人治理」不需要另建一套 RBAC，仍由 Governance Policy（9.5）一处描述。

**审批绑定的是不可变快照，不是可变对象名称。** `target.revision / content_digest` 固定被批准内容，`scope.action / arguments_digest` 固定动作与参数范围，`policy_version` 固定授权依据。摘要由受信实现对规范化内容计算；示例中的可读摘要仅用于说明字段，真实值必须使用完整算法摘要。审批记录本身不可改写。

执行前必须重新核对目标版本、摘要、参数范围、有效期、撤销状态与当前 Policy。目标或执行参数改变需新 Approval；Policy 变化需重新评估并留下结果，无法证明原授权仍适用则重新申请。重放历史只恢复当时的批准事实，不等于获得再次执行许可。自动放行也必须记录规则版本与作用域；它是确定性规则的结果，不是提案 Agent 自我批准。

`mission` 审批必须绑定 Mission 的 success_criteria 版本、候选交付物摘要与 Acceptance Verification 集合，CRITICAL 级只接受 human_owner。事后否决只阻止后续动作并触发影响分析，不能撤销已发生的不可逆外部效果；该类效果按 14.4 对账。

**EXPIRED 不是终点。** 审批走到 `expires_at` 时必须有确定的后续路径，否则审批人长期不在线会让项目静默卡死。`on_expire` 三种取值：

```text
escalate   产生 approval.expired + approval.escalated，按 Risk Level（9.4）重新路由（默认）
reject     视为拒绝，Decision 回到 REVIEWING（9.1）
renew      按原条件重新发起，仅允许有限次数
```

HIGH / CRITICAL 的 `escalate` 目标仍然是人类——不存在可以代人类批 CRITICAL 的主体。此时 escalate 的实际含义是提升通知等级，并把受阻的 Task 显式标记 `BLOCKED`（7.9），使卡点在活动流（13.8）里可见。协议只禁止一种行为：**过期之后什么都不发生。**

### 9.4 Risk Level

所有高影响操作必须带风险等级。

| 等级 | 示例 | 默认处理 |
| --- | --- | --- |
| LOW | 修改普通代码、运行测试、创建文档、安装依赖、Git commit | 自动执行 |
| MEDIUM | 增加依赖、修改 API、修改数据库结构、大规模重构 | Agent Reviewer + 通知人类 |
| HIGH | 修改核心架构、生产部署、大规模删除代码 | 人工审批 |
| CRITICAL | 删除生产数据、资金操作、账户操作、购买服务、发送公开消息、不可逆外部操作 | 强制人工审批 |

MEDIUM 对应的「通知」语义是：系统告知人类「Agent 建议修改 X，因为 Y」，人类可选择**批准 / 拒绝 / 修改**，但不阻塞流程等待。这一层是「完全自动」与「必须审批」之间的中间态。

### 9.5 Governance Policy

```yaml
governance:
  mode: selective
  rules:
    - action: code.write
      approval: auto
    - action: git.commit
      approval: auto
    - action: git.push
      approval: auto
    - action: architecture.change
      approval: decision_based
    - action: dependency.add
      approval: delegated          # 委托代批（9.3）
      delegate: agent_reviewer_001
      revocable_within: 7d         # 事后否决窗口
    - action: production.deploy
      approval: human
    - action: database.drop
      approval: human
```

`approval` 取值：`auto / decision_based / delegated / human`。`delegated` 必须同时给出 `delegate` 与 `revocable_within`，落到 Approval 对象上就是 `delegated_to` 与 `revocable_until`（9.3）。CRITICAL 级动作（9.4）不允许配置为 `auto` 或 `delegated`——Policy 校验期即拒绝，而不是运行时才发现。

### 9.6 自主模式

| 模式 | 行为 |
| --- | --- |
| Manual | 关键操作均需人类批准，适合初期测试 |
| Selective | LOW 自动、MEDIUM 交 Agent Review、HIGH 交人类（**默认模式**） |
| Autonomous | Agent Team 自主执行所有被 Policy 授权的工作 |

即使在 Autonomous 模式下，生产部署、删除数据、支付、账户操作、外部不可逆操作仍受 Governance Policy 约束。用户说「这个项目完全托管」在实现上只是 `autonomy: autonomous`，底层安全规则依然生效。

### 9.7 Intervention

人类可在任何允许的位置介入，标准动作：`PAUSE / STOP / REDIRECT / MODIFY / RESUME / OVERRIDE`

```yaml
intervention:
  schema_version: "0.1"
  id: intervention_xxx
  actor:
    type: human
    id: human_owner_001
  target:
    type: task
    id: task_xxx
  action: pause
  reason: "Change architecture direction."
  command: command_001
  impact: high
```

**Intervention 本质上也是一个 Command。** 人类的介入同样必须经过校验才能改变状态，不存在绕过 Command 直达 State 的特权通道：

```text
Human Intervention
      ↓
Command（14.1）
      ↓
Validation
      ↓
Event
```

那为什么还保留 Intervention 这个独立 Entity？因为它承担的是 Command 不承担的语义：**这是一次人类治理行为**。`command` 字段指向实际执行的那条 Command，`impact` 记录这次介入的影响面。Command 记录"系统做了什么"，Intervention 记录"人为什么要这样做"——治理审计需要后者。

介入不是简单 kill Agent，而是走完整链路：

```text
Intervention → Command → Event → Agent PAUSED → Impact Analysis → Task Updated → Resume
```

---

## 10. 执行层

### 10.1 Artifact

实际工程产物。

```yaml
artifact:
  id: artifact_xxx
  type: code
  task_id: task_xxx
  created_by:
    agent_id: agent_xxx
  source:
    type: git
    repository: ...
    commit: a82f310000000000000000000000000000000000
```

类型：`CODE / DOCUMENT / DESIGN / SCHEMA / REPORT / TEST_RESULT / BUILD / BINARY / DATASET / CONFIGURATION`

**Artifact 身份对应不可变内容。** Git 类型必须解析为完整 commit / tree 标识，不能以可移动 branch / tag 充当验证目标；其他类型必须保存内容摘要与可读取的不可变快照。修改内容创建新 Artifact，并通过 `derived_from / supersedes` 关联旧产物，不得在原 ID 下换内容。Review、Verification 和 Approval 引用的摘要由受信存储或执行设施计算，不能仅采信 Agent 的文字报告。

Artifact 还必须携带来源关系字段（`derived_from` / `produced_by` / `reviewed_by`），使产物可反向追溯到决策与证据，详见 14.7。

Artifact 预留 `data_classification: public / internal / sensitive / restricted` 字段（仅 Schema 预留，v0.1 不宣称完整的数据分级强制策略）。本地 Runtime 也可能调用远程模型，不能以「进程在本机」推断数据没有出域；执行环境必须声明实际模型端点与网络出口，restricted 数据在没有可验证出口限制时不得交给该执行环境。Context Package 装配时经 Data Classification Filter 按级裁剪（12.1），为未来远程 / 第三方 Agent 接入预留数据出域边界——与 14.3 是同一思路，从凭证延伸到数据。

### 10.2 Review

Review 不是 Message，而是正式工程行为。写代码的 Agent 不能自己宣布完成。

```yaml
review:
  id: review_xxx
  target:
    type: artifact
    id: artifact_xxx
  reviewer:
    agent_id: agent_xxx
  criteria: [correctness, security, architecture, testing]
  status: pending
```

结果：`APPROVED / CHANGES_REQUESTED / REJECTED`

同一产物可由多个 Agent 从不同视角并行审核：

```text
Artifact
   ├──→ Reviewer      (correctness)
   ├──→ Security      (vulnerability)
   ├──→ QA            (testing)
   ├──→ Performance   (efficiency)
   └──→ Architecture  (consistency)
              ↓
        适用 Review 通过 → Verification → Integration Gate
```

任一参与 Agent 或轮换协调者可汇总 Review 结果并请求 Integration（10.6）；是否放行由协议检查有效 Review、Verification 与目标版本，不由 Manager 个人裁决。

### 10.3 Verification（AETP-019）

Verification 是**协议的正式实体**，不是 Review 的一个字段，也不是一句结论。

```yaml
verification:
  schema_version: "0.1"
  id: verification_xxx
  target:
    type: artifact                # artifact / mission
    id: artifact_051
    content_digest: sha256:artifact_051_digest
  inputs:
    source_commit: a82f310000000000000000000000000000000000
    test_suite_digest: sha256:test_suite_digest
    environment_digest: sha256:runner_environment_digest
    criteria_ref:
      type: task                  # task / mission
      id: task_042
      revision: 3
      content_digest: sha256:acceptance_criteria_digest
  method:
    type: automated_test
    command: "pytest -q"
    test_authorship: [agent_test_001]
  execution:
    action_id: action_verify_052
    binding_id: binding_qa_002     # 属于 Task 的验证执行自身的 Binding，不是被测 Task 的 Lease
    runner_id: trusted_runner_001
  verifier:
    agent_id: agent_qa_001
  evidence:
    artifact_id: artifact_052
  result: PASSED
  timestamp: ...
```

`method.type`：`automated_test / build / lint / type_check / integration_test / security_scan / runtime_check / manual_inspection`

`result`：`PASSED / FAILED / INCONCLUSIVE`

必须基于可验证事实：Build、Test、Lint、Type Check、Integration Test、Security Scan、Runtime Check。**Agent 的自然语言声明不能单独作为 Verification**——声明属于 Claim（8.2），Claim 只能被 Verification 消解。

`evidence.artifact_id` 是硬性要求：Verification 必须指向一份可复查的产物（测试输出、构建日志、扫描报告）。没有 evidence 的 Verification 与 Claim 无异。`INCONCLUSIVE` 存在的意义是让"没跑起来"与"跑了但失败"区分开——前者不能计入失败率，也不能推动状态前进。

**Review ≠ Verification。** 这是第六条冻结区分（16.1），两者不可互相替代：

| | Review | Verification |
| --- | --- | --- |
| 性质 | 主观判断 | 客观事实 |
| 主体 | 有能力评判的 Agent 或人 | 可执行的验证方法 |
| 输出 | 意见 | 证据 |
| 典型表述 | "代码看起来没问题" | "184 / 184 tests passed，build exit code = 0" |
| 如何复核 | 重新审查并保留意见历史 | 按方法复跑 / 复查并生成新记录，不在 Event Replay 中执行 |

完整链路：

```text
Artifact
   ↓
Review          有人看过并认可
   ↓
Verification    有证据证明它真的能工作
   ↓
Task VERIFIED
   ↓
Integration → System Verification（无集成面须记录 Policy 豁免）
   ↓
Task COMPLETED
```

Review 通过但 Verification 失败，Task 不得进入 VERIFIED；Verification 通过但 Review 未过，同样不得进入。这正是 `COMPLETED ≠ VERIFIED` 得以落地的机制：Task 状态机（7.3）中的 VERIFIED 必须有一条对应的 Verification 记录作为凭据（INV-017）。

**验证有效性绑定。** 测试类 Verification 必须固定被测代码 / 产物、测试集、运行环境、执行命令和验收标准版本；非测试方法按 method 固定相应检查输入与环境，不能以空值冒充已验证。证据必须保存可复查输出及其内容摘要，由受信执行设施提供运行来源。`INCONCLUSIVE` 不得充当通过，也不得以伪造日志推进状态。

Review 也必须指向同一不可变产物。任务修订、验收标准变化或合并结果改变后，旧 Review / Verification 保留历史，但不能自动证明新版本；可复用与否必须由明确规则检查输入一致性并留痕，否则重新验证。系统级 Verification 固定合并结果 commit，不以可移动的集成分支名为目标。

Mission Acceptance 使用 `target.type: mission`，额外固定 Mission revision、逐条 success_criteria 引用和候选交付 Artifact 摘要集合；每条准则都必须映射到可复查的 PASSED 证据，再请求 9.3 的 mission Approval。

**独立审查与执行授权。** Review / Verification 的提交资格不以拥有被审 Task 为前提。验证工具由受信 Runner 在单次、可撤销、限定快照与动作范围的授权下运行，`execution.action_id` 关联 14.4 的操作记录；属于 Task 的验证执行还必须校验其自身 Binding / Lease，不借用被审 Task 的写权限。人类手动检查须保存经认证的检查人与过程证据，不伪造自动 Runner 记录。

**测试作者与完成判定分离。** 默认 `Implementation Author ≠ Verification Author`；低风险 Task 允许同一 Agent 生成测试以控制成本，但任何情况下都不得由同一 Agent 单独决定 VERIFIED——作者分离是默认，完成判定分离是底线。

### 10.4 Event

系统事实，必须 Immutable。**Event 只能由受信协议实现根据 Command 的受理、校验和处理结果产生，Agent 不得直接制造 Event**（见 14.1）。请求已受理、外部动作已派发和最终成功是不同事实，不能提前记成功。

```yaml
event:
  id: event_xxx
  type: task.completed
  sequence: 10241
  actor:
    agent_id: agent_xxx
  subject:
    type: task
    id: task_xxx
  causation_id: command_xxx
  correlation_id: task_xxx
  timestamp: ...
  payload: ...
```

`sequence` / `causation_id` / `correlation_id` 的排序与幂等规则见 14.2。

命名规则 `<entity>.<action>`：

```text
project.created / project.paused / project.resumed
mission.created / mission.completed
agent.created / agent.joined / agent.left / agent.failed / agent.offline
team.created / team.updated
blueprint.proposed / blueprint.approved / blueprint.superseded
task.created / task.assigned / task.claimed / task.started / task.blocked
task.completed / task.failed / task.cancelled / task.overdue
integration.started / integration.completed / integration.conflict
discussion.started / discussion.closed
meeting.started / meeting.completed
decision.proposed / decision.approved / decision.rejected
approval.requested / approval.granted / approval.denied
approval.delegated / approval.expired / approval.escalated / approval.revoked
artifact.created / artifact.verified
review.requested / review.approved / review.rejected
verification.started / verification.completed
build.started / build.passed / build.failed
test.started / test.passed / test.failed
tool.invoked / tool.completed / tool.failed
intervention.applied
command.received / command.rejected
execution.started / execution.progress / execution.finished / execution.failed
execution.report_recorded / execution.pause_status_changed
lease.granted / lease.renewed / lease.revoked / lease.expired
execution.bound / execution.unbound
approval.invalidated / verification.invalidated
tool.requested / tool.outcome_unknown / tool.reconciled / tool.cancelled
task.integration_exempted / task.requeued / task.resumed
```

`build.*` 与 `test.*` 是 Verification 的**执行来源**，`verification.*` 是其**结论**——前者说明跑了什么，后者说明判定结果与证据（10.3）。QA 据此判定，而非依赖 Agent 的自然语言声明。`verification.completed` 用 result 区分 PASSED / FAILED / INCONCLUSIVE，并固定输入版本。`tool.*` 是外部动作的审计来源（14.4），`command.rejected` 表示已认证主体的命令被拒绝；未通过认证的请求不借此向项目注入事实。`approval.invalidated / verification.invalidated` 表示旧记录不再适用于当前版本，不修改旧记录；它们不是 Approval / Verification 的新增终态。

上表全部属于 Durable Protocol Event，必须进入 Event Store；Agent 之间的讨论过程不在此列（见 14.10）。

### 10.5 事件驱动架构

```text
task.completed
      ↓
  Event Bus
      ↓
┌─────┼──────────┐
↓     ↓          ↓
Task  Graph    Agent
Engine Update  Performance
      ↓
 New Tasks Ready
```

Event 不应依赖具体 Agent Runtime。这也是为什么 Event 必须独立于 Message：Backend 说一句「完成了」然后退出，如果只有聊天消息，系统就无法可靠地推进状态。

### 10.6 Integration Gate

`VERIFIED ≠ INTEGRATED`（16.1 第⑩条）。Task 级 Verification 只证明「这个模块是正确的」，不证明「这个模块和整个系统放在一起仍然正确」。两个分支各自通过 Review 与 Verification，合并后仍可能语义互相破坏——例如各自修改了同一接口的调用约定，单测全绿、合起来跑不通。

因此 Integration 是一次独立的、可验证的状态迁移，而不是 Review 通过后的隐含动作：

```text
VERIFIED → READY_FOR_INTEGRATION → INTEGRATING → INTEGRATED → SYSTEM_VERIFIED → COMPLETED
```

合并本身是一条 Command（`git.merge`），经 Integration Gate 校验目标分支保护规则与冲突检测后执行：

```yaml
integration:
  source:
    branch: agent/backend/task-042
    commit: source_commit_full_id
  target:
    branch: main
    expected_commit: target_commit_full_id
  execution:
    binding_id: binding_042_2
    lease_epoch: 2
  result: merged
  result_commit: merge_commit_full_id
  verification:
    verification_id: verification_087
```

流程：

```text
git.merge → integration.completed → 集成分支系统级 Verification → verification.completed
```

源 commit、预期目标 commit、审批范围与执行代次必须在实际更新受保护引用时再校验。目标分支已前进则拒绝该次更新并重新评估，不允许把旧基线上的验证直接套用。合并后必须针对 `result_commit` 重跑系统级 Verification（10.3），产生新的 Verification 记录——合并不是传播状态，而是一次新的可验证事实。Integration 结果同时挂入 Artifact Provenance（14.7）。

出现合并冲突时，禁止 Orchestrator 静默 rebase 覆盖他人修改：产生 `integration.conflict` 事件与冲突记录，路由回原作者 Agent 或集成分支的负责 Role 解决。

---

## 11. 变更与恢复

### 11.1 Change Request

任何可能影响 Blueprint 的重大修改都必须进入变更流程，Agent 不得直接改 Blueprint：

```text
Agent → Change Request → Impact Analysis → Discussion
      → Decision → Approval → Blueprint vNext
```

### 11.2 Impact Analysis

作为协议原语，至少分析：Affected Tasks、Artifacts、Decisions、Dependencies、Team Members、Risk、Estimated Cost、Estimated Delay。

```yaml
impact:
  affected_tasks: [task_003, task_007]
  affected_artifacts: [artifact_012]
  affected_decisions: [decision_004]
  risk: medium
```

系统据此告知人类「这个改动会影响 3 个 Task、1 个 Artifact、1 个 Decision」，再由人类决策。

### 11.3 Change Propagation 与 Replanning

```text
Blueprint v1.0 → Change → Impact Analysis → Replanning
               → Blueprint v1.1 → Task Graph Update
```

已完成的任务不得被静默删除，必须标记 `SUPERSEDED / INVALIDATED / REWORK_REQUIRED`。

**完成事实与当前有效性分离。** 上述 `SUPERSEDED / INVALIDATED / REWORK_REQUIRED` 是成果 / 任务有效性或替代关系标记，不是 7.3 的 Task 生命周期状态。已经 COMPLETED 的历史任务不回写为「从未完成」；修订需求创建新任务，通过 `supersedes` 和引用保留旧成果、旧证据与重新工作的原因。未完成任务则按 7.3 取消、阻塞或重新排队。

### 11.4 失败恢复

```text
Agent Failure → Event → Recovery Engine
```

```yaml
recovery:
  max_retries: 3
  strategies:
    - retry_same_agent
    - switch_agent
    - request_help
    - reduce_scope
    - escalate
```

典型场景：Claude Agent 运行 40 分钟后崩溃，Task 不能永远停在 `IN_PROGRESS`，由 Recovery Policy 决定重试或切换到 GPT Agent 继续。

接入外部 Runtime 后调用链变长（`AETP → Codeg → Codex CLI → OpenAI API`），「Task failed」必须回答**坏在哪一层**。Failure Domain 在 5.6 的 `failure_cause`（是不是能力问题）之上，再标注故障位置：

```text
PROTOCOL / ORCHESTRATOR / RUNTIME / MODEL / PROVIDER
TRANSPORT / TOOL / WORKSPACE / GIT / EXTERNAL / AGENT_CAPABILITY
```

Recovery Engine 按 Domain 选择动作，而不是一律 retry：

| Failure Domain | 恢复动作 |
| --- | --- |
| MODEL / PROVIDER | 换 Model，创建替代 Binding 并增加 lease_epoch（5.13、7.6） |
| RUNTIME | 换 Runtime（如 Claude Code ↔ Codex），从 Checkpoint 继续 |
| AGENT_CAPABILITY | 换 Agent，或发起 Assistance Request（8.7） |
| WORKSPACE / GIT | 重建 Worktree，从 Checkpoint 恢复 |
| TRANSPORT | 重连，Command 按幂等键重放（14.1） |
| TOOL | 按 14.4 审计记录重试或降级 |
| PROTOCOL / ORCHESTRATOR | 协议级缺陷，升级人类 |

其中只有 `AGENT_CAPABILITY` 计入 5.6 的能力成功率，其余 Domain 分别归因到 `infra / dependency / external`，避免信誉污染。

### 11.5 Supersession：统一的替代关系

Decision Reversal（9.2）只是替代关系的一种。Blueprint、Task、Artifact、Proposal 都可能被新版本替代。统一使用 `supersedes` 关系，禁止各实体自行发明 `replaces` / `revised_from` / `deprecated_by`：

```text
Decision B      supersedes → Decision A（9.2）
Blueprint v4    supersedes → Blueprint v3（7.1）
task_093        supersedes → task_021（未完成的旧 Task 进入 CANCELLED；已完成的保留完成事实并标记被替代，7.3）
artifact 新版本  supersedes → artifact 旧版本
```

被替代对象不得删除，保留在各自的 Graph 中。Event Graph（4.4）由此始终能回答「为什么现在是这样」。

---

## 12. 上下文与记忆

### 12.1 Context Engine

Agent 不应默认获得整个 Project Context，而由 Context Engine 按 Task 构建 Context Package：

```text
Mission + Relevant Blueprint + Relevant Decisions + Dependencies
       + Related Artifacts + Relevant Messages
       + AGENTS.md + Current Git State
```

构建链路：`Task → Context Builder → Priority Ranking → Context Compression → Agent`。目的是只提供与当前任务相关的信息，极大降低 Token 消耗。

### 12.2 Context 优先级

| 优先级 | 内容 | Token 不足时策略 |
| --- | --- | --- |
| P0 | 当前 Task | 永久保留 |
| P1 | 直接依赖 | 优先保留 |
| P2 | 相关 Decisions | 摘要 |
| P3 | Blueprint | 压缩 |
| P4 | 相关 Artifacts | 检索 |
| P5 | Discussion History | 摘要 |
| P6 | Project Memory | 按需加载 |

### 12.3 Memory Layers

| 层 | 内容 |
| --- | --- |
| Working Memory | 当前正在干什么 |
| Task Memory | 该 Task 的上下文 |
| Team Memory | 团队已讨论过什么 |
| Project Memory | 项目长期事实 |
| Agent Memory | 单个 Agent 积累的经验 |
| Historical Memory | 过去项目的经验 |

Project Memory 至少包含：Identity、Goals、Architecture、Decisions、History、Tasks、Agents、Discussions、Lessons。

它使项目不必每次从零开始。三个月后用户说「把之前那个概率引擎改一下」，系统应当能回答**当初为什么这样设计**，甚至能指出「曾经尝试过方案 B，因为性能问题放弃」。

由此形成 **Organizational Memory**：新建项目时可检索历史项目，发现类似架构与过去踩过的坑，并注入 Team Formation。

---

## 13. 运行时架构

### 13.1 Orchestrator 与 Manager Agent 分离

这是关键的架构分离：**基础设施与平级成员分离，而不是建立 Human → Manager → 下属 Agent 的指挥链。**

```text
Human → 想法 / 目标 / 关键治理
                    ↓
        Agent A ↔ Agent B ↔ Agent C
           ↘       ↕       ↙
              共同提出方案与执行请求
                    ↓
       Orchestrator（校验 / 调度 / 事件 / 恢复）
                    ↓
              Runtime / Project State
```

**Orchestrator（确定性基础设施）** 负责 Project State、Task Scheduling、Task Routing、Agent Discovery、Event Processing、Dependency Resolution、Permission Enforcement、Approval Routing、Meeting 的计时与流程状态、Recovery，以及应用已通过协议的 Replanning。它不生成技术意见、不判断方案优劣，也不代替 Agent 拆解想法。

**协调职责（可选；可称 Coordinator / Manager）** 可以包括理解 Mission、汇总问题、提出 Role Graph、召集 Meeting、整理分歧、提出 Decision 与 Replanning。这些工作可由任一 Agent 发起、共同完成或轮换承担，不是专属权力；承担者与其他成员平等，不能单方面发布团队决定、分配他人必须接受的任务或宣布成果通过。

**Manager 不是必需组件，也不是通信、提案或成果提交的必经节点。** 不设置 Manager，或当前协调者失联，其他成员仍可直接讨论、提出方案与申请认领；系统按同一协议继续运行。

Orchestrator 也不是「更高一级的 Agent」（P10）：不出现在 Team 名册中、没有 Role、不参与 Discussion 或投票、不能成为技术 Decision 的提议者。任一 Agent 都不能取得 Orchestrator 的基础设施权限。

```text
Orchestrator   确定性、无意见、可重放   校验 / 调度 / 状态 / 事件 / 恢复
所有 Agent    有模型、有意见、平级     思考 / 讨论 / 提议 / 执行 / 互审
```

实现判据：需要技术判断的逻辑应由 Agent 提案与同行讨论承担；需要强制执行的条件应写入协议校验。不能用给 Orchestrator 接 LLM 的方式混合两者。

### 13.2 AETP CORE 引擎划分

协议层面是 19 个 Entity，Runtime 层面可抽象为四大引擎：

```text
┌──────────────────────────────────────┐
│              AETP CORE               │
│                                      │
│  ① Organization Engine               │
│     Team / Role / Agent Formation    │
│                                      │
│  ② Planning Engine                   │
│     Mission / Blueprint / Task DAG   │
│                                      │
│  ③ Collaboration Engine              │
│     Meeting / Discussion / Decision  │
│                                      │
│  ④ Execution Engine                  │
│     Agent / Artifact / Review / QA   │
│                                      │
└──────────────────────────────────────┘
```

展开到实现粒度则是围绕 Project State 的八个组件：

```text
Project State
     ├── Event Store
     ├── Task Engine
     ├── Agent Router
     ├── Meeting Engine
     ├── Decision Engine
     ├── Approval Engine
     ├── Context Engine
     └── Recovery Engine
```

### 13.3 推荐运行时结构

```text
                    ┌─────────────┐
                    │     UI      │
                    └──────┬──────┘
                    ┌──────▼──────┐
                    │     API     │
                    └──────┬──────┘
              ┌────────────▼────────────┐
              │       Orchestrator      │
              └────────────┬────────────┘
       ┌───────────────────┼───────────────────┐
       ↓                   ↓                   ↓
 Task Engine        Agent Router        Meeting Engine
       │                   │                   │
       └───────────────────┼───────────────────┘
                           ↓
                    Event Bus / Store
          ┌────────────────┼────────────────┐
          ↓                ↓                ↓
       Agent A          Agent B          Agent C
        Claude            GPT             Gemini
          └────────────────┼────────────────┘
                           ↓
                          MCP
                ┌──────────┼─────────┐
                ↓          ↓         ↓
               Git       Docker    Browser
```

基础设施组件：Command Handler、Event Store、State Store、Resource Ledger、Credential Broker、Memory、Context Engine、Agent Router、Capability Registry、Runtime Adapter、Transport Adapter、Tool Adapter、Git、Workspace。

### 13.4 Source of Truth

| 存储 | 职责 |
| --- | --- |
| Git | 代码历史 |
| Event Store | 系统行为历史（**事实源**） |
| State Store | 当前项目状态（**Projection**） |
| Artifact Store | 工程产物 |

**Event 是事实源，State 是投影。** 这条规则决定了整个 Runtime 的写入顺序，必须在实现之前定死：

```text
Command
   ↓
Validation
   ↓
Event Store        ← 事实在这里落地，Append-only，不可修改
   ↓
Event
   ↓
Projection
   ↓
Current State      ← 由 Event 推导出来的视图
```

**错误的顺序**是先写 State Store 再补一条 Event。那样 Event 就退化成日志，一旦两者不一致就无法判断谁对。正确的顺序下 State Store 永远是可丢弃的——删掉它，重放全部 Event 就能重建。

由此获得的能力都不是额外功能，而是这条规则的直接推论：

| 能力 | 实现方式 |
| --- | --- |
| Replay | 重放 Event 序列重建任意时刻的 Project State |
| Pause / Resume | 暂停新派发与受控操作；继续接收事实、审计与投影，恢复前重新校验在途状态（见下文） |
| Recovery | Agent 或 Runtime 崩溃后，从 Event Store 恢复而非从 Agent 记忆恢复 |
| Audit | 任何状态都能回答"它是由哪条 Event 造成的" |
| Time Travel | 指定 `sequence` 上限即可查看历史状态 |
| Debug | 复现问题不依赖"当时 Agent 说了什么" |

State Store 的一致性要求因此只有一条：**它不得在 Event 之外被写入**（INV-015）。任何直接改 State Store 的代码路径都是协议违规，无论它看起来多方便。

**重放与派发分离。** Projection Replay 是纯状态重建：不得再次调用模型、Shell、工具、通知发送器或 Runtime.start()。派发队列、命令结果索引和操作记录可由 Command / Event 重建；恢复流程只对尚未确认完成的操作逐条对账，不把历史事件重新当成执行命令（13.10、14.4）。

**Pause 的确定性边界。** `project.paused` 提交即建立派发屏障，并冻结治理时间；它表示调度已暂停，不自动证明所有 Runtime 已停止：

- 停止派发新任务、启动新执行与批准新的受控工具动作；执行边界在实际放行时检查屏障，不能仅检查排队时的状态。
- 继续接收消息、Runtime 报告、工具结果、审计和人类治理命令，继续消费 Event 并更新 Projection。在途报告先留档，不触发后续执行或质量阶段推进；恢复后再检查版本、Lease 与证据。归属撤销、风险阻断和取消等安全控制仍可生效。
- 普通 Agent 交流不需要额外审批；但已暂停的模型会话不承诺实时响应。消息可投递 / 排队，暂停不能被用作永久的角色间通信禁令。
- 分别记录各 Binding 的 `pause_status: requested / confirmed / unsupported / failed`。`confirmed` 仅在执行设施证明受控执行已停止后成立，Runtime 的自述不足以保证外部子进程已停；不支持时阻断可控出口或停止执行，并向用户显示尚未静止的范围。
- 已放行的在途外部动作仍可能完成；结果未知时按 14.4 对账。UI 必须区分「调度已暂停」与「全部执行已静止」，不得把软暂停宣称为彻底停机。
- `project.resumed` 在完成恢复对账、执行代次、凭证、审批和预算检查后提交，之后才重新派发。不得因暂停而延长凭证实际有效期（5.1）。

Git 与 Event Store 的分工也由此明确：Git 是代码的事实源，Event Store 是**组织行为**的事实源。两者不互相包含——Git 不知道某个 commit 对应哪次 Decision，Event Store 不存代码。连接两者的是 Artifact 的 `source.commit` 与 Provenance（14.7）。

### 13.5 Agent Runtime 策略

AETP 不重新实现 Coding Agent、LLM 或 Coding Runtime。Claude Code、Codex CLI、Gemini CLI、OpenCode、Hermes、OpenClaw 等已具备读写代码、运行命令、Git、搜索、测试能力，它们作为**外部 Runtime**通过 Runtime Adapter（13.9）接入。

准确的表述不是「平台管理这些 Agent」，而是——**AETP 通过 Runtime Adapter 驱动这些 Runtime 执行 AETP Task。** 差别在于 AETP 不接管 Runtime 的 Agent Loop（它自己怎么思考、怎么调工具、怎么迭代，AETP 不干预），而只负责它外面的一圈：

```text
创建 / 管理 Execution Binding      提供 Workspace
分配 Task 与执行上下文             接收 Runtime 状态
收集 Artifact                     收集 Usage
触发 Review / Verification         处理失败与 Recovery
把 Runtime 行为映射为 Command / Event
```

由此得到一组固定的归属关系，实现期出现争论时按它裁决：

```text
Agent              是 AETP 的组织成员
Runtime            是 Agent 的执行载体
Execution Binding  是一次具体执行的连接
Session            是 Runtime 侧的执行上下文
Workspace          是执行环境
Git                是代码事实源
```

模型侧通过 Model Router（如 LiteLLM）统一接入 OpenAI / Anthropic / Gemini / Qwen / DeepSeek / OpenRouter，Agent 更换模型无需改动 Agent 本身。

### 13.6 技术栈建议

| 层 | 选型 |
| --- | --- |
| Backend | Python + FastAPI |
| 存储 | SQLite（第一版） |
| 实时通信 | WebSocket |
| 消息 / 事件 | 进程内 Event Bus（后续可换 Redis Streams / NATS） |
| Workspace | Git + Docker Sandbox + Filesystem |
| Frontend | React + TypeScript + React Flow |

第一版不引入 Kafka、RabbitMQ、Redis 等重量级组件；Agent 数量上来后再替换 Message / Event 层。

### 13.7 Agent 执行循环

```text
RECEIVE → BUILD CONTEXT → ANALYZE → PROPOSE → ACT
        → OBSERVE → REPORT → VERIFY → COMPLETE
```

遇到问题时分支到 `NEED_HELP → ASSISTANCE_REQUEST` 或 `BLOCKED`。

### 13.8 Agent Activity Stream

完全托管场景下，UI 不能只是聊天窗口，需要可观测的活动流：

```text
22:31:04  Manager      重新分析 Mission
22:31:09  Architect    提交 Architecture Proposal
22:31:17  Backend      发现 API dependency conflict
22:31:21  Backend      请求 Architect 协助
22:31:28  Architect    开始 Review
22:31:42  Security     检测到 potential vulnerability
22:31:44  Orchestrator Task #42 → BLOCKED
22:32:01  Manager      启动 Replanning
22:32:17  Human Approval Required
```

配合 Agent 列表、任务看板与 React Flow 协作图，人类可以只旁观，必要时介入。

### 13.9 Runtime Adapter Contract

AETP 不实现 Agent，不实现 LLM，不实现 Coding Runtime——它定义这些东西如何组成一个 AI 工程组织。外部 Coding Agent（Claude Code / Codex / Gemini CLI / OpenCode / Hermes / OpenClaw）通过 **Runtime Adapter** 成为 AETP Agent；Codeg 这类多 Runtime 管理器也可以整体作为一个 Adapter 接入，而不必重写其 Agent 管理能力。

**AETP → Runtime（控制面）：**

```text
start() / stop() / pause() / resume()
send_message() / assign_task()
get_status() / get_capabilities()
create_workspace() / get_workspace()
collect_artifact() / collect_usage()
checkpoint() / recover()
```

**Runtime → AETP（上报面）：** 全部提交报告类 Command，由受信边界绑定发送身份、校验后产生 Event；Runtime 不直接生成权威 Event，不允许直接写 State（INV-001 / INV-011）：

```text
execution.report_started / execution.report_progress
execution.report_finished / execution.report_failed
artifact.submit / review.request
agent.report_available / agent.report_failed / agent.report_disconnected
```

`execution.report_finished` 只表示该次执行已经结束，不能等同于 `task.completed`。带合格 Artifact 的结束报告最多请求进入待审阶段；Review、Verification、Integration 与 Mission Acceptance 仍由 AETP 的质量门决定。迟到或旧代次报告作为历史事实保存，不能覆盖当前 Task。

Adapter 接入时声明 **Runtime Capability**，供 Effective Capability（5.13）与资格门（6.4）使用：

```yaml
runtime:
  id: codeg
  version: "x.x"
  capabilities:
    task:      [assign, cancel, pause]
    workspace: [git, worktree]
    execution: [shell, filesystem]
    streaming: [stdout, progress]
    recovery:  [checkpoint]
  enforcement:
    mode: mediated               # mediated / observation_only
    authenticated_actor: true
    pre_tool_authorization: true
    credential_isolation: true
    workspace_isolation: os_sandbox  # working_copy / os_sandbox
    network_egress: allowlist     # unrestricted / allowlist / disabled
    pause: controlled_execution  # controlled_execution / dispatch_only
```

**能力声明不是安全证明。** `enforcement` 必须通过对应 Conformance / 越权用例验证，并参与任务资格门（6.4）；配置由受信运行设施提供，不允许模型自行升格。

1. **身份绑定：** Command 中的 actor 与已认证连接、Agent 身份及 Binding 对齐；普通成员消息不要求任务 Lease，但也不能冒充其他成员。执行命令校验当前 Binding 与 epoch（7.6）。
2. **执行前授权：** 敏感工具操作必须在真实调用点检查权限、审批快照、参数摘要、暂停屏障与代次；工具代理、受控 Shell 或隔离环境可以承担这个职责，不要求 AETP 接管模型推理循环。
3. **防绕过：** 如果能通过原始 Shell、直连 API、共享凭证或访问受保护仓库绕过代理，就不能宣称该控制有效。工作区、凭证和网络出口必须与所承诺的权限边界一致，受保护分支只由受控集成入口更新。
4. **兼容范围：** `observation_only` 可以参加讨论与提交候选成果，但只能执行其边界确实能限制的低风险工作，不得承接依赖缺失控制的任务或宣称完整 AETP Compatible。即便 `mediated`，超出已验证能力的操作也必须拒绝或转交合格执行设施；不能靠提示词补齐。
5. **通信不分级：** 上述区别是执行能力，不是 Agent 职级。能力较弱的 Runtime 不因此失去普通讨论、质疑或提案资格；真正执行时可以请求合格同行协助。

**Adapter 按职责分三类。** Runtime Adapter 不应该顺手承担工作区与传输职责——Codeg 一类工具最值得借鉴的恰恰不是它的 Agent 协作逻辑，而是 Workspace / Worktree / Branch / Session / Diff / Review / Merge 这一整套工程执行设施。因此 AETP 侧划成三类契约，**它们是 Service Contract，不是新的协议实体**（4.2 的实体表不变）：

```text
AETP
 ├── Runtime Adapter      驱动 Agent 执行     Claude Code / Codex / Gemini CLI / OpenCode
 ├── Workspace Provider   提供隔离执行环境    Local FS / Git Worktree / Docker / Codeg
 └── Transport Adapter    传递消息           Local IPC / WebSocket / A2A（2.4）
```

一个实现可以同时充当多类：Codeg 既是 Runtime 管理器也是 Workspace 提供者，Claude Code 只是 Runtime。接入方式（subprocess / PTY / HTTP / WebSocket）属于 Adapter 内部实现，协议只约束契约。**Workspace Provider 控制面：**

```text
create(project_id, base_ref) → workspace     attach(workspace_id, binding_id)
diff(workspace_id) / commit(workspace_id)    merge(source, target) → result | conflict
snapshot(workspace_id) / destroy(workspace_id)
```

两条硬性要求：`create()` 必须能给出**独立工作副本**（默认 Git Worktree，1.6 ⑤），一个 Agent 的未提交改动不得自动出现在另一个 Agent 的工作副本中；`merge()` 必须能返回冲突而不是自行解决——冲突要落成 Integration Conflict 记录并按 10.6 路由，**不允许 Provider 静默 rebase 掉别人的修改**。

**工作副本隔离不等于安全隔离。** Git Worktree 本身不证明另一个进程无法读取、写入相邻目录或共享仓库元数据。若 Task 要求访问隔离，Provider 还必须提供经验证的 OS / 容器权限边界，否则只能声明 `working_copy` 能力。`merge()` 必须接收固定 source commit、expected target commit 与当前执行权，在受保护引用更新处做条件校验；目录路径或分支名不能替代这些条件。

**Execution ≠ Session。** Session 是 Runtime 侧的执行上下文（一次 Codex 会话、一次 Claude Code 会话），它既不是 AETP Task，也不是 Execution Binding：

```text
AETP Task-042
 ├── Execution #1  → Codex Session 182         （崩溃）
 ├── Execution #2  → Claude Code Session 91    （超时）
 └── Execution #3  → Codex Session 193         → VERIFIED
```

Task 的权威状态属于 AETP（7.10），Session 的生命周期属于 Runtime。**Session 结束不代表 Task 结束，Session 丢失也不代表 Task 失败**——只要 Checkpoint 在（7.7），换一个 Binding 继续即可。Adapter 必须上报 `session.id` 供审计与 Recovery 使用（5.13），但不得把 Session 状态当作 Task 状态的来源；把两者等同起来，Recovery 与 Runtime 切换就都无从谈起。

v0.1 的第一个参考 Adapter 是本机 Runtime，Codeg 为首个外部验证对象（18.3）。

### 13.10 Orchestrator 自身的恢复语义

v0.1 允许单进程，但不能让 Orchestrator 的内存成为权威状态。**Orchestrator 无自有权威状态（INV-021）**：缓存、索引、命令结果表与待派发队列必须由持久化 Command / Event 重建；命令的受理事实亦须落为 Event（14.1）。

```text
启动并保持派发屏障
  → Replay / Snapshot + 增量事件重建 Projection（不执行外部动作）
  → 按治理时间恢复 Project 暂停状态、Lease / epoch、Approval 与调度条件
  → 重建已受理 Command、终态结果索引与待派发操作
  → 与 Runtime 对齐 Session / Binding；检查尚未确认的外部效果
  → 对 UNKNOWN 操作查询 / 对账，无法安全确认则阻塞相关任务
  → 校验当前权限、凭证、审批版本与预算
  → 仅在 Project 非 PAUSED 且相关恢复条件满足时开放派发
```

- Task Readiness 由 Task Graph 与 Event 重算，不依赖上次内存中怎么排队。
- 内部 Command 的幂等效果由 14.1 的原子事务保证；不能推导出外部工具恰好执行一次。已派发未确认的动作按 14.4 对账，不能简单重发。
- Orchestrator 崩溃不等于 Agent 崩溃；通过 `get_status()` 及受信执行记录确认 Session，而不是默认丢弃已有成果。暂停、隔离或旧代次报告只作为恢复依据，不直接推进当前任务。
- 项目原本为 PAUSED 时重启后仍保持暂停。重复重启或重复恢复事件不能重复启动 Runtime、重复合并、重复扣款或再次发送已确认完成的外部通知。

这些记录属于现有 Command / Event / Action 的实现与投影，不新增协议实体，也不引入无法从事实源重建的私有调度状态。

---

## 14. 协议底层机制

前面各层定义的是「系统里有什么、它们之间怎么发生关系」。本章补齐的是协议的**底层写入路径、审计边界与错误表达**——这些不是功能，而是 Runtime 一旦开写就必须存在的东西，缺失会导致返工。

优先级：**14.1 ~ 14.4 为 P0，必须进入 v0.1；14.5 ~ 14.9 为 P1，可延后实现，但协议接口现在就要预留**（见 17.6）。

### 14.1 Command / Operation（AETP-017）

协议此前定义了 Message、Event、Task、Decision、Approval，但缺少最关键的一环：**Agent 到底通过什么「动作」改变系统？**

Agent 说「我要把 task_042 分配给自己」，这不是 Message，也不能直接变成 Event。它是一个 Command。

**错误的关系：**

```text
Agent → Event
```

因为 **Event 是已经发生的事实，不应该由 Agent 直接制造**。

**正确的链路：**

```text
Agent → Command → 身份 / 权限 / 版本 / Lease 校验
      → 原子提交 Event 批次与处理结果 → Projection
```

**Command Type ≠ Command Instance。** `task.claim` 是类型，是协议词汇表里的一个词；真正在系统里流动的是实例，必须可寻址、可去重、可审计：

```yaml
command:
  schema_version: "0.1"
  id: command_001
  type: task.claim
  actor:
    type: agent
    id: agent_002
  target:
    type: task
    id: task_042
  payload: {}
  expected_revision: 7
  issued_at: ...
  idempotency_key: claim_attempt_8c519e17
  correlation_id: task_042
```

各字段的必要性：

| 字段 | 为什么不能省 |
| --- | --- |
| `id` | Event 的 `causation_id` 要指向它（14.2），没有 id 就断链 |
| `type` | 决定校验规则与所需权限 |
| `actor.type` | 主体可能是 agent、human 或 system，权限模型完全不同 |
| `target.type` | 同一个 id 空间下必须区分对象类型 |
| `issued_at` | 与 Event 的 `timestamp` 分离，用于测量校验延迟 |
| `idempotency_key` | 网络重试必然发生；同一 key 重复提交只允许生效一次 |
| `correlation_id` | 把 Command 与后续 Event 串进同一条业务链路 |
| `expected_revision` | 限定目标对象预期版本，在最终提交时检测并发冲突 |
| `binding_id / lease_epoch` | 执行类命令的当前执行权；首次认领与普通讨论不要求持有 Task Lease |

`idempotency_key` 是四个 P0 字段里最容易被忽略、代价最大的一个。缺了它，一次超时重试就可能让同一个 Task 被 claim 两次、同一笔预算被扣两次。

Orchestrator 在执行前必须校验：

```text
actor 是否与受信连接及执行身份一致？
idempotency_key 是否已受理？规范化内容是否与原请求相同？
是否具备当前 Policy 规定的 Permission / Authority 与有效审批快照？
目标与相关依赖版本、状态是否允许该操作？
Agent 是否已达并发与资源上限？Project 是否允许派发？
执行类命令的 Binding / lease_epoch 是否仍有效？
```

结果二分：

```text
内部处理成功 → 对应领域 Event 批次与可重建结果（如 task.claimed）
校验失败 → command.rejected + Error 对象（见 14.9）
需外部执行 → 仅确认受理 / 待派发，最终效果按 14.4 确认
```

**受理、事务与幂等的最小契约。**

1. 通过身份认证和基本格式校验后，持久化不可变 Command 与 `command.received` 受理事件，再确认收到。尚未完成这一步不承诺接收成功；未认证请求只进入受信入口的安全审计，不能借伪造 actor 向项目注入事实。
2. 去重键的作用域是 `(project_id, authenticated_actor_id, idempotency_key)`，并绑定规范化命令内容摘要（类型、目标、payload、预期版本和执行上下文）。同键同内容返回原受理状态 / 终态结果；同键不同内容返回 `IDEMPOTENCY_CONFLICT`，不能覆盖原结果。应用重试沿用原 Command，新的业务意图使用新 ID / key；释放后再次认领不是旧认领的重试。v0.1 在 Project 生命周期内保留去重依据。
3. 在同一存储事务中检查目标及所有受影响资源的当前版本、提交有序 Event 批次并写入结果索引。唯一约束与提交时版本检查必须处理竞争，不能只在事务外「先查一下」。同一批次的跨对象约束（如归属、Lease、资源预留）全部成功或全部失败。结果索引必须可从 Command / Event 重建。
4. Projection 不得先写。读侧允许滞后，但写入校验必须基于事务内的最新事实或具有等价串行化保证的状态，不能拿任意滞后的读投影授权。提交遇到 `REVISION_CONFLICT` 时保留原结果，重新读取后以新命令表达修订意图；不能暗中改写原 payload 或 expected_revision。
5. 一条 Command 可以合法产生多个 Event。幂等保证的是**不重复提交该次操作的领域效果批次**，不是「最多一条 Event」。同键重试不能重复创建领域事件或 rejected 事件；如需记录重试观测，使用独立诊断日志。成功提交后响应丢失，重试仍返回原结果。
6. 外部调用不得包在数据库事务里假装原子完成。事务只持久化待执行意图，其派发与结果确认采用 14.4 的独立状态机。事件重放不能重新触发这些调用。

`expected_revision` 是目标对象的版本，不是 Project phase，也不是客户端 Event sequence。创建新对象使用「不存在」条件；对多对象命令还须携带或事务内校验其他对象的版本 / 作用域。新增字段不新增顶层实体。

**命令契约索引。** 下表定义本轮涉及的规范边界；7.3 是 Task 后态的唯一迁移表，错误码见 14.9。冻结前每个已实现 Command 都必须补齐相同列的可执行 valid / invalid 夹具；没有契约的未知 Command 拒绝，而非隐式放行。

| Command / 类别 | 前置与授权 | 成功事实 / 结果 | 关键拒绝条件 |
| --- | --- | --- | --- |
| `task.claim` / 分配 | 依赖就绪、角色能力匹配、允许接受分配、预期版本、无有效竞争归属 | 原子记录 task.claimed / task.assigned、Binding 与 Lease；进入 ASSIGNED | REVISION_CONFLICT / TASK_NOT_ASSIGNABLE |
| `task.release / task.handoff / task.decline` | 当前归属者或明确的人类治理授权；校验在途动作 | 撤销旧执行权；按 7.3 重排，交接不强迫接收者接受 | STALE_EXECUTION / ACTION_OUTCOME_UNKNOWN |
| `execution.report_*` | 认证来源与绑定；区分当前代次、迟到与历史报告 | 记录执行事实；仅在守卫满足时进入 7.3 允许的后态 | ACTOR_MISMATCH；旧代次仅留档、不推进任务 |
| `artifact.submit` | 产物摘要与来源；关联当前实施输出时校验其 Binding / Lease；非 owner 的候选产物不自动取得任务归属 | artifact.created；正式接受与任务迁移另行校验 | STALE_EXECUTION / EVIDENCE_STALE |
| `review.request / verification.submit` | 提交者自身操作权限、受信证据与被审目标快照；不要求接管被审 Task 的 Lease（10.3） | review.requested / verification.completed；不得跳过质量门 | 未授权提交 / EVIDENCE_STALE；适用执行上下文失效时 STALE_EXECUTION |
| `git.merge` | Review / Verification 有效、固定源与目标 commit、当前执行权、分支保护 | 先记请求；确认后 integration.completed / integration.conflict | REVISION_CONFLICT / APPROVAL_STALE / ACTION_OUTCOME_UNKNOWN |
| `decision.propose / task.propose / change.request` | 项目准入及提案基本格式；不要求 Manager 许可 | 提案事实；批准或应用变更另行校验 | 无效引用 / 目标版本冲突 |
| Approval 请求、批准、撤销与决定应用 | 相应动作权限、主体分离、版本 / 摘要 / Policy / 过期与撤销状态 | 对应 approval.* / decision.*，保留完整历史 | APPROVAL_STALE / 未授权审批 |
| `assistance.request / role.request / meeting.open` 等正式协作命令 | 项目准入、主题 / 预算规则；不要求 Agent 职级 | 对应协作事实，不直接取得他人任务或资源权限 | 无效对象 / 预算不足 |
| `tool.invoke` | 工具作用域、审批快照、参数、当前执行权与暂停屏障 | tool.requested；最终效果另行确认 | ENFORCEMENT_UNAVAILABLE / PROJECT_PAUSED |
| `project.pause / project.resume / intervention.apply` | 人类或 Policy 明示的治理权限 | project.paused / project.resumed / intervention.applied | 未授权 / 恢复前置条件未满足 |

普通成员之间的 Message 走通信契约，不以该命令表设置 Manager 审批；将发言固化为证据或提案时才产生相应权威记录（8.5、14.10）。

Command 本身也是不可变的：它一旦被提交就成为历史记录，不允许修改后重发——改变主意的方式是发一条新 Command，而不是改旧的。

常用 Command：

```text
task.claim / task.release / task.handoff / task.propose / task.decline
decision.propose / approval.request / change.request
role.request / assistance.request / meeting.open / intervention.apply
```

**核心规则：Command 是 Project State 唯一的写入口。** 这条规则使 INV-001（Agent 不得直接修改 Project State）第一次有了明确的执行机制。人类介入也不例外——Intervention 同样落为 Command（9.7）。

### 14.2 Event Ordering 与 Idempotency

这是协议进入工程实现后必踩的坑。两类故障必然出现：

```text
重复投递    task.completed 被发送两次
顺序异常    task.completed 先于 task.started 到达
```

因此 Event 必须携带排序与因果字段：

```yaml
event:
  id: event_xxx
  sequence: 10241
  timestamp: ...
  causation_id: command_xxx     # 直接导致该事件的 Command 或 Event
  correlation_id: task_042      # 同一业务链路的共同标识
```

`causation_id` 与 `correlation_id` 使整条链路可追踪：

```text
command.task.claim
      ↓
event.task.claimed
      ↓
command.execution.report_started
      ↓
event.task.started
```

**`sequence` 由谁赋值？** 这是必须在写第一行代码前定死的归属问题。答案是：**Event Store 内的 Event Sequencer 统一赋值，Agent Runtime 不得自行生成 `sequence`。**

```text
Command
   ↓
Orchestrator（校验）
   ↓
Event Sequencer     ← 唯一的 sequence 分配者
   ↓
Event Store（append）
   ↓
Subscribers
```

这是 AETP 对 Project 内权威事件全序的协议选择，不要求部署一个跨所有项目的全局发号服务。当 Agent 分别跑在 VPS-1、VPS-2 和本地时：

```text
Agent A（VPS-1）  自己发号 → 1, 2, 3
Agent B（VPS-2）  自己发号 → 1, 2, 3
Agent C（本地）   自己发号 → 1, 2, 3
```

得到的不是一个全局序列，而是三条互不相干的局部序列，无法重排、无法重放、无法判断因果。而时间戳同样不可信——多机时钟漂移几百毫秒就足以让因果颠倒。

因此：

- `sequence` 在 **Project 范围内全局单调递增**，由 Event Sequencer 独占分配。
- Agent 提交的是 Command，不是 Event；Agent 从不参与编号。
- 乱序到达时**按 sequence 重排，而不是按 timestamp**。
- `timestamp` 只用于展示与性能观测，**不得用于排序或因果判断**。
- Event 消费方**必须幂等**，同一 `event.id` 重复到达不得产生二次状态变更。

这条规则同时把 Event Store 变成了系统里唯一的同步点，也正是 13.4 中 State Store 能作为纯 Projection 存在的前提。

### 14.3 Credential Broker（凭证边界）

系统最终会同时持有 Claude / OpenAI / Gemini API、GitHub、Cloudflare、AWS、数据库、Browser 等大量凭证。**Agent 不应直接拥有它们**：

```text
Agent → Credential Broker → 短期 scoped credential → Tool
```

```yaml
credential_scope:
  agent: backend
  permissions:
    - github.repo.read
    - github.repo.write
  expires_in: 30m
```

Agent 拿到的永远是**限定权限、限定时效**的凭证，而不是 `GITHUB_TOKEN` 本身。这个边界必须从协议层就存在——否则「完全托管」不可能安全成立。

`expires_in` 是协议里唯一按**墙钟时间**计的过期语义（5.1）：暂停项目不得延长一份短期凭证的实际有效期，否则一次长暂停就能把它变成长期凭证。

### 14.4 External Action / Tool Audit

**外部工具的执行许可与执行结果必须分开记录。** MCP、Shell、浏览器、Git 与云 API 都不能成为协议外的旁路。Action 是现有工具操作记录，不新增顶层实体：

```yaml
action:
  id: action_042
  command_id: command_087
  actor:
    agent_id: agent_001
  binding_id: binding_042_2
  lease_epoch: 2
  tool:
    name: cloud.create_resource
  arguments_digest: sha256:canonical_arguments_digest
  approval_id: approval_087
  policy_version: governance_7
  external_idempotency_key: action_042
  provider_operation_id: null
  risk: high
  status: PENDING
```

对不属于 Task 执行的人类 / 系统操作，Binding 字段可不适用，但必须具有经过认证的主体、动作作用域与授权来源。低风险自动动作可以没有 approval_id，但仍要记录适用的 Policy；Agent 角色名称不是授权依据。

| 状态 | 含义 | 后续 |
| --- | --- | --- |
| PENDING | 意图已持久化，尚未开始派发 | 在真实执行点重新检查授权、版本、暂停屏障与执行权；通过后才派发 |
| IN_FLIGHT | 已记录派发开始，尚未得到确定结果 | 等待结果或查询；不能因客户端超时就认定失败 |
| SUCCEEDED | 已确认外部效果成功且保存证据 / 外部标识 | 生成对应领域事实；不得再次派发 |
| FAILED | 已确认失败并记录已发生的部分效果 | 按明确的安全重试 / 补偿规则处理；失败不等于外部自动回滚 |
| UNKNOWN | 派发后失联、崩溃或缺少确定证据，无法判断是否生效 | 查询 / 对账，必要时人工确认；不可盲目重试 |
| CANCELLED | 确认尚未派发的意图被取消 | 不得派发；已在途的操作不能只靠取消本地记录假装撤销 |

**持久化派发与恢复规则：**

1. Command 事务内写入 `tool.requested` 与可重建的派发意图，提交后再由 Dispatcher 领取。v0.1 可使用同一 SQLite 存储中的 outbox 投影，不需要额外消息系统。队列必须从事件重建；领取、派发开始和结果均留下事实。
2. 同一 Action 的并发派发必须串行化，重试沿用稳定的外部幂等键。仅在 Provider 明确支持该动作的幂等范围 / 有效期时依赖它；本地 Command 去重不能替代远端保证。
3. 「远端成功、响应丢失」或「记录派发后、发出前崩溃」都进入待确认路径。可通过 provider_operation_id、唯一资源标识或可验证的结果摘要查询；无法安全确认则保持 UNKNOWN 并阻塞相关任务，通知人类。只有经证明无副作用 / 可安全重试的操作才可自动重发。
4. UNKNOWN 不能直接推动 Task FAILED、任务重新执行或 Mission 完成。取消、Lease 换代、暂停与审批撤销也不能抹掉在途效果；对账报告即便来自旧执行也要保留，但不得借此恢复旧执行权。必要的补偿是新的受控操作，不是改写旧结果。
5. Replay 只重建上述状态。Dispatcher 只处理已确认可派发的 PENDING 意图；IN_FLIGHT / UNKNOWN 必须先对账，不得把历史 `tool.requested` 逐条再执行一遍。

对应事件为 `tool.requested / tool.invoked / tool.completed / tool.failed / tool.outcome_unknown / tool.reconciled / tool.cancelled`。其中 tool.invoked 表示已开始派发，不证明远端已完成；tool.completed 必须有结果依据。参数、输出与错误须按密钥 / 数据范围脱敏；审计元数据由受信设施记录，模型自述只作为待核实报告。

**该契约只约束动作，不限制对话。** Agent 可以讨论任何方案、提出风险与替代建议；真正访问资源或把结论写入权威状态时，才按 13.9 与第 9 章执行检查。

### 14.5 Resource Ledger（AETP-018）

Agent Resources（5.7）只描述**约束**（并发上限、日预算、Rate Limit），还缺少记录**实际消耗**的账本：谁用了多少钱、多少 Token、多少时间。

三级账目：

```text
Project    Budget 20.00 / Used 13.20 / Remaining 6.80

Agent      Manager $1.2   Architect $3.4   Backend $4.7
           Frontend $2.1  QA $1.8

Task       task_042  Token 182k  Cost $1.82  Runtime 23m
```

这对多模型混编团队尤为关键：不同 Agent 使用不同 API、不同模型，成本差异巨大。有了 Ledger，Router 的选人链路才完整：

```text
Task → Capability → Cost → Latency → Availability → Quality → Agent Selection
```

Ledger 是 6.4 中 `SelectionScore` 里 `Cost` 项的事实来源，也是预算耗尽时触发降级或暂停的依据。

### 14.6 Capability Registry

Capability 目前只是字符串（`backend` / `security` / `kubernetes`），长期运行不够用。应有独立的能力注册表：

```yaml
capability:
  id: capability.security.web
  name: Web Security
  version: "1.2"
  category: security
  prerequisites:
    - networking
  evaluation:
    type: performance_based
```

于是能力具备命名空间层级：

```text
security.web
security.api
security.cloud
security.smart-contract
```

而不是把所有东西塞进一个 `security`。Agent 的 capability 字段引用 Registry 中的定义，评分（5.5）与三级可信度（5.6）挂在引用关系上，Role 的 `required_capabilities` 也据此精确匹配。

### 14.7 Artifact Provenance

Artifact 需要正式记录来源关系：

```yaml
artifact:
  id: artifact_042
  created_by:
    agent: backend
  derived_from:
    - artifact_021
    - decision_012
  produced_by:
    task: task_042
  source:
    git_commit: a82f31
  reviewed_by:
    - security
    - qa
```

由此可以回答「这段代码为什么存在」，一路追溯：

```text
Code → Artifact → Task → Decision → Meeting → Evidence → Mission
```

这条链就是 **Engineering Provenance Graph**，也是 P4（所有重要状态可追溯）的具体实现。

### 14.8 并发与冲突

Task Lease 与 fencing（7.6）解决任务归属和旧执行权失效；它们不替代独立工作副本、文件权限或集成冲突处理。对共享资源的锁也必须绑定执行代次，并在实际写入点检查，不能仅依靠到期时间。

手段一，Resource Lock：

```text
LOCK
resource: repository/backend/api.py
owner:    agent_backend
expires:  ...
```

手段二，也是**推荐的默认开发模式**——每个 Agent 独占分支：

```text
Agent → Git Branch → Worktree → Commit → Review → Merge
```

原则：**Agent 之间尽可能不直接覆盖彼此的文件**，冲突在 Merge 阶段以工程手段解决，而不是靠运行时抢锁。

### 14.9 Protocol Error Model

协议定义了大量正常状态，但没有定义**失败本身怎么表达**。统一错误对象：

```yaml
error:
  code: TASK_NOT_ASSIGNABLE
  message: |
    Agent lacks required capability.
  retryable: false
  severity: medium
  context:
    task_id: task_042
    agent_id: agent_007
```

错误码按域划分命名空间：

```text
AETP-AUTH-001      权限与凭证
AETP-TASK-001      任务与依赖
AETP-AGENT-001     Agent 与 Runtime
AETP-TEAM-001      组队与角色
AETP-GOV-001       治理与审批
AETP-RUNTIME-001   基础设施
```

`command.rejected`、`task.failed`、`tool.failed`、`review.rejected` 统一携带该对象。`retryable` 必须结合外部效果状态与有效授权判断，不能仅凭布尔值重发可能已生效的操作（14.4）。

本轮明确的符号错误码及处理如下；它们归入上述域，不新增错误实体：

| 符号码 | 域 | 处理 |
| --- | --- | --- |
| ACTOR_MISMATCH | AUTH | 拒绝冒用身份；受信入口记录安全审计 |
| IDEMPOTENCY_CONFLICT | RUNTIME | 同键异内容，拒绝且不得覆盖原结果 |
| REVISION_CONFLICT | TASK / GOV | 读取新状态后重新提出命令，不暗改旧请求 |
| STALE_EXECUTION | AGENT | 旧 Binding / epoch 不能继续权威写入；历史报告仅留档 |
| APPROVAL_STALE | GOV | 审批快照不适用，重新评估 / 申请 |
| EVIDENCE_STALE | TASK | 证据不对应当前输入，重新验证 |
| PROJECT_PAUSED | RUNTIME | 不派发新动作；恢复前不自动重试 |
| ENFORCEMENT_UNAVAILABLE | AUTH | 所需强制边界未验证，拒绝或转交合格执行设施 |
| ACTION_OUTCOME_UNKNOWN | RUNTIME | 对账或人工确认，禁止盲目重试 |

### 14.10 Durable Event 与 Ephemeral Communication

**不是所有 Agent 之间的往来都应该进入 Event Store。** 这个边界如果不划，第一个真实项目就会把事实源撑爆。

一次 3 小时、8 个 Agent 的开发过程，Agent 之间的对话轮次很容易达到上万条量级。如果每一句都写成 Event，Event Store 会立刻退化为聊天记录数据库——重放要跑几万条无意义的记录，审计时也无法从噪声里找出真正改变了项目的那几十件事。

因此协议区分两类流量。

**Durable Protocol Event（必须进入 Event Store）：**

```text
Command                提交与拒绝
State Change           任何对象的状态迁移
Decision               提出、通过、推翻
Approval               请求、批准、拒绝、过期
Task Status            创建、分配、开始、阻塞、完成、失败
Artifact               产出与变更
Review                 结果
Verification           结果与证据
Tool Action            外部调用（14.4）
Intervention           人类治理行为
```

判据只有一条：**它是否改变了项目的事实状态，或是否需要被审计。**

**Ephemeral Communication（不进入 Event Store）：**

```text
Agent 之间的讨论过程
模型的流式输出
中间上下文与草稿
临时推理与自我修正
未形成 Proposal 的想法
```

这些内容仍然可以被持久化，但去向不同：进入 Discussion（8.8）、Meeting 记录（8.9）与 Memory（12.3），作为可检索的过程材料，而不是作为事实。它们可以被摘要、压缩、按保留策略清理；Event 不可以。

两者的关系正是 `Message ≠ Event`（16.1 第②条）在存储层的落地：

```text
Ephemeral        Message / Discussion / Meeting    可压缩、可过期、可摘要
                          ↓
                      Proposal
                          ↓
Durable          Command / Event                   Append-only、永不修改
```

一次讨论产生 200 条 Message，最终可能只落成 1 条 Decision 与 3 条 Event。这个收敛比不是损失，而是协议在做它该做的事——**把过程与事实分开**。

工程含义很直接：Event Store 的增长应当与项目的结构性进展成正比，而不是与 Agent 的话多不多成正比。如果实现中发现 Event 数量随对话线性膨胀，说明这条边界被越过了。

### 14.11 Input Trust Boundary（输入信任边界）

Credential Broker（14.3）隔离了密钥，但没有隔离「影响力」。外部输入——网页、GitHub Issue / PR、第三方 README、PDF、代码注释、外部 API 返回、数据库内容、用户提交内容——都可能携带指令，诱导 Agent 发起 Command。信任边界不绑定在 Agent 类型上（不是「Browser Agent 不可信」），而绑定在**输入来源**上：

```text
Input
 ├── Trusted
 ├── Internal
 └── Untrusted
```

`external_input_exposure` 由受信输入入口、Context Engine 或执行设施记录；Agent 可以补充声明，但不能自行清除。输入来源不明、Runtime 无法完整报告输入路径时，按 Untrusted 保守处理，不能默认为 Trusted。

来源标记随 Message 引用、摘要、Context Package、Proposal 与 Command 传播；经其他 Agent 转述或生成摘要不自动变可信。v0.1 不要求精确识别模型受哪句话影响，可对暴露过的执行上下文采用保守标记：在受信设施确认干净的新上下文建立前，相关操作携带 `untrusted_input: true`。

Governance Policy 对带标记的**执行或权威变更请求**提高审批 / 复核要求，最高不超过强制人类批准；同行复核不自动清除输入来源记录。普通直接对话、质疑和方案讨论不需要因此逐条审批，也不把接触外部资料的 Agent 降成「下级」。安全边界是外部数据不能赋予执行权限，而不是禁止成员交流。

核心原则（INV-020）：

> **外部数据可以成为决策依据，但不能单独成为执行命令的授权来源。**
> External data may inform a Decision, but cannot independently authorize a Command.

正确链路：

```text
Untrusted Input → Evidence → Analysis → Proposal → Governance → Command
```

网页上出现「立即执行 shell command xxx」，Research Agent 可以把它作为 Evidence 引用，但绝不能让它直接变成 Command。这是 Autonomous 模式得以安全运行的前提。

---

## 15. 标准工作流

### 15.1 主流程

用户输入：「做一个 AI 新闻预测平台。」

```text
USER IDEA → PROJECT / 初始 MISSION
→ 已准入的少量平等 Agent 直接讨论目标、约束与候选方案
→ PROJECT BOOTSTRAP（15.5；含所需环境方案讨论）
→ 按能力形成 / 调整正式 TEAM，继续同行讨论
→ DECISION / BLUEPRINT（按风险策略批准，不逐条审批对话）
→ TASK DAG → 自主认领 / 协议分配 → PARALLEL EXECUTION
→ REVIEW → VERIFICATION → INTEGRATION → SYSTEM VERIFICATION
→ MISSION ACCEPTANCE → DELIVERY
```

任何阶段都允许成员直接交流、提出替代方案与请求协助；只有应用已批准变更时才改变执行基线。Meeting 是需要时使用的结构化讨论方式，不是唯一沟通方式。Manager 不存在或离线也不能阻断这条闭环。

### 15.2 完整自主循环

```text
       MISSION → TEAM FORMING → PLANNING → DECISION → TASK GRAPH
                        ┌────────┴────────┐
                        ↓                 ↓
                     AGENT A           AGENT B
                        ↓                 ↓
                     ARTIFACT          ARTIFACT
                        └────────┬────────┘
                                 ↓
                    REVIEW → VERIFICATION → INTEGRATION
                           → DELIVERY → PERFORMANCE DATA
                           → TEAM EVOLUTION ──→ REPLAN
```

### 15.3 人工介入循环

```text
                    HUMAN
                      ↓
                INTERVENTION
          ┌───────────┼───────────┐
          ↓           ↓           ↓
        PAUSE      MODIFY       STOP
          │           ↓
          │    IMPACT ANALYSIS
          │           ↓
          │        REPLAN
          └───────────┴──────────→ RESUME
```

### 15.4 人类职责

人类不再需要手动拆 Task、手动找 Agent、手动复制上下文、手动转发意见、手动安排会议、手动检查每个结果，只需要：

```text
Define Goal
Set Governance
Approve Critical Decisions
Intervene When Necessary
```

### 15.5 Project Bootstrap：开发前的标准初始化阶段

正式开发之前，AI Team 先自主完成项目启动——不是人工备好环境再让 Agent 写代码，而是由协议管理的**第一个真实 Mission（Mission #0「Initialize Project」）**。Bootstrap 自身完整走协议：Bootstrap Mission → Blueprint → Tasks → Commands → Events → Verification。

```text
Mission #0
 │
 ├── B0 Discovery        环境侦察
 ├── B1 Architecture     技术栈与架构决策
 ├── B2 Environment      开发环境搭建
 ├── B3 Knowledge        Skills / 知识库 / 知识图谱
 ├── B4 Infrastructure   Git / CI / 测试 / Lint / 可观测性
 └── B5 Verification     Bootstrap Acceptance
        ↓
 BOOTSTRAP_VERIFIED → 进入正式 Planning（第 7 章）
```

Bootstrap 从已登记 Agent 中选择最小有效的平级协作集合；Environment Analyst / Architect / DevOps / Research / Skill Architect / QA / Security 是可兼任的职责，不是必须配齐的固定职位或层级。正式执行团队的完整 Team Formation（第 6 章）在 `BOOTSTRAP_VERIFIED` 之后进行，先前的讨论与初始方案不依赖它。

**B0 Discovery。** 侦察 OS、CPU / RAM / GPU / 磁盘、Python / Node / Git / Docker / WSL、数据库、网络、可用 API 与凭据，形成 Environment Profile。关键原则：**环境信息必须是 Evidence，不是 Agent 的一句话**——「Docker 可用」必须来自 `docker version` 的 Action 输出（14.4），经 Verification 落为 `environment.docker = VERIFIED`。这是冻结区分⑤（16.1）在环境层的直接应用。

**B1 Architecture。** 不由用户提前指定技术栈，而由 Architecture Meeting（8.9）产出 Technology Selection Decision（9.1）——backend / frontend / database / event store / transport / runtime adapters，经批准后进入 Blueprint v1。技术栈从此是 Project Decision：可追溯、可推翻（9.2）。

**B2 Environment。** DevOps Agent 按 Decision 拆 Setup Tasks：安装运行时、创建虚拟环境、初始化前后端、建数据库、初始化 Git 仓库、CI、测试框架——可并行的全部并行。

**B3 Knowledge。** 建立 Project Knowledge Base（协议规范、AGENTS.md、参考仓库、架构文档、已有代码、历史 Decision），并构建 Project Knowledge Graph——4.4 中 Knowledge / Decision Graph 的实例化：

```text
AETP
 ├── optionally_uses → A2A（Transport Adapter，可选）
 ├── uses       → MCP
 ├── integrates → Git
 └── defines    → Verification
        ├── related_to     → Task
        ├── produces       → Evidence
        └── constrained_by → Governance
```

此后 Architect 在 Knowledge Graph + Project State 上工作，而不是每次重新「想」。

**Skills 设计也在 B3。** Skill 不是「一段提示词」，而是**可验证的能力模块**：走 Discovery → Design → Specification → Implementation → Verification，本身是一种 Artifact（10.1），挂入 Capability Registry（14.6）：

```yaml
skill:
  id: architecture.review
  version: "1.0"
  capabilities: [architecture.analysis, architecture.review]
  inputs: [blueprint]
  outputs: [architecture_review]
  acceptance: [...]
```

**B4 Infrastructure。** Git 分支策略、CI、测试框架、Lint / Formatter、构建、日志与可观测性、Migration。

**B5 Bootstrap Acceptance。** 「环境搭好了」不能是一句话。逐项验证 environment / dependency / build / test / git / knowledge，全部通过后产生 Bootstrap Acceptance——与 Mission Acceptance（5.2 / INV-019）同一思想——按 Mission Acceptance 完成固定版本证据与 CRITICAL 人类验收后，Project 的 phase 进入 `BOOTSTRAP_VERIFIED`（不是新的 Project status），才进入正式开发 Planning。初始目标、方案与环境设计的讨论无需等待此阶段。

**权限边界。** Bootstrap Agent 从第一天就遵守 Autonomy ≠ Unlimited Authority（P9）：

```text
工作区内创建目录 / 初始化 Git / 获准依赖安装    → Policy 允许范围内自动
系统级安装 / 提权 / 修改服务或防火墙 / 数据出域 → Approval
删除数据                                      → 按风险与作用域检查 Approval
读取凭据                                      → Credential Broker（14.3）
部署生产环境                                  → Approval
```

Bootstrap 也是 AETP 最好的第一个演示场景：用户只说「创建 AETP 项目」，UI 上各专职 Agent 依次完成侦察、决策、搭建与验证，最终呈现一份全部 `VERIFIED` 的 Bootstrap 清单——这比「Agent 写了一段代码」更能体现协议的价值。

---

## 16. 核心不变量

以下规则属于协议核心，实现时不得违背。「执行层」标注每条不变量在 Runtime 中的强制位置。

| ID | 规则 | 执行层 |
| --- | --- | --- |
| INV-001 | Agent 不得直接修改 Project State，必须通过合法 Protocol Operation | Command Handler |
| INV-002 | Message 不得直接代表 Decision | Collaboration / Governance |
| INV-003 | Agent Claim 不得直接代表 Verification | Verification Engine |
| INV-004 | Task 必须经过有效 Review、Verification 与适用的 Integration Gate 才能 COMPLETED；无集成面豁免须显式留痕 | Task Engine / Integration Gate |
| INV-005 | 历史 Event 不得被修改 | Event Store |
| INV-006 | 高风险 Action 必须经过 Governance Policy | Governance Engine |
| INV-007 | Blueprint 变更必须保留版本历史 | Planning Engine |
| INV-008 | Agent Identity 与 Model Identity 必须分离；Agent 之间平等独立，Role 不产生上下级或直接通信特权 | Agent Registry / Team / Collaboration |
| INV-009 | Task Dependency 不得形成循环 | Task Engine（DAG 校验） |
| INV-010 | Human Override 必须产生 Event | Governance Engine / Event Store |
| INV-011 | Agent 不得直接产生 Event，状态变更必须经由 Command 校验 | Command Handler |
| INV-012 | Agent 不得直接持有长期凭证，只能通过 Credential Broker 获取短期 scoped credential | Credential Broker |
| INV-013 | 外部工具调用必须在真实执行边界授权并留下受信 Action 审计；结果未知须对账而非盲目重试 | Runtime Enforcement / Tool Audit |
| INV-014 | Event 消费必须幂等，重复投递不得产生二次状态变更 | Event Store / Projection |
| INV-015 | State Store 是 Event Store 的 Projection，不得在 Event 之外被写入 | State Projection |
| INV-016 | Event 的 `sequence` 只能由 Event Sequencer 赋值，Agent Runtime 不得自行编号 | Event Sequencer |
| INV-017 | Task 进入 VERIFIED 必须有携带 evidence 且绑定当前输入快照的 Verification，并满足独立完成判定 | Verification Engine |
| INV-018 | 改变项目事实状态的行为必须落为 Durable Event，讨论过程不得写入 Event Store | Event Store |
| INV-019 | Mission 不得仅依据 Task 完成状态进入 COMPLETED，必须存在针对 Success Criteria 的 Acceptance Verification 并经 CRITICAL 级批准 | Governance Engine |
| INV-020 | 外部数据可以成为决策依据，但不得单独成为 Command 的授权来源 | Governance Engine / Input Trust Boundary |
| INV-021 | Orchestrator 不得持有 Event Store 之外的权威状态，重启后必须能从 Event Store + Projection 完整重建调度 | Orchestrator / State Projection |

### 16.1 已冻结的十一条区分

```text
① Agent ≠ Model ≠ Runtime ≠ Execution   身份、模型、运行时、执行实例四层分离
② Message ≠ Event            聊天不是系统事实
③ Discussion ≠ Decision      讨论不等于决定
④ Decision ≠ Approval        AI 提议不等于人类批准
⑤ Artifact ≠ Claim           Agent 说完成不等于完成
⑥ Review ≠ Verification      有人认可不等于有证据
⑦ COMPLETED ≠ VERIFIED       没有验证不算真正完成
⑧ Command ≠ Event            意图不是事实，必须经过校验
⑨ AETP ≠ Transport           A2A / HTTP / IPC 只是传输，AETP 是工程组织层
⑩ VERIFIED ≠ INTEGRATED      模块正确不等于集成后正确
⑪ Collaboration ≠ Shared Workspace   共享目录不产生协作语义，协作在 State 里
```

---

## 17. 版本范围

### 17.1 v0.1 覆盖范围

Agent Identity、Role、Team、Project、Mission、Blueprint、Task、Message、Discussion、Meeting、Decision、Approval、Artifact、Review、Verification、Event、Intervention、Task Dependency、Agent Routing、Human Governance、Failure Recovery。

以及第 14 章中的四项 P0 底层机制：**Command / Operation、Event Ordering 与 Idempotency、Credential Broker、External Action 审计**。

以及四项协议语义底线：**Verification 实体化（10.3）、Event Store → State Projection（13.4）、Command 完整 Schema（14.1）、Event Sequencer 归属（14.2）**。

以及规范性审查新增的三项 P0：**Integration Gate（10.6）、Mission Acceptance（5.2 / INV-019）、Input Trust Boundary（14.11 / INV-020）**。

### 17.2 最小可运行实现

v0.1 的最小实现按层分批，**不要求一次性实现全部 Entity**：

```text
Core Kernel      Project / Agent / Task / Command / Event
Execution        Artifact / Review / Verification
Collaboration    Message
Governance       Decision / Approval
```

运行时：`Orchestrator / Command Handler / Event Sequencer / Event Store / State Projection / Agent Router / Task Engine`

传输：进程内调用 + WebSocket 即可，不必先接入 A2A（见 2.4）。

M0 仅实现 Core Kernel 五个对象，随后按里程碑增量实现其余各层：M1 双 Agent + Message / Artifact / Lease / Checkpoint / Review / Verification，M2 Discussion / Meeting / Decision / Approval / Governance，M3 Team Formation / Blueprint / Task DAG / Integration / Mission Acceptance。每个里程碑的验收判据见《AETP-设计方案-补充建议》§3。

**M0 是协议内核验证，不是完整产品体验或完整 Bootstrap。** 它只以无危险外部效果的任务 / 模拟 Runtime 验证 Command、事件、版本、幂等、重启与重放，不得在缺少 Review / Verification 时把任务伪装成合规 COMPLETED。测试用断言不是 Verification 实体，也不能产生 Bootstrap Acceptance。

M1 接入 Message 与双 Agent 直接交流，同时具备 Artifact / Review / Verification、Lease / Checkpoint 与必要的执行边界；可用明确的无集成面低风险任务跑通小成果，但不能宣称完成第 15.5 节的完整 Bootstrap。M2 增加结构化讨论与治理；M3 补齐 Blueprint、Integration、Mission Acceptance 后，才把完整 Project Bootstrap 与「一个想法 → 讨论方案 → 成果验收」作为真实项目闭环。M0–M2 的有限演示不代替基本设定的最终验收。M1 只使用固定且版本化的低风险 Policy；完整 Approval 尚未实现时，需要审批的操作一律拒绝或留待 M2，不能把缺少审批模块解释为默认放行。

第一版不要求实现：Dynamic Team Evolution、Agent Evolution、Advanced Consensus、Ephemeral Agent Generation。

即使是最小实现，也必须从第一天就遵守写入顺序 `Command → Event Store → Projection`。这不是可以「先简单写、以后再改成事件溯源」的部分——反过来改代价极高。

同理，Orchestrator 从 M0 起就不得持有私有权威状态（13.10 / INV-021）。M0 的验收判据本身就是「杀掉进程重启后重放 Event 得到一致状态」，把调度状态放进内存会让这条判据永远无法通过。

### 17.3 明确不做

- Agent 自我修改（自动改 Prompt、人格、权限）。第一版允许 Agent 学习，但**不允许自行改变身份和权限**，否则容易从 Autonomous Engineering 变成 Autonomous Chaos。
- 完整的 Agent Evolution（`Agent v1 → v2 → v3`）推迟到 **v0.3**。v0.1 只记录 Performance、Experience、Skills、Failures 四类数据，不据此自动改写 Agent 定义。
- Long-term reputation market
- Cross-project Agent economy
- Federated Agent Network
- External Agent Marketplace

### 17.4 Conformance

声明完整「AETP Compatible」的 Runtime 必须保留平等直接协作语义（1.1 / 8.5），并通过所声明执行能力的强制边界测试（13.9）。仅观察、部分能力或 M0 内核演示须明确标注兼容范围，不能暗示具备尚未实现的保证。完整实现至少必须实现实体 `Agent / Project / Task / Command / Message / Event / Decision / Approval / Artifact / Review / Verification`，以及 Task Lifecycle、Event Model、Permission Model、Agent Identity、Command 校验链路、Event Store 与 State Projection 的分离。

### 17.5 版本规则

遵循 Semantic Versioning：PATCH 为缺陷修复与措辞澄清，MINOR 为向后兼容的协议新增，MAJOR 为破坏性变更。

对象级 `schema_version`（4.3）与协议版本独立演进，使 Migration 可以逐对象进行。

### 17.6 协议补全优先级

冻结前不再新增功能，只补齐底层机制与协议语义。优先级如下：

| 优先级 | 项目 | 归属版本 |
| --- | --- | --- |
| 🔴 P0 | Command / Operation（14.1） | v0.1 |
| 🔴 P0 | Command Schema、身份绑定、版本校验与原子幂等提交（14.1） | v0.1 |
| 🔴 P0 | Event Ordering / Idempotency（14.2） | v0.1 |
| 🔴 P0 | Event Sequencer 归属（14.2） | v0.1 |
| 🔴 P0 | Event Store → State Projection（13.4） | v0.1 |
| 🔴 P0 | Verification 实体化（10.3） | v0.1 |
| 🔴 P0 | Credential / Secret Boundary（14.3） | v0.1 |
| 🔴 P0 | Tool Audit、持久化派发、UNKNOWN 与外部效果对账（14.4） | v0.1 |
| 🔴 P0 | Integration Gate（10.6） | v0.1 |
| 🔴 P0 | Mission Acceptance（5.2 / INV-019） | v0.1 |
| 🔴 P0 | Input Trust Boundary（14.11 / INV-020） | v0.1 |
| 🔴 P0 | Runtime Adapter Contract 与可验证执行强制边界（13.9） | v0.1 |
| 🔴 P0 | Task 权威归属与执行映射（7.10） | v0.1 |
| 🔴 P0 | Execution Binding 与 Lease epoch / fencing（5.13 / 7.6） | v0.1 |
| 🔴 P0 | Runtime Capability 与 Capability Negotiation（13.9 / 6.4） | v0.1 |
| 🟠 P1 | Claim Schema（8.2） | v0.1 |
| 🟠 P1 | Approval Target、Mission 与审批快照绑定（9.3） | v0.1 |
| 🟠 P1 | Intervention → Command → Event（9.7） | v0.1 |
| 🟠 P1 | Durable Event vs Ephemeral Communication（14.10） | v0.1 |
| 🟠 P1 | Task `due_at` 与 `task.overdue`（7.2） | v0.1 |
| 🟠 P1 | Task `CANCELLED` 语义与原因字段（7.3） | v0.1 |
| 🟠 P1 | 统一 `supersedes` 关系（11.5） | v0.1 |
| 🟠 P1 | Data Classification（10.1 / 12.1，仅 Schema） | v0.1 |
| 🟠 P1 | Failure Domain 归因（11.4） | v0.1 |
| 🟠 P1 | Conformance Test Specification（18.3） | v0.1 |
| 🟠 P1 | Approval 委托与 EXPIRED 后续路径（9.3） | v0.1 |
| 🟠 P1 | Governance Clock 与调度 / 执行暂停分离（5.1 / 13.4） | v0.1 |
| 🟠 P1 | Orchestrator 无状态恢复（13.10 / INV-021） | v0.1 |
| 🟠 P1 | Workspace Provider Contract（13.9，隔离与 merge 冲突返回） | v0.1 |
| 🟠 P1 | Agent Initiated Action（8.7，Agent 作为发起方） | v0.1 |
| 🟠 P1 | Resource Ledger / Budget（14.5） | v0.1.x / v0.2 |
| 🟠 P1 | Capability Registry（14.6） | v0.1.x / v0.2 |
| 🟠 P1 | Artifact Provenance（14.7） | v0.1.x / v0.2 |
| 🟠 P1 | Concurrency / Lock（14.8） | v0.1.x / v0.2 |
| 🟠 P1 | Error Model（14.9） | v0.1.x / v0.2 |
| 🟡 P2 | Schema Version 与 Migration（4.3） | v0.1 |
| 🟡 P2 | Agent Evolution | v0.3 |
| 🟡 P2 | Cross-project Agent Reputation | v0.3+ |
| 🟡 P2 | Agent Marketplace | v0.3+ |

P0 十五项必须进入 v0.1。前六项（Command / Operation 至 Verification 实体化）属于**协议语义层面的歧义**——歧义不修掉，两个 Runtime 实现同一份规范会得到不同行为；第 7–8 项（Credential Boundary / Tool Audit）是**治理与审计的地基**——缺了它们，Governance Policy 管不到 Agent 实际做了什么；第 9–11 项（Integration Gate / Mission Acceptance / Input Trust Boundary）属于**验证与安全闭环的断点**——不补上，并行开发与完全托管都不可信；末四项（Runtime Adapter Contract / Task 权威映射 / Execution Binding / Runtime Capability 与 Negotiation）属于**与外部 Runtime 对接的协议接口**——没有它们，协议无法被任何真实 Coding Agent 实现。

标为 v0.1 的 P1 十五项是 Schema 与规则级补充，实现成本低但影响协议语义，同样进入 v0.1。标为 v0.1.x / v0.2 的 P1 五项**可以延后实现，但协议接口必须现在预留**——否则 Runtime 写到一半必然返工。P2 中除 Schema Version 外明确不进 v0.1（见 17.3）。

---

## 18. 下一步计划

### 18.1 落地为机器可读规范

```text
AETP/
├── SPEC.md
├── schemas/
│   ├── project.schema.json
│   ├── agent.schema.json
│   ├── team.schema.json
│   ├── mission.schema.json
│   ├── blueprint.schema.json
│   ├── task.schema.json
│   ├── message.schema.json
│   ├── meeting.schema.json
│   ├── decision.schema.json
│   ├── approval.schema.json
│   ├── artifact.schema.json
│   ├── review.schema.json
│   ├── verification.schema.json
│   ├── event.schema.json
│   └── intervention.schema.json
├── protocol/
│   ├── state-machine.md
│   ├── permissions.md
│   ├── communication.md
│   ├── commands.md
│   ├── events.md
│   ├── projection.md
│   ├── routing.md
│   ├── governance.md
│   ├── runtime-adapter.md
│   ├── workspace.md
│   └── error-codes.md
└── examples/
    └── autonomous-project.yaml
```

`schemas/` 还需补齐 `command.schema.json`、`claim.schema.json`、`action.schema.json`、`capability.schema.json`、`error.schema.json`，与第 14 章一一对应。每个 schema 必须包含 `schema_version` 字段（4.3）。

`protocol/projection.md` 需明确规定：哪些 Event 影响哪些 State 字段、Projection 的重建流程、以及重放时的幂等要求（13.4）。`protocol/runtime-adapter.md` 与 `protocol/workspace.md` 分别落 13.9 的两组契约——前者是控制面 / 上报面与 Runtime Capability，后者是 Workspace Provider 的隔离要求与 `merge()` 冲突返回。

### 18.2 协议验证与故障注入

在写 Runtime 之前，先拿一个真实项目做完整推演，验证协议是否存在缺字段、状态机漏洞或规则冲突。**这个过程暴露的问题会远多于继续头脑风暴。**

推演样例：Prediction Market Intelligence Platform，模拟 8 个 Agent（Manager、Architect、Market Research、Data Engineer、Probability Engineer、Backend、Frontend、QA/Security），从一句「做一个预测市场智能分析平台」开始，逐步跑完：

```text
Mission → Team Formation → Agent Contract → Meeting → Evidence
→ Decision → Blueprint → Task DAG → Claim → Execution → Handoff
→ Review → Checkpoint → Failure → Recovery → Replanning → Delivery
```

**关键是不能只推演顺利路径。** 必须故意注入以下 22 类事故，逐条检验协议能否优雅处理：

```text
①  Agent 崩溃
②  API Rate Limit
③  两个 Agent 同时修改同一文件
④  Agent 意见严重冲突
⑤  Decision 被推翻
⑥  Blueprint 中途修改
⑦  Task Lease 过期
⑧  Agent 误用权限
⑨  工具调用失败
⑩  一个 Agent 提交错误代码
⑪  人类半路改变需求
⑫  两个已通过 Review 的分支合并后语义互相破坏
⑬  所有 Task 均 Verified 但 Mission Acceptance 失败
⑭  审批长期无人处理直至 EXPIRED
⑮  Orchestrator 进程中途重启
⑯  Event 已提交但 Command 响应丢失，同键重试及同键异内容
⑰  外部动作已成功但回执丢失，或记录派发后尚未调用即崩溃
⑱  Lease 换代后旧执行恢复并尝试推进任务 / 合并
⑲  审批后改参数、验证后改代码 / 测试 / 验收标准或目标分支前进
⑳  PAUSED 后仍收到在途结果；Runtime 不支持彻底暂停
㉑  冒用 actor、绕过工具代理、越界访问及隐藏输入来源
㉒  不配置 Manager 或当前协调者失联，成员仍需讨论并交付
```

每一类都对应协议中已设计的机制——分别是 Recovery（11.4）、Agent Resources（5.7）、并发模型（14.8）、Disagreement 与升级（8.15 / 8.16）、Decision Reversal（9.2）、Change Request（11.1）、Task Lease（7.6）、Command 校验（14.1）、Tool Audit 与 Error Model（14.4 / 14.9）、Review 与 Verification（10.2 / 10.3）、Intervention（9.7）、Integration Gate（10.6）、Mission Acceptance（5.2 / INV-019）、审批委托与 `on_expire` 升级路径（9.3）、Orchestrator 无状态恢复（13.10 / INV-021）。新增 ⑯–㉒ 分别对应原子提交与命令去重（14.1）、外部效果对账（14.4）、Lease fencing（7.6）、审批 / 验证快照与合并基线（9.3 / 10.3 / 10.6）、暂停屏障（13.4）、可信身份与执行边界（13.9 / 14.11）、平级直接协作与可替换协调职责（1.1 / 8.5 / 13.1）。**如果每条都能走通且留下完整可追溯记录，协议才算可以冻结。**

验证的判据不是「系统没崩」，而是四条：

```text
① 每个故障都能被协议现有机制处理，不需要临时加规则
② 事故过后 Event Store 能完整回答「刚才发生了什么、为什么」
③ 删掉 State Store，重放 Event 能得到完全一致的项目状态
④ 同一 Command（相同 idempotency_key）重复投递，不得产生二次状态变更
```

第三条与第四条尤其关键——它们同时验证了 Event Sequencer、Projection 与幂等三项机制（13.4 / 14.2 / 14.1），也是 M0 验收的最低门槛。

推演过程中发现的字段缺失与规则冲突回写协议。**跑完这一轮，AETP v0.1 才算真正冻结。**

### 18.3 Runtime Adapter 先行验证与 Conformance

协议验证不应止于纸面推演。v0.1 冻结前的工程顺序：

```text
Protocol Core → Runtime Adapter（Codeg 作为第一个 Adapter）
→ Conformance Test → Fault Injection → Real Project → FREEZE
```

拿 Codeg 严格按 13.9 接入，记录每一处「卡住」的位置——卡点就是协议歧义或 Adapter Contract 的缺口，回写协议。这个过程比继续理论设计更容易暴露真正的问题。

同时把 17.4 的 Conformance 从文字声明落成可执行测试套件：

```text
conformance/
├── agent/        ├── task/       ├── command/    ├── event/
├── projection/   ├── governance/ ├── verification/
├── workspace/    └── recovery/
```

示例用例（每条对应至少一条不变量或冻结区分）：

```text
TEST-001  同键同内容重试返回原结果，不重复提交领域 Event 批次（INV-014 / 14.1）
TEST-002  Agent 不得直接修改 State（INV-001）
TEST-003  Task 不得跳过 Review / Verification 进入 VERIFIED（INV-017）
TEST-004  未经 Approval 的高风险 Command 必须拒绝（INV-006）
TEST-005  删除 State Store 后重放 Event 得到一致状态（INV-015）
TEST-006  Agent 崩溃后 Task 可按 Lease 重新分配（7.6）
TEST-007  Untrusted Input 不得直接授权 Command（INV-020）
TEST-008  Review 通过但 Verification 缺失不得 VERIFIED（16.1 ⑥）
TEST-009  有集成面任务未经 Integration Gate 不得 COMPLETED；豁免必须显式留痕（INV-004）
TEST-010  Mission Acceptance 失败不得 Delivery（INV-019）
TEST-011  Approval 过期后必须产生升级路径，不得静默悬挂（9.3）
TEST-012  Orchestrator 重启后调度状态完整恢复（INV-021）
TEST-013  Agent 主动发起的协作与 Orchestrator 下发走同一条 Command 校验路径（8.7）
TEST-014  工作副本不相互污染；声称安全隔离的 Provider 还须阻止越界访问（13.9）
TEST-015  无 Manager 的 Agent A / B 可直接发言、回复、质疑与提案；独立审查不要求接管被审 Task，无职级前置（1.1 / 7.6 / 8.5 / 10.3）
TEST-016  伪造 actor 或冒用他人 Binding 不得取得执行权（13.9 / 14.1）
TEST-017  提交 Event 后、返回响应前崩溃，恢复重试得到原结果且无重复效果（14.1）
TEST-018  同幂等键异内容被拒绝；释放后用新键可合法再次认领（14.1）
TEST-019  两个 Agent 基于同一旧版本认领，最多一个成功并保持 Lease / Binding 一致（7.6 / 14.1）
TEST-020  外部结果 UNKNOWN 时查询 / 对账，不重复创建资源或发布（14.4）
TEST-021  Replay 不执行模型、Shell、Runtime.start 或已确认的工具动作（13.4 / 13.10）
TEST-022  新代次生效后旧执行可留档但不能推进 Task / 合并；已在途效果仍对账（7.6）
TEST-023  审批后改变目标 / 参数被拒绝；Mission 审批绑定准则与交付快照（9.3）
TEST-024  更换代码、测试集、环境或验收标准后旧验证不能自动放行；合并基线检查有效（10.3 / 10.6）
TEST-025  PAUSED 继续记录在途事实而不派发；重启保持暂停，不把软暂停显示成彻底停止（13.4）
TEST-026  绕过代理执行高风险操作被真实边界阻止；未具备能力不得宣称完整兼容（13.9）
TEST-027  输入来源标记跨 Agent 转述保留；来源未知按不可信处理，但普通讨论不要求审批（14.11）
TEST-028  两个以上平等 Agent 从粗糙想法讨论方案并按方案交付，无 Manager 必经路径（1.1 / 15.1）
```

`schemas/` 的每个 schema 配 valid / invalid 成对夹具，使「AETP Compatible」成为可跑的断言，而不是自述。以上 28 项是**待实现与执行的验收要求，不是本次文档修订已通过的测试结果**。

每例至少固定初始 State / Event、输入 Command 或 Message、Runtime 能力、故障注入点、预期错误 / 事件 / 状态与重放结果。TEST-028 的通过条件是：用户只提供粗糙想法；至少两个成员互相回应并形成可追溯方案；按方案认领 / 协作执行，产出固定版本成果并完成适用质量门与验收；人类只在策略规定的关键点介入，不人工拆任务，也不由隐藏主 Agent 代替成员讨论。

无集成面的低风险小成果可按 7.3 明确豁免，不能据此宣称已验证代码集成路径。消息速率 / 预算护栏可以阻止无限广播，但不能成为按角色禁止普通直接对话的理由。

---

## 19. 一句话定义

> **AETP 是一个定义 AI Agent 如何作为工程团队成员，在共享项目中进行讨论、决策、分工、执行、审核，并在人类治理下自主完成软件工程任务的协作协议。**

```text
AETP
 ├── Transport   A2A / HTTP / WebSocket / IPC / MQ
 ├── MCP         Tool / Resource access
 ├── AGENTS.md   Project instructions
 └── Git         Source of truth
```

而它要回答的问题，最终只有一个：

```text
Human Intent → Mission → Proposal → Decision → Approval
→ Command → Event → Task → Artifact → Review → Verification
→ Integration → Delivery
```

---

## 附录 A：设计演进溯源

本方案由十七轮设计对话、一轮文档一致性评审、一轮架构边界修订与一轮基本设定确认及执行契约修订汇总整理而成，各轮主题与产出如下：

| 轮次 | 主题 | 主要产出 | 对应章节 |
| --- | --- | --- | --- |
| 01 | 现有工具调研 | ClaudeLink / DeerFlow / Agent Team 等方案对比；「让一个 AI 公司托管项目」的初始构想 | 1.4、1.5 |
| 02 | 自研决策与 MVP | 决定自研；复用现成 Coding Agent 而非重新实现；Team Bus / Agent Council 构想；技术栈初选 | 1.6、13.5、13.6 |
| 03 | 产品定义 | 个人 AI 开发基础设施；Idea → Debate → Blueprint → Approval 七阶段闭环；Project Memory；L0–L4 自主等级 | 1.1–1.3、9.4、12.3、15.1 |
| 04 | 通信设计 | Message / Task / Event / Document 职责分离；Subscription 订阅；引用回复链；频道制 | 8.1、8.4–8.6 |
| 05 | 协议选型 | 确认 A2A / MCP / AGENTS.md / Git 为底座；「通信底座 + 团队语义」两层划分 | 2、2.2 |
| 06 | 协议命名与对象 | 正式命名 AETP；核心对象初稿；Context Package；「v0.1 只解决三个问题」的范围克制 | 4、12.1、17 |
| 07 | 协议映射 | 对照 A2A 1.0 的对象映射表；Message ≠ Event；Meeting Protocol 与独立分析；核心原则定型 | 2.1、8.9、8.10、3 |
| 08 | 数据模型与状态机 | 核心实体与各状态机；Capability / Permission / Authority 三层权限；七条冻结区分 | 4.2、5.5、7.3、16.1 |
| 09 | 协作语义 | Assistance Request、Agent Router、Task DAG、Opinion Weight、Consensus Engine、三种运行模式、Recovery | 6.4、7.4、7.9、8.12–8.16、9.6、11.4 |
| 10 | 动态组队 | Role Graph、Agent Pool、Selection Score、Ephemeral Agent、Team Evolution、四引擎划分 | 6、5.6、13.2 |
| 11 | 规范成稿 | AETP v0.1 Specification 全文；INV 不变量；机器可读规范目录计划 | 全文、18.1 |
| 12 | 补漏（一） | Agent 生命周期、Agent Resources、Agent Contract、Task Lease、Checkpoint、Evidence、Disagreement 而非强制共识、Memory Layers、Agent Activity Stream | 5.4、5.7、5.9、7.5–7.7、8.11、8.15、12.3、13.8 |
| 13 | 补漏（二） | Command / Operation、Event Ordering 与幂等、Credential Broker、Tool Audit、Resource Ledger、Capability Registry、Provenance、并发与冲突、Error Model、Transport Adapter 解耦 | 14、2.4 |
| 14 | 冻结前修订 | Verification 实体化、Event Store → State Projection、Event Sequencer 归属、Claim 结构、Approval Target、Intervention → Command → Event、Durable vs Ephemeral、Project Clock | 10.3、13.4、14.1、14.2、8.2、9.3、9.7、14.10、5.1 |
| 15 | 规范性审查（进入协议验证前） | Integration Gate 状态机（VERIFIED ≠ INTEGRATED 成为第十条冻结区分）、Mission 验收升 P0（INV-019）、输入信任边界（INV-020）、失败归因与选型维度拆分、会议预算、Task `CANCELLED` / `due_at` / `supersedes`、数据分级 Schema 预留、INV 扩充至 INV-020 并标注执行层、最小实现分层（M0 仅 Core Kernel）、故障注入增至 13 类并新增幂等判据 | 7.3、10.6、16.1、5.2、14.11、5.6、6.4、8.14、7.2、11.5、10.1、16、17.2、18.2 |
| 16 | Runtime 对接与可实现性 | Runtime Adapter Contract（Codeg 为首个验证对象）、Task 权威归属与执行映射、Execution Binding（冻结区分①升级为四层分离）与 Effective Capability、Capability Negotiation 两阶段路由、Failure Domain 归因、Conformance Test Specification 与冻结前工程顺序（Adapter → Conformance → Fault Injection → Real Project → FREEZE） | 13.9、7.10、5.13、16.1、6.4、11.4、18.3、17.6 |
| 17 | Project Bootstrap | 开发前标准初始化阶段：B0 环境侦察（环境信息必须是 Evidence）、B1 技术栈决策（Architecture Meeting → Decision）、B2 环境搭建、B3 Skills（可验证能力模块）/ 知识库 / 知识图谱、B4 工程基础设施、B5 Bootstrap Acceptance；Mission #0 概念；Bootstrap 权限边界；M0 首个真实 Mission | 15.5、5.2、15.1、17.2、14.6 |
| 18 | 文档一致性评审与治理补缝 | 审批委托、事后否决（`REVOKED`）与 `on_expire` 升级路径、`requested_by / approver / delegated_to` 三方分离；Governance Clock（治理时间与墙钟分离，凭证为例外）；Orchestrator 无状态恢复（INV-021）；新增 `approval.*` 与 `project.resumed` 事件；故障注入扩至 15 类、Conformance 扩至 12 例；一致性修正：Team Formation 不再占用 Mission 编号、17.6 中 P0 序号引用、轮次计数 | 9.3、5.1、13.10、16、10.4、18.2、18.3、6.1、17.6 |
| 19 | 架构边界修订（Codeg 复审后） | 协作层与执行层分离（Team Collaboration ≠ Shared Workspace，立为冻结区分⑪与 P11）；平级不等于无协调者（`Agent ≠ Orchestrator`，立为 P10）；第一阶段目标改为共享 Project 而非共享 Workspace 的六件事；调研对象按 Transport / Runtime / Workspace 分层重新归类，Codeg 定位为下层执行基础设施而非竞争协议；13.5 改为「通过 Runtime Adapter 驱动 Runtime 执行 AETP Task」；Adapter 三分并新增 Workspace Provider 契约（隔离要求与 `merge()` 冲突返回）；Execution ≠ Session、Task ↔ Binding 一对多；Agent Initiated Action 正名为标准形态；`protocol/` 增 runtime-adapter / workspace 两篇，Conformance 扩至 14 例并新增 `workspace/` 组。**未新增协议实体，4.2 实体表不变** | 1.4、1.5、1.6、3、5.11、5.13、8.7、13.1、13.5、13.9、16.1、17.6、18.1、18.3 |

| 20 | 基本设定确认与执行契约修订 | 用户确认核心：投入想法、平等 Agent 直接讨论方案并产生成果，Agent 无从属关系；移除 Hierarchical 与 Manager 必经节点；补齐 Command 原子事务 / 幂等、外部效果 UNKNOWN / 对账、Runtime 强制边界、Lease epoch、审批与验证快照、暂停与纯重放；统一 Task 迁移与上报语义；修正 M0 范围，故障注入 22 类与 Conformance 28 例。未新增顶层实体、未宣称完成 Runtime 实现验证 | 1.1、5.11、6.2、7.3–7.6、8.5、9.3、10.3、13.1、13.4、13.9–13.10、14.1、14.4、14.11、15.1、17.2、18.2–18.3 |

十七轮对话原文是本协议的「制宪记录」，建议归档至 `Docs/history/`（当前不在本仓库内）。



















