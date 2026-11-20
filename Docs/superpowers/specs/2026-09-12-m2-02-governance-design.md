# M2-02 Approval、治理与暂停恢复设计

工作项：M2-02。执行者 `/root`；独立复核 `/root/m1_reviewer`。用户已要求继续开发、不使用 ClaudeLink；主线程实现，只复用原 reviewer。此项是已有方案中治理子系统的接入，按已授权的开发范围推进，不新增外部执行权限。

## 规范与范围

依据主规范 §§5.1、9.1–9.7、13.4、13.9–13.10、14.1–14.4、14.11、18.3；不修改主规范。涉及 INV-006、010、012、015、020、021，映射 TEST-004/007/011/023/025/027 的本地子场景。

本项实现：版本化 Policy、Approval 的请求/独立批准/拒绝/委托/撤销/过期/有限续期、Decision 的治理状态、固定文档 Runtime 在调用点的审批检查、Project 暂停与人类 Intervention。继续使用 `Command → Event Store → Projection`。

可批准的目标适配器仅 `decision` 与现有固定文档执行的 `task`。八种协议 target type 均作枚举校验；blueprint/deployment/budget/credential/team/mission 缺少相应可信目标/执行设施，拒绝 `ENFORCEMENT_UNAVAILABLE`。Mission 准则与交付快照仍属 M3-02，不能将此处的拒绝称为通过完整 TEST-023。

## 方案选择

采用独立 `governance` 模块，以纯记录转换和已有服务接入点为边界。通用任意动作 Policy 引擎会超出当前 Provider 能力；独立可变审批表则破坏事实链。Policy 和身份角色配置是 Project 的 Event 投影，Approval/Intervention 是规范已有实体，不新增顶层实体。

每条 Command 仍只有一个对应领域终态 Event。需要多个事实的请求由受信服务在外层 SQLite 事务内串联确定性 child Commands：如 `approval.expired → approval.escalated`、有限续期、人类 `project.paused → intervention.recorded`。child 的 `status != accepted` 必须使全批回滚；已认证外层请求另留拒绝审计。重试用原父 Command，成功后重试不再次触发 child。子命令和记录保留父 Command ID，纯 Replay 不执行串联逻辑。

实现中的因果约束：父 Event 记录由原始状态纯计算的 `continuations`；Replay 重算并核验实际 child 的确定性身份、类型、目标、参数、actor、父链接、时点与顺序，host tick 根也有固定身份和触发约束。子 ID 使用规范化数组编码，避免冒号拼接歧义。前缀停在父事件与必需子步骤之间时，状态可查看，但父 Command 仍为 recovery pending；不能夹入无关命令或拒绝子步骤。治理 Project 的现有聚合缓存不含因果游标，故回退完整事实重放，不迁移 SQLite schema。治理专有事件或已治理 Project 的暂停/恢复缺少正确 schema 时拒绝，不能降级到旧 reducer。

凡与文档执行并行的治理变更，先取得同数据库 ResourceGate，再开启数据库事务；不在事务内查询 Provider、启动 Session 或调用 `ExecutionService._call/recover`。运行恢复在事务外受控查询，然后在提交恢复事实前重新检查持久状态和 live Session。

## 身份、Policy 与来源

`GovernanceService` 的首次配置要求宿主显式提供 `owner_id`，且认证通道主体就是该 owner。没有默认 human/bootstrap 代批身份。配置后的角色从 Project 事实读取；Agent ID 不能被配置成人类身份。角色仅表达审批职责，不影响直接交流或提案权。

身份互斥双向生效：Agent 注册入口与 Replay 都保留当前及历史 Policy 中的人类 ID，系统 ID 同样不能注册为 Agent。`principal` 对矛盾的同名 Agent/人类状态防御性拒绝。Manual 模式对本项支持的动作均要求人类批准，不因某条规则列有 Agent delegate 而降级。

Policy 保存完整内容、版本与摘要，版本不可同名换内容；更换当前版本保留历史，并为旧授权记录 `approval.invalidated`。仅 owner 可配置 Policy。CRITICAL 动作在配置期就禁止 auto/delegated/decision_based，且仅 human_owner；HIGH 不能由 Agent 代批。固定动作的最低风险由实现规定，客户端 risk 只能提高。

默认来源 unknown，按 untrusted 处理。Approval 保留来源；引用的 Decision/Message/Artifact 若已标为不可信，任何新回执或同行复核都不能清除。普通讨论不要求审批。一个可选的宿主 `InputAuthority` 为完整 Command 摘要签发仅在入口验证的能力回执，使已由可信输入设施证明的新上下文可标 internal/trusted；不能在 payload 中自报清白。回执绑定 actor、Command 与源 namespace；历史 Event 只恢复当时的来源事实，不重建该入口能力。

文档 append/restore 从持久 source Action 合并来源；restore 还保留 Checkpoint context 的来源、引用 ID 和摘要。旧 Action 缺少来源字段时按 unknown 处理；新的可信回执不能将这些派生内容洗为可信。

不可信 LOW 升到至少 MEDIUM；不可信 MEDIUM 升到 HIGH；HIGH/CRITICAL 仍要求人类。auto 是确定性系统规则的批准事实，不能由提案者伪装审批人。MEDIUM 可由配置中合格、独立且参与项目的同行审批；请求人与实际批准人分离，并拒绝原提案作者自批。

## Approval 快照与执行前检查

`target` 固定 type/id/revision/content_digest/revision_kind，由可信实现计算并与请求比较。Decision 的 `revision_kind=proposal`：版本始终指不可变提案内容版本，正文摘要保持 M2-01 的原值；状态变化的 `Command.expected_revision` 仍是聚合 CAS。Task 的 `revision_kind=aggregate`：版本和摘要绑定当前完整执行快照。两种适配器不能混用。

`scope` 固定 action/arguments_digest，保留规范化参数。`requested_by` 与 executor 固定认证主体；别的 Agent 不能借用批准。固定文档参数同时绑定 operation、规范化文档内容、Binding、epoch、Session、目标 Task；最终调用点重查 Policy、Approval 状态/有效期、目标摘要、主体、参数、当前执行权与暂停屏障。

目标或参数变化必须新审批；Policy 变化保守使旧授权失效，不自动迁移。Approval 历史 Event 不改写，状态与 validity 由新 Event 推导。事实重放或收到历史 accepted 结果不提供再次执行许可。

Decision 经过 `proposed → reviewing → pending_approval → approved → active`。独立 review 留反馈，原提案正文/来源不变。批准与激活均检查 Approval；激活只确立本地决策事实，不等于部署或执行任意工具。修改内容仍由新 ID + supersedes 表达。后续撤销不回写 active 历史，记录 authorization invalidation 与影响范围。

## 过期、委托与撤销

Approval 的 TTL 与委托否决窗口使用基于持久 pause/resume 区间的治理时间，和 M2-01 相同时间原点；凭证保持墙钟期限。空闲过期由宿主 `tick(project_id)` 驱动；消费审批时也检查时间，即使宿主尚未 tick 也不能使用已过期授权。

`on_expire=escalate` 原子产生 expired/escalated 并记录更高通知等级和人类路线；关联高风险 Task 显式 BLOCKED。`reject` 记录拒绝路径，未激活 Decision 回 reviewing。`renew` 只在原快照/参数/Policy 仍适用时创建新 ID，保持请求人和条件，最多 Policy 指定次数；达到上限或原授权已失效转 escalation，不无限续期。旧请求保持 expired。

delegated Policy 固定实际代批人、角色、作用域与 revocable_within，产生 delegated Event；CRITICAL 不委托。owner 的窗口内 veto 产生 REVOKED；一般安全撤销也只允许人类 owner，并明确原因。撤销/过期保留已有 Action 结果，记录 Decision/Task/Action 的影响清单与需重新规划的提示；已发生的外部效果不可被声称撤回。

## Pause、恢复与 Intervention

人类 pause/resume 必须含 reason 和 impact，产生 Project Event 和可寻址 Intervention（指向实际 Command）。对未配置治理的旧 M1 流保留原固定 bootstrap 行为；一旦治理配置存在，旧入口不能绕过人类身份或恢复检查。

暂停阻断新 Task 派发、执行启动、工具意图/授权与实际调用；继续记录已生成消息、受信 Runtime 报告、工具结果、审计及安全治理操作。在途报告记为 observation/historical，不推进 Task 质量阶段。

Project 记录调度屏障；各当前 Binding 记录 `pause_status=unsupported`，因为固定文档 Runtime 不证明完整执行静止。不得报告 `confirmed` 或全部静止。resume 在提交前检查未知/在途 Action、未完成 Command、当前 Lease/epoch、成员、墙钟 Session、审批/Policy/预算；无法确认则保持 paused。恢复不会重建丢失 Session、重新写文件或重发已完成动作。

未配置文档 Runtime 的已治理 Project 也从同一 writer transaction 快照读取真实 Commands/Events，计算 receipt-only 或不完整治理批次的 pending 状态；只排除当前正在验证、已持久化但尚无 receipt 的 resume 自身。缺少 Runtime 不代表没有待核查命令，拒绝恢复不得产生 resumed 或新 Intervention。

Intervention 支持 Project pause/resume 和 Task stop（安全取消并撤销当前执行权、保留在途 Action 对账）。redirect/modify/override 若需要未实现目标或质量门则明确拒绝；不能作为绕开治理/Verification 的通道。

## 写集与验证

新增 `src/aetp/governance/{contracts,policy,trust,snapshots,approvals,decisions,controls,service,projection}.py` 与 README；扩展 domain/core 的静态词汇/路由，runtime 的审批接入、暂停报告与恢复检查，meetings 的已治理 Decision 来源读取兼容。无 Event Store schema 迁移、依赖安装或网络调用。

测试覆盖身份伪造/自批/委托越界、版本/摘要/参数/Policy 变化、CRITICAL 配置拒绝、unknown/untrusted 来源、有限 renew/过期拒绝/升级、撤销后实际调用拒绝、暂停后在途结果/报告、长暂停凭证失效、重启保持屏障、事务故障回滚/幂等/跨实例竞争、逐前缀 Replay 与旧 M2-01 示例字节只读兼容。

每批先真实 RED 后 GREEN。完整 M2/M1/M0 和准备套件在冻结前运行；候选和 journal 独立冻结，原 reviewer 复核后才可 done。此前基线保留在 `.tmp/m2-02-baseline/`（217 输入），索引 `Docs/development/evidence/2026-09-12-m2-02-baseline.json`。

边界保持：phase=preparation、product_completion_percent=0、bootstrap_status=not_started、完整 Conformance 28 registered/0 passed、完整 M1 not_accepted、正式 Verification INCONCLUSIVE。工作项接受不代表完整协议或完整 M2 验收。
