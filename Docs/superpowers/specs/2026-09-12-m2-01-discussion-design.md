# M2-01 结构化讨论、会议和 Decision 提案设计

日期：2026-09-12。工作项：M2-01。执行者：主线程 Codex；独立复核：复用 `/root/m1_reviewer`。用户要求继续任务，不使用 ClaudeLink，最多一个子代理。本设计落实已确认规范和 backlog 三项标准，不改变产品角色与授权设定。

## 范围和取舍

这是新增协作子系统，按 architectural 路径形成设计和实现计划。主规范 §§8.5、8.8–8.16、9.1–9.2、13.4、14.1–14.2、14.10–14.11、16 是依据。INV-002/008/018/020 要求过程、意见、提案与授权分开；TEST-013/015/028 是相关完整要求，此工作项不将其标为完整 passed。

采用同一 SQLite 数据库中独立的 process 表保存发言和受理计量，现有 Command/Event/Projection 保存对象生命周期、阶段账目检查点和 Decision 提案。这样阶段变更与最后一份受理材料可在一个 writer transaction 内提交，而普通发言不会使 Event 数随文字量线性增长。另设数据库会增加跨库恢复窗口；把每条发言作为 Event 则违反过程/事实边界。

实现入口是受信本地 Python API；Agent 只提交数据。沿用当前受信宿主、数据库和身份通道前提，无网络、真实模型、任意代码、通知、费用支付或通用 OS 隔离。M2-02 的 Approval/Governance 不在本项内；Decision 只产生 proposed 状态，approve/activate 拒绝。完整 M1 仍 not_accepted。

## 对象和权限

Discussion/Meeting 是既有顶层对象，Contribution、计量回执、过程账目和共识摘要为子资源，不扩展实体清单。所有已准入 Agent 均可发起 Discussion/Meeting 和 Decision proposal，不要求 Task、Lease、Manager 或模型职级。固定参与者列表必须属于同一项目，主持人必须在列表内；主持人只可提前结束议程。

Discussion：open → synthesizing → closed。Meeting：created → open → individual_analysis → debate → synthesis → decision_proposed → closed。预算终止允许从 open/individual_analysis/debate 提前进入 synthesis；未提交者明确保留为 missing，不假定支持。created 尚未开始计时；meeting.open 开始整个会议的计时。

`discussion.open / discussion.synthesize / discussion.tick / discussion.close`；`meeting.create / meeting.open / meeting.advance / meeting.synthesize / meeting.tick / meeting.close`；`decision.propose / decision.approve / decision.activate` 使用固定词汇。advance 只能推进下一合法阶段；individual_analysis 正常进入 debate 必须全员各提交一份独立分析；debate 中 advance 表示结束当前轮并检查最大轮数和无新证据轮数；synthesis 中 advance 必须绑定已提交的本会议 Decision 提案。关闭 Discussion 同样绑定自己的提案。关闭不激活 Decision。

任何 Command 复用现有认证、幂等、事务与拒绝审计。跨项目对象、旧 revision、身份不符、非法阶段、客户端伪造支持列表/账目/时间/用量来源均拒绝。

## 过程材料与首轮独立性

Contribution 包含项目、对象类型/ID、消息 ID、作者、类型、正文、自己的 position、同一过程中的引用及 Artifact 证据引用。服务生成时间、阶段、轮次和输入来源标记；调用者不能自行填写其他参与者的立场。所有来源默认 untrusted，转述、提案和纯文本一致意见不清除标记。

普通 post 只写独立 process 表。个体分析阶段仅允许每人提交一份 analysis；读取、列表和上下文接口只能返回调用者自己的答案。引用别人首轮答案、提前创建来源提案也拒绝。所有人提交后仍需合法阶段迁移才揭示；预算提前终止时结束继续作答资格，再允许读取已有材料。

发言记录不可就地编辑，同 ID/同内容可重试，不同内容冲突。process 元数据维护数量、规范化摘要与受理账目；阶段内材料缺失或不一致时拒绝继续，不以空表重置预算。对象创建 Event 与 process 标记原子创建；不得仅凭 Replay 重新创建一个空过程并继续消费。

## 固定预算和计量边界

Policy 版本 `m2-local-discussion-v1`。每个过程固定 token_budget、time_budget_ms 和 consensus_threshold；Meeting 另有 max_rounds、no_new_evidence_rounds，两项均以 debate 的 advance 为轮次边界。Discussion 没有轮次，不接受这两项配置。整数边界拒绝 bool、非正数、超限值，比例必须有限且在 (0, 1]。创建后不增加预算，不按阶段、服务实例或重启重置。

**token_budget 是本服务对获受理材料的固定本地 token 额度，不是 provider 实际费用账本。** 上游受信宿主安装 MeteringAuthority，并签发与完整 Contribution 语义摘要、项目/过程/作者、来源命名空间和稳定计量调用 ID 绑定的不可变注册回执。回执固定 `purpose=process_admission` 和 `unit=token`；没有计量器、复制/伪造回执、换来源/单位、调用 ID 重铸均拒绝。数据库持久唯一约束保证两个实例、重启和清理后仍不重复消费。测试只使用明确标记的 fixture meter，不存在默认生产放行计量器，也不将字符数估算称为真实 token。

超出剩余额度的材料不受理，不消耗本服务的受理额度；恰好耗尽则原子提交材料、持久消费回执和合成阶段的 Command/Event。真实模型费用若已经发生，不能用这里的事务回滚解释为未发生；本 API 不接收 actual_provider_usage 回执。调用前预留、实际费用/迟到用量对账和完整 Resource Ledger 留待真实 Runtime/治理实现，因此不声明 provider 花费硬上限。

时间来自受信宿主墙钟减去持久 Project pause/resume 区间，处理阶段使用 writer transaction 内的新事实，拒绝时钟倒退；客户端 issued_at 不参与。Project Projection 从 pause/resume Event 派生累计暂停区间，不使用可在后来配置的 M1 执行计时原点。暂停期间继续受理已生成的普通材料，归入当前阶段并沿用其可见性和受理额度，治理时间冻结；禁止新建/启动过程和正常 advance。额度/时间耗尽或主持人结束仍可确定性收敛；整理来源提案和关闭不启动执行。所有新增发言入口先检查时间；宿主定期提交 tick 才会使空闲到期过程产生 synthesis Event，本切片不启动后台线程。

终止条件按时间耗尽、token 耗尽、Meeting 的 max_rounds/no_new_evidence_rounds、显式共识阈值或主持人议程结束检查，任一适用条件满足即收敛。新证据只按存在且摘要匹配的 Artifact 引用去重，换消息 ID/重复意见不算新增证据。共识阈值只触发阶段收敛，不选择或批准技术方案。synthesis 不接受新增过程用量，只允许读取已存在材料、确定性组装来源快照与提案者明确提供的字段。提案命令的标题/选择/理由不属于 Contribution 受理额度，不声称这些文本或真实调用已被 meter 计量。

## Decision 与永久异议

decision.propose 可直接提交方案，也可绑定当前 synthesizing/synthesis 对象和 revision。服务从过程存储读取完整记录，固定全部作者、立场、意见/证据区别、引用、输入来源和规范化摘要。supporting_agents、minority_opinions、missing_participants、concerns/unresolved、consensus level 由服务从来源生成，不信任提案者传入的列表。提案者只填写自己的选择、备选项、理由与风险。

支持统计采用固定参与者分母，每人最多计一个最新的非空自述 position；未表态或缺席者不计支持。supporting_agents 仅为当前 position 等于提案 choice 的参与者。所有历史不支持该 choice 的明确立场以及 disagreement/challenge 原文均保留，后来修改立场不能抹去旧异议。concerns/unresolved 仅按结构化类别收录带来源原文，不声称服务理解了任意正文含义；直接提案没有过程支持统计，consensus_level 为 null。

100% 支持也仅是 proposed。存在分歧或缺席时保留独立复核/人类治理的 escalation 建议，不发送消息或启动实验。未实现的批准/激活返回 ENFORCEMENT_UNAVAILABLE。supersedes 新建不可变 Decision 引用旧提案及摘要，不覆盖旧对象，也不假装新提案已经使旧决策失效。

只有对象关闭且 Decision 完整来源/账目已固定后才允许清理过程正文；回执消费依据、创建标记和结算摘要不删除。清理后 Decision 中的异议仍可查询，纯 Replay 仅使用 Command/Event 重建相同事实，不读取 process 表、时钟、meter 或运行工具。尚未结算的 process 数据缺失时，Replay 只恢复已固化控制状态，继续受理必须先恢复/对账过程材料。

## 写集、历史和验证

新建 `src/aetp/meetings/`、`src/aetp/decisions/`、`tests/m2/`。扩展 `src/aetp/domain/models.py`、`src/aetp/core/commands.py`、`src/aetp/core/projection.py` 的词汇、地址与纯归约接点；复用 SQLiteStore 现有嵌套事务，不改其源文件。材料写集为本 spec/plan、本项 evidence/artifacts、backlog/status/MEMORY。独立 reviewer 确认自身写集为空，没有共享写冲突。

修改共享源前保存 accepted M1-02 的 90 输入及依赖源基线；原报告、SHA、失败日志、归档保持不变。无 Git repository，工作在既有 workspace 内，不 init/commit/push 或安装依赖。

TDD 覆盖：全过程状态机、首轮所有读取边界、普通发言不生成 Event、身份/引用/旧版本、精确预算边界和超额、回执重铸/并发/重启、阶段中材料丢失、原子失败回滚、无证据轮数、治理时钟/暂停、异议不能删改、消息清理后固定来源、独立提案/替代链、拒绝批准激活、纯事实 Replay 与 Command 因果校验。之后执行 M1/M0 回归和三个准备检查，冻结新候选并由同一 reviewer 独立验收。只有三项标准均接受且证据完整才将 M2-01 置 done。
