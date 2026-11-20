# AETP 全协议 Conformance 测试套件架构设计与执行规范

## 1. 规范背景与定位

依据《AETP-设计方案.md》§§13.4, 13.9, 14.1–14.4, 15.1, 16, 17.4, 18.3：
全协议 Conformance 测试套件（Conformance Test Specification）是评定实现是否符合 AETP 规范的可执行基准，包含 28 个核心测试用例（TEST-001 至 TEST-028）。

在开发准备期（M0–M3）阶段，各领域的机制逻辑已逐步实现并在单元/集成测试中得到验证。本测试套件的目标是构建**全协议统一的 Conformance 调度器与夹具执行体系**，使协议规范从离散测试集收敛为统一的可执行断言与结构化合规报告。

---

## 2. 核心架构与领域分类

按照规范 §18.3 推荐结构，28 项 TEST 分为七大测试领域：

```text
conformance/
├── runner.py               # 统一调度器与 CLI 入口
├── suites/
│   ├── command_event.py    # TEST-001, 002, 005, 013, 017, 018, 021 (事实链与事务)
│   ├── governance.py       # TEST-004, 007, 011, 023, 025, 027 (治理、审批与输入边界)
│   ├── task_lease.py       # TEST-003, 006, 016, 019, 022 (Task 状态机、Lease 与并发)
│   ├── collaboration.py    # TEST-015, 028 (平等 Agent、无 Manager 协商与自主交付)
│   ├── integration.py      # TEST-009, 024 (Integration Gate 与基线保护)
│   ├── acceptance.py       # TEST-008, 010 (Verification 与 Mission 逐条验收)
│   └── runtime.py          # TEST-012, 014, 020, 026 (Orchestrator 恢复、隔离与边界)
```

---

## 3. 28 项 Conformance 映射矩阵

| TEST ID | 规范章节 | 核心不变量 / 规则 | 验证重点与断言 |
|---|---|---|---|
| TEST-001 | 14.1 | INV-014 | 同键同内容重试返回原结果，不重复提交领域 Event 批次 |
| TEST-002 | 14.1 | INV-001 | Agent 不得直接修改 State，必须通过 Command 事实链 |
| TEST-003 | 7.3, 10.3 | INV-017 | Task 不得跳过 Review / Verification 进入 VERIFIED |
| TEST-004 | 9.3 | INV-006 | 未经 Approval 的高风险 Command 必须被拒绝 |
| TEST-005 | 14.2 | INV-015 | 删除 State Store/缓存后纯重放 Event 得到完全一致状态 |
| TEST-006 | 7.6 | Lease | Agent 崩溃后 Task 可按 Lease 租期超时安全重新分配 |
| TEST-007 | 14.11 | INV-020 | Untrusted Input 不得直接授权 Command |
| TEST-008 | 10.3, 16.1 | 冻结区分⑥ | Review 通过但 Verification 缺失不得标记 VERIFIED |
| TEST-009 | 7.3, 10.6 | INV-004 | 有集成面任务未经 Integration Gate 不得 COMPLETED |
| TEST-010 | 5.2 | INV-019 | Mission success_criteria 未全过或终验未通过不得 Delivery |
| TEST-011 | 9.3 | Governance | Approval 过期后必须产生明确升级路径，不得静默悬挂 |
| TEST-012 | 13.10 | INV-021 | Orchestrator 重启后从 Event Store 恢复调度状态 |
| TEST-013 | 8.7 | Architecture | Agent 主动发起的协作与调度下发走同一条 Command 校验路径 |
| TEST-014 | 13.9 | Provider | 工作副本不相互污染，跨工作区越界访问被阻断 |
| TEST-015 | 1.1, 7.6 | Equal Peer | 无 Manager 的 Agent 可直接对话、提案，独立审查无职级前置 |
| TEST-016 | 13.9, 14.1 | Security | 伪造 actor 或冒用他人 Binding 无法取得执行权 |
| TEST-017 | 14.1 | Recovery | 提交 Event 后响应前崩溃，重试得到原结果且无重复副作用 |
| TEST-018 | 14.1 | Idempotency | 同幂等键异内容拒绝；释放后用新键可合法再次认领 |
| TEST-019 | 7.6, 14.1 | Concurrency | 两个 Agent 基于同一旧版本认领，CAS 保证至多一个成功 |
| TEST-020 | 14.4 | External | 外部结果 UNKNOWN 时查询/对账，不重复创建资源或发布 |
| TEST-021 | 13.4, 13.10 | Replay | Replay 不执行模型调用、Shell 执行或已确认工具动作 |
| TEST-022 | 7.6 | Epoch | 新代次生效后旧执行无法推进 Task 合并；在途效果对账 |
| TEST-023 | 9.3 | Governance | 审批后改变目标/参数被拒绝；Mission 审批绑定交付快照 |
| TEST-024 | 10.3, 10.6 | Integration | 更换代码/基线后旧验证不自动放行；合并基线前移被拦截 |
| TEST-025 | 13.4 | Governance | PAUSED 继续记录在途事实而不派发；重启保持暂停状态 |
| TEST-026 | 13.9 | Execution | 绕过代理执行高风险操作被真实边界阻止 |
| TEST-027 | 14.11 | Trust | 输入来源标记跨 Agent 保留；普通讨论不强制要求审批 |
| TEST-028 | 1.1, 15.1 | End-to-End | 两个以上平等 Agent 从粗糙想法直接讨论方案并交付，无 Manager |

---

## 4. 执行规范与退出码

1. **环境与数据独立性**：
   - 每次运行必须使用全新的测试数据库与证据目录；
   - 绝不使用业务生产数据库，不修改全局环境。
2. **两级状态标准**：
   - `status`: `passed`（功能完全覆盖且断言通过）、`pending`（受控范围内部分覆盖）、`failed`（失败）；
   - `execution.status`: `passed / failed / not_run`（当次实际执行事实）。
3. **退出码约定**：
   - `0`: 所有已纳入范围的测试用例均执行通过且断言一致；
   - `1`: 存在测试断言失败或异常；
   - `2`: 参数、文件路径或数据库 I/O 错误。
