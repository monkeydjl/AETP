# AETP 故障注入测试矩阵设计方案（Fault Injection Suite Specification）

## 1. 规范定位与背景

依据《AETP-设计方案.md》§18.2、§11.4、§14.1-14.4、§16：
协议验证不应止于常规的成功路径。为了确保 AETP 在分布式、多 Agent 协作和各类环境异常下的**反脆弱性（Anti-fragility）**，在代码冻结前必须建立系统化的故障注入测试套件（Fault Injection Suite）。

验证的判据不是“系统没崩”，而是四个刚性标准：
1. **现有机制闭环**：每个故障都能被协议现有机制处理，不需临时补丁或特权放行；
2. **事实链完备性**：事故过后 Event Store 能完整追溯“刚才发生了什么、由谁引起、为什么被拒绝/恢复”；
3. **纯重放确定性**：删掉 State Store / 派生缓存，重放 Event 能得到完全一致的项目状态；
4. **幂等零副作用**：同一 Command（相同 idempotency_key）重复投递或冲突投递，不得产生二次状态变更或副作用污染。

---

## 2. 15 类核心故障矩阵（FI-01 至 FI-15）

依据方案 §18.2 与前序设计，将最核心的 15 类事故分类映射至协议对应机制：

| 故障编号 | 故障名称 | 模拟场景与注入方式 | 对应协议机制与章节 | 预期恢复行为与断言 |
|---|---|---|---|---|
| **FI-01** | Agent 进程崩溃 | Agent 进程在持有 Task 期间异常退出 | Task Lease 租约机制（§7.6, §11.4） | 租约超时后可由其他 Agent 重新认领，原 binding 自动解绑 |
| **FI-02** | 提交后响应丢失（半死锁） | Event 已写入数据库，客户端未收到响应前网络断开 | 原子事务与 Command 幂等收据（§14.1） | 重投返回原执行结果，Event 数量不增加，零重复副作用 |
| **FI-03** | 幂等键冲突与漂移 | 相同的 idempotency_key 发送不同的 Command payload | 幂等摘要比对（§14.1 / INV-014） | 严格拒绝 IDEMPOTENCY_CONFLICT，事实链不受污染 |
| **FI-04** | 并发 CAS 竞争 | 两个 Agent 基于相同的 expected_revision 尝试认领同一 Task | 乐观锁与代次 CAS（§7.6 / §14.1） | 恰好一个成功，另一个被 REVISION_CONFLICT 拒绝 |
| **FI-05** | 状态投影缓存丢失 | 突然删除 State Store / Projections 缓存表 | Projection.rebuild 纯重放（§14.2 / INV-015） | 纯凭 Event Store 完全重建出一模一样的业务投影状态 |
| **FI-06** | 外部动作 UNKNOWN | 外部工具调用超时或状态不明（如磁盘根路径消失） | Tool Reconcile 外部对账（§14.4） | 记录 unknown 状态，触发 query 对账，绝不盲目重复执行 |
| **FI-07** | 越权身份冒用 | 请求声明的 actor_id 与通信层 authenticated_actor_id 不符 | Boundary Authentication（§13.9, §14.1） | 边界守卫拦截并拒绝 ACTOR_MISMATCH，审计留痕 |
| **FI-08** | 未经审批的高风险调用 | 试图在未获 Approval 授权下激活关键状态（如 mission.activate） | Governance Policy 引擎（§9.3 / INV-006） | 拒绝 PERMISSION_DENIED 或 ENFORCEMENT_UNAVAILABLE |
| **FI-09** | 审批参数事后篡改 | 获得针对参数 A 的 Approval 后，试图使用该 Approval 执行参数 B | Approval Binding Snapshot（§9.3） | 授权检查失败，拒绝 APPROVAL_STALE，阻止越界执行 |
| **FI-10** | 审批超时无响应 | 审批在有效 TTL 内未获处理 | on_expire 升级路径（§9.3） | 自动超时流转为 expired，并根据策略触发 escalate 升级通知 |
| **FI-11** | 项目暂停期间的操作推进 | Project 处于 PAUSED 状态时尝试提交配置或任务变更 | Governance Clock 与暂停屏障（§13.4, §5.1） | 拒绝 PROJECT_PAUSED，在途计时冻结，事实链保持静止 |
| **FI-12** | 任务跳级完成（逃避门禁） | Task 未经 in_review 或缺少 Verification 直接请求完成 | Task Quality 状态机与门禁（§7.3, §10.3 / INV-017） | 拦截 INVALID_TRANSITION 或 QUALITY_GATE_NOT_MET |
| **FI-13** | 目标代码基线前移（合并冲突）| Git 分支目标 target commit 已被他人推进 | Integration Gate 基线保护（§10.6 / TEST-024） | 阻止合并并抛出 BASELINE_ADVANCED，要求对齐最新基线 |
| **FI-14** | 跨工作区非法访问 | Agent 试图操作不属于当前 Workspace Provider 的路径 | Provider 隔离与安全边界（§13.9 / INV-020） | 拒绝 WorkspaceViolation，阻止跨租户或跨沙箱渗透 |
| **FI-15** | 不可信输入渗透核心命令 | 来自不可信渠道的消息输入直接试图驱动高特权变更 | Input Authority & Receipt 验证（§14.11 / INV-020）| 缺少有效受信收据直接拒绝 INPUT_CONTEXT_INVALID |

---

## 3. 测试架构与报告规范

测试套件将组织在 `tests/fault_injection/` 与 `src/aetp/testing/fault_injection/`：
- `runner.py`: 统一调度器，支持命令行与全量运行；
- `cases.py`: 15 类故障的独立测试夹具；
- 输出标准报告至 `artifacts/fault-injection-report.json`。
