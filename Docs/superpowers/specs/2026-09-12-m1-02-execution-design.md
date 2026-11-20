# M1-02：固定文档 Runtime 的执行边界

日期：2026-09-12。执行者：主会话 Codex；独立复核：复用 `/root/m1_reviewer`。用户要求继续开发、不使用 ClaudeLink、最多一个子代理。仓库没有 Git；采用摘要与源文件归档，不初始化或提交。

## 验收边界

按 backlog 的四项标准验收本工作项：旧 epoch 不能推进 Task 或写资源；不同 Binding 使用独立工作副本并拒绝越界；外部 UNKNOWN 先查询/对账；需要 Approval 的操作拒绝。提供实际文档文件写入、Checkpoint 和另一个 Agent 换代续接的正向路径。

本项实现 Windows 上固定、数据驱动的文档 Broker。Agent 输入是受限 JSON/文本，不运行 Agent 提供的 Python、Shell、插件或任意代码。working_copy 不是 OS sandbox；其他平台和任意 Coding Runtime 返回 ENFORCEMENT_UNAVAILABLE。权限保护针对经过 Broker 的请求，可信宿主、数据库、注册身份的调用通道与宿主时钟属于信任基础；不声称防御同权限恶意宿主改写数据库。

正式 Verification 保持 INCONCLUSIVE / ENFORCEMENT_UNAVAILABLE。整个 M1 的低风险成果交付与 Integration 豁免验收尚未满足（设计 §17.2、补充 §3）；M1-01/02 工作项计数不能充当整阶段接受。后续应补齐受信 Verification Runner、质量迁移与显式集成豁免，并独立验收。完整 Conformance 保持 28 registered / 0 passed，Bootstrap not_started，产品百分比 0。

## 规范与方案

规范来源为设计 §§5.1、5.13、7.3–7.7、7.10、13.4、13.9–13.10、14.1、14.4。保留 Command → Event Store → Projection。复用 SQLite 原子事务和最终 revision 检查；纯 Replay 无 Runtime/文件调用。

1. **事实与资源。** Lease、Binding、Session 描述是 Task 子资源，owner/current Binding/Lease 在一个领域 Event 内原子变化。Action 与 Checkpoint 有独立投影地址，但必须依附同 Project 的 Task，不增加角色、授权等级或独立执行权。Action 结果不直接修改 Task 阶段。每个 Command 只有一个终结领域效果；跨地址的 tool.request/checkpoint.create 明确校验 Task 与子资源地址，不能凭 causation_id 误认完成。
2. **固定 Policy。** 可信 bootstrap 首先配置 Project 的固定版本与 Workspace 标识。ExecutionService 创建的 Task 显式带执行 Policy；旧 M0/M1 candidate Task 不自动获得执行能力。工具白名单为定长文档写入、从已确认来源恢复与追加。未知工具拒绝；Shell、网络、发布、敏感数据或请求 Approval 均不因客户端 risk_level=low 而放行。
3. **认领与会话。** task.claim 在最终事务中分配单调 epoch、Binding 与 Lease；续租不变 epoch，换代递增。start_session 是可信 Runtime 入口，提交当前 Binding 的开始事实后激活内存 Session；调用通道由不可复制的已注册对象绑定，JSON 中相同字符串不是授权。崩溃后缺失 Session 不自动重建。Lease 使用治理时间；Project pause 冻结治理时间，Session 凭证仍受墙钟到期约束。
4. **资源 fencing。** 同数据库的执行服务使用 Windows 命名 mutex 串行化派发与权限变更；它不能替代数据库 revision/epoch 条件。取得资源门后提交 IN_FLIGHT，结束数据库事务，再在实际文件打开处重新验证 actor/Session/Binding/epoch/Policy/暂停屏障。锁不可用时拒绝；不回退为无锁执行。宿主不得将外部派发包在已有数据库事务中。
5. **文件边界。** Provider 根据 Project/Binding/Action 的摘要选择固定路径，客户端不能指定路径。根目录与所有路径祖先以禁止 DELETE sharing 的 Windows directory handles 锁定，逐级拒绝 reparse/junction。最终对象使用 OPEN_REPARSE_POINT、独占新建或只读打开，拒绝目录、链接、硬链接和 ADS。内容有大小上限与固定 UTF-8 JSON envelope，含稳定 Action 身份、目标、参数摘要和内容摘要；查询逐字段比对并检查完整内容。没有任何通用文件浏览/任意路径读写接口。
6. **Action。** tool.request 先持久化 PENDING；dispatch 提交 IN_FLIGHT 后只调用一次 Provider。成功才记录 COMPLETED；断电、异常或响应丢失进入 UNKNOWN。IN_FLIGHT/UNKNOWN 阻止同 Task 新工具意图与重新排队。恢复只查询原 Action，完整确认才写对账事实。缺文件、部分文件、摘要不符继续 UNKNOWN，不造新 key 重试。尚未派发的 PENDING 可在撤权后取消；UNKNOWN 不可被当作可安全取消。
7. **Checkpoint 与交接。** Checkpoint 固定 Task/Agent 快照、已确认文档 Action 和候选 Artifact 引用、带来源的 Context Snapshot、remaining work；Git/Decision 明确 not_applicable。撤权立即阻止旧执行，旧报告仅留在原 Command/拒绝审计。先对账旧 Action，再 requeue；另一 Agent claim 创建新 epoch 和独立副本，引用旧 Checkpoint，经过同样的 Action 边界恢复/追加文档。恢复源也必须通过固定 Provider 查询。
8. **恢复与暂停。** 新 Broker 默认派发屏障关闭。recover 先纯重建，再查询 Session 和 IN_FLIGHT/UNKNOWN，清理确定未派发的旧 PENDING。不能确认时保留关闭；不会调用 Runtime.start、重发工具或把失联等同 Task FAILED。Project PAUSED 时允许撤权、查询和结果归档，不派发新工具；resume 仍须重新检查凭证与未知结果。

## 写集与失败证据

新建 src/aetp/runtime/、src/aetp/workspace/、tests/m1/test_execution_boundary.py 及测试帮助文件。共享接入限定 domain/models.py、core/commands.py、core/projection.py、collaboration/service.py，必要的 SQLiteStore 只读宿主属性。更新开发计划、证据、backlog/status/MEMORY；不改变协议原文或旧验收报告。

失败夹具使用实际 SQLite 与实际 Windows 文件系统，包括跨进程竞争、数据库插入故障原子回滚、旧 epoch 与伪造会话、junction/硬链接/路径替换、效果前崩溃与效果后响应丢失、暂停时凭证过期、纯 Replay 无 IO、Checkpoint 换 Agent 恢复。唯一的故障替身位于宿主/Provider 的故障注入点，不替换协议实现。

基线见 `Docs/development/evidence/2026-09-12-m1-02-baseline.json`，其中已核对 accepted v2 的 43 个输入，归档在 `.tmp/m1-02-baseline/`。原 M1-01 验证脚本的工作区摘要要求不适用于开发后的共享路径；历史重现应使用此归档，不能篡改原证据。

## v2：独立复核 R1 的文件写入修正

v1 的一次性 links 检查与 sharing flags 未阻止打开后增加硬链接，独立复核 `M1-02-REVIEW-R1` 因此拒绝该候选。原报告、失败日志与 82 个冻结源保留，389 个相关文件另存于 `.tmp/m1-02-candidate-v1/`；不回写 v1 为成功。

这是固定文档 Provider 内的局部修正，不改变 Command/Action、Policy、Session、角色或授权模型。真实 Win32 诊断表明 share=0 仍允许新增链接；新文件的 delete-pending 状态则让该调用被文件系统拒绝。Provider 在创建后先设置此状态，再检查剩余链接为零（待删除的原名字不计入 links）；若创建与设置之间已经出现别名，则在写入任何内容前拒绝。全部字节写完并刷盘后才清除该标记并保留文件，此后不再写内容。

未发布文件的失败或进程退出会由句柄关闭移除文件；持久化 Action 仍为 UNKNOWN，缺文件不能证明可安全重试。查询已发布对象继续验证单链接、完整身份和全部内容。此措施约束 Provider 写入期间的资源访问，不限制可信宿主在操作完成后的任意文件系统动作，不将工作副本升级为 OS sandbox。

验收补充覆盖：打开后插入链接、创建与标记之间出现链接、标记能力不可用、刷盘失败，以及真实子进程在刷盘后/保留前退出。新崩溃用例在归档 v1 代码上真实失败、修正后通过；不覆盖物理磁盘故障或整机断电的全部持久性保证。
