# M2-01 本地结构化讨论

`MeetingService` 继承现有 Command 边界，增加 Discussion、Meeting 和不可变 Decision 提案。所有准入同级 Agent 都能发起过程或直接提案，不需要 Task、Lease 或 Manager。主持人只负责提前结束议程。批准和激活始终返回 `ENFORCEMENT_UNAVAILABLE`。

## 接口与数据边界

宿主创建 `MeetingService(store, meter=MeteringAuthority(source_id), clock=...)`。`handle(command, authenticated_actor_id=...)` 处理控制和提案；`post(Contribution(...), authenticated_actor_id=..., receipt=...)` 接收普通材料。身份和 meter 对象来自受信宿主，不能由 Agent 提交任意 Python 引用。未安装 meter 时不能打开新的受理过程，也没有默认生产计量器。

`transcript(project, kind, id, authenticated_actor_id=...)` 读取当前可见材料。Meeting 的 `individual_analysis` 阶段每人只能交一份分析，正常 advance 必须全员提交；在合法揭示前，读取和引用只能看到自己。`usage(...)` 仅返回数量、额度用量和清理状态。未获参与权限者不能读取这些接口。过程记录不可编辑；同 ID 同语义重试不消费第二次。

普通材料只进入 `collaboration_entries`，不逐条产生 Event。生命周期和结算检查点使用 Command → Event Store → Projection。最后一份材料恰好耗尽额度时，它与消费回执、自动 tick 和收敛 Event 在同一 SQLite 事务内提交或回滚。过程创建标记、数量、摘要、回执与事实检查点必须一致；丢失未结算过程数据会拒绝继续消费。

## 固定限制

Policy 为 `m2-local-discussion-v1`。Discussion 使用 token、时间和显式共识阈值；Meeting 另有最大轮数和无新证据轮数。Discussion 拒绝这两项无适用边界的配置。每个参与者只贡献一个最新非空 position，固定参与者总数作为共识分母，缺席和未表态不增加支持。共识只让过程收敛，不产生批准。

`token_budget` 是本地 Contribution **受理额度**。受信 meter 为完整材料摘要、来源 namespace、稳定 call ID 签发 `purpose=process_admission, unit=token` 回执，数据库跨实例/重启/清理去重。它不启动模型、不接收真实 provider usage、不证明真实调用费用上限；本地事务回滚也不是实际费用退款。提案者填写的标题、选择、理由属于 Command 输入，在此过程计量之外。

时间来自宿主墙钟，减去 Project pause/resume 事实派生的累计暂停区间，后配 M1 执行时钟不会重置它。暂停仍接收当前阶段的已生成材料并保留首轮隔离，但阻断新开过程和正常阶段推进。额度到限和主持人终止仍可收敛。宿主须定期提交 `discussion.tick` / `meeting.tick` 才能让空闲的到期过程产生终止 Event；没有后台线程。synthesis 只整理已有材料。

## 提案、清理与恢复

`decision.propose` 输入自己的 title、choice、alternatives、reasoning、risk_level，可引用 synthesis 来源的 kind/id/revision。服务固定完整原始材料、回执、摘要和输入信任标记，自行计算支持、缺席、历史异议与分类原文。后续改立场也不删除旧异议；服务不理解或裁定任意自然语言正文。直接提案的 `consensus_level` 为 null。`supersedes` 新建提案并引用旧提案摘要，不覆盖或使旧提案自动失效。

关闭过程必须绑定自身提案。`compact(...)` 只清理已关闭且来源固定的过程正文，保留消费依据。Decision 仍包含完整异议。清理后的同 ID/同语义重试先通过身份、参与权限和持久账目检查，再从关联提案的固定来源返回原确认；不同语义返回 `MESSAGE_ID_CONFLICT`，新消息仍不能进入关闭过程。返回确认不恢复正文、不读取新时间、不再消费回执，重启后也适用。

Projection 从各阶段 Event 派生 `checkpoint_history`，不把该索引重新写入 Event。读取过程材料及固定最终来源时，按每个历史检查点的消息数核验对应前缀，防止新增材料后旧阶段摘要被遗忘。纯 Replay 只需要 Command/Event，不访问 process/meter/clock/Runtime；它恢复控制事实，不重新创建丢失的未结算过程账目。旧 M2 缓存缺少历史索引时，由既有 Event 纯重建后继续事务。

验证入口：`PYTHONPATH=src` 下运行 `python -m unittest discover -s tests/m2 -t . -v`；完整示例脚本位于 `Docs/development/evidence/2026-09-12-m2-01-demo.py`。该切片不改变完整 M1、Conformance 或 Bootstrap 的未验收状态。
