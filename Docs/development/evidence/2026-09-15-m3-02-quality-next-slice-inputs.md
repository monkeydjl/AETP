# M3-02 Task 质量批次之后的输入核对

本文件是下一批设计的输入清单，不是已实现功能、独立接受或新的执行授权。Task 质量候选的正式接受以本批独立报告及消费收据为准；M3-02 的三个原验收条件保持未接受。主规范、知识图谱和旧证据不因本文改变。

## 已有能力及适用范围

- `TaskQualityService` 为固定文档提供显式加入、完整成果提交、独立 Review、轮次证据使用、返工和受控完成。`Command.expected_revision` 仍完整校验。
- 受信 JSON Runner 已有真实 `PASSED / FAILED / INCONCLUSIVE`、独立 QA Task/Session、单次派发、不可变结果与 abandoned 恢复；使用已完成证据时不把派发 TTL 当作证据最大年龄。
- 具体 Task 只有在当前 human_owner 的版本化 `standalone_fixed_json_document` 声明及明确 Governance 许可下，才能经双事实豁免完成。它没有权威的真实集成需求识别能力，不能证明需要集成的成果已经通过 Integration Gate。
- 已完成 Task 的 Lease/Binding 退役；旧执行入口不能复活终止态。完成事实不能推导 Mission、Bootstrap 或 TEST-028 成功。
- 本批候选与基线入口：`artifacts/m3-02-quality-test-report-v1.json`、`2026-09-15-m3-02-quality-candidate-v1-snapshot.json`、`2026-09-15-m3-02-quality-baseline.json`。开始下一批源代码修改前，另存本批所有冻结输入、独立结果及最终收尾证据；不能继续以 live 文件代替历史来源。

## 原验收条件与缺口

| 原条件 | 原始依据 | 下一批必须补足的事实 |
| --- | --- | --- |
| 集成面任务通过 Integration Gate | §7.3、§10.6、INV-004、TEST-009/024 | 权威集成目标、固定源与目标 commit、受保护引用更新的实际边界、冲突事实及结果 commit 的新系统 Verification |
| Mission success criteria 逐条 Acceptance Verification | §5.2、§9.3–9.4、§10.3、INV-019、TEST-010/023 | 固定 Mission revision、每条准则与交付集合、逐条验收证据、绑定相同快照的 CRITICAL 人类批准 |
| 至少两名平等 Agent 从粗糙想法讨论到交付 | §1.1、§8.5、§13.1、§15.1、§18.3、TEST-028 | 真实独立成员的直接回应与方案来源、按方案认领及执行、适用质量门和验收、真实调用与费用证据 |

主规范 §10.6 要求 `VERIFIED → READY_FOR_INTEGRATION → INTEGRATING → INTEGRATED → SYSTEM_VERIFIED → COMPLETED`。`git.merge` 必须在更新受保护引用时再核验源 commit、预期目标 commit、审批范围和执行代次；目标前进需要重新评估。合并冲突必须记录并交回有职责的成员，不能由设施静默 rebase。新的系统 Verification 固定 `result_commit`，不能继承合并前的 PASSED。

主规范 §5.2 明确 Mission 进入 `ACCEPTANCE` 后逐条验证 `success_criteria`，并经 CRITICAL 人类批准才能交付。Task 全部 COMPLETED、JSON 检查通过或本批代码复核接受均不能代替此条件。

## 后续设计需回答的事项

1. 如何保存权威的集成需求与目标，以及它与现有具体 Task 豁免声明的互斥关系。不能靠文档扩展名、Agent 转述或没有填写目标来默认免集成。
2. 如何为真实 Git 操作建立资源边界、分支保护、Session/Binding/epoch 与当前授权的提交时校验。产品支持 Git 与在本工作区初始化 Git 是两件事；现有禁止初始化、安装、联网和发布的约束继续有效。
3. 如何区分一次合并的授权、外部效果、结果提交、冲突和 UNKNOWN；进程崩溃后通过查询/对账恢复，不能盲目重试已经可能更新的引用。
4. 如何固定系统测试来源、Runner/环境、合并结果及准则版本；变更这些输入时，旧验证不能自动放行。当前固定 JSON Runner 不可冒充代码构建或系统集成测试。
5. 如何把新的 Integration 阶段接入现有质量轮次而不跳过独立 Review、适用性检查或终态退役；旧豁免记录和 Task 历史仍按原契约纯重放。
6. 如何形成不可变 Mission 交付集合和逐条准则映射，以及在审批与实际交付之间发生目标、准则、Policy、成员或版本变化时显式失效。
7. 正式 Team/Blueprint 激活、Bootstrap 与可执行规划图目前仍未接受；真实双 Agent 自主交付必须先明确这些前置关系，不能把当前 candidate-only 规划当成已生效执行图。

## 最小证据要求

- 正向：真实受保护目标更新、结果 commit 系统 Verification、完整 Task 集成链；独立的 Mission 逐条通过与相同交付快照人类批准。
- 负向：未经过 Gate 的集成任务不能完成；目标分支前进、冲突、旧 epoch/过期审批、来源或测试输入变化均不能沿用旧授权；缺少一条 Mission 证据、FAILED 或 INCONCLUSIVE 均不能 Delivery。
- 恢复：效果发生前后进程退出、提交失败、响应丢失、并发旧 revision、暂停时在途事实，以及仅事实库和完整库的逐前缀纯 Replay；记录真实执行守卫与库字节保持。
- TEST-028：用户只给粗糙想法，真实成员互相回应并形成可追溯方案；人工只在策略关键点介入，不能由主代理代写所有成员讨论，也不能把本地确定性身份夹具计作自治模型。

下一步先消费本批真实独立复核并完成不可变收尾，再归档已接受输入，按上述依赖形成单独 Integration/Mission 设计与实施计划。本文不启动这些产品功能，不改变 `phase=preparation`、`product_completion_percent=0`、`bootstrap_status=not_started`、完整 M1 `not_accepted` 或完整 Conformance `28 registered / 0 passed`。
