# M1-01：直接协作与候选证据

使用现有 Python 标准库和 SQLite，无安装步骤。工作项设计见 `Docs/superpowers/specs/2026-09-11-m1-01-collaboration-design.md`。

```python
from aetp.collaboration.messages import Message, MessageBus
from aetp.collaboration.service import CollaborationService
from aetp.domain.models import Command
from aetp.storage.sqlite_store import SQLiteStore

# 使用新的开发数据库；项目和成员先经 bootstrap Command 注册。
with SQLiteStore.open(".tmp/my-collaboration.sqlite") as store:
    service = CollaborationService(store)
    # service.messages.send(message, authenticated_actor_id="agent-a")
    # service.handle(command, authenticated_actor_id="agent-a")
```

`authenticated_actor_id` 是受信入口传入的身份，不能由外部请求的 actor 字段自行决定。此库接口不是完整的 Runtime / Workspace 身份隔离。`Message.untrusted_input` 默认 true；只有受信入口知道输入来源时才能标为内部，引用不可信消息不能清除标记。内联 Artifact 的正文来源没有 Runtime 证明，始终保留不可信输入标记。

MessageBus 提供 `send`、`inbox`、`snapshots`。消息类型包括 question / proposal / challenge / response 等；回复须带 references 和 target_message。所有成员使用相同成员规则，无 Manager、Role 等级或 Task Lease 前置。普通 Message 不产生 Command / Event，也不会执行正文中的指令。MessageBus 是进程内过程记录，重启后为空；Artifact 引用的发言以内容、身份、来源与摘要快照固化进事件历史。

`Message.from_dict` 接受版本化 JSON 解码后的 recipients / references 数组并冻结为 tuple，保留 schema_version、字段、身份和回复引用校验；直接构造 Message 仍要求不可变 tuple。

所有正式事实仍经 `CommandHandler.handle` 的 SQLite 事务、身份校验、版本及幂等边界写入。`CollaborationService` 在委托既有 Task claim/release 前校验当前成员、Project、固定 Policy 和字段，并要求目标 Task 已显式采用 M1 Policy；旧 M0 Task 不自动获得 M1 操作许可。bootstrap 仍是既有受信模拟入口。

| Command | target_id / payload | 结果 |
| --- | --- | --- |
| `task.create` | 新 Task ID；title、acceptance_criteria（非空唯一文本数组） | 固定低风险 Policy 与验收标准摘要 |
| `task.claim / task.release` | 已有 M1 Task ID；仅通用 Policy 字段 | 通过成员、Project、Policy 和 revision 校验后，沿用既有认领/释放事务 |
| `artifact.submit` | 新 Artifact ID；task_id、type=document、content；可选 message_ids、derived_from、supersedes、data_classification | 服务计算内容摘要，保存候选快照，不改变 Task |
| `review.request` | 新 Review ID；artifact_id、artifact_digest、reviewer_id | 创建独立 Review；作者不得自审 |
| `review.submit` | Review ID；status=approved/changes_requested/rejected、feedback、artifact_digest | 指定 reviewer 提交一次正式结果，无须取得作者 Task |
| `verification.run` | 新 Verification ID；artifact_id、artifact_digest | 实际纯文本预检查，原子保存报告 Artifact 和 INCONCLUSIVE Verification |
| `verification.submit` | 任意自报结果 | ENFORCEMENT_UNAVAILABLE |
| `task.verify / task.complete` | Task ID；artifact_id、review_id、verification_id | 缺少适用质量证据或执行授权时拒绝 |

新对象的 expected_revision 为 0 或 None；已有 Review 提交和 Task 请求必须携带当前 revision。Review 固定 Artifact 摘要、Task revision、验收标准摘要及 Policy；目标变更后旧证据保留但不再自动适用。

Policy 为 `m1-document-candidate-v1`，仅允许至多 65536 UTF-8 字节的 public/internal 文档候选。高风险或需要 Approval 的请求拒绝；未知 Policy、字段、执行方法、路径/Git 来源、敏感分级不被隐式放行。客户端传 `approval_required=false` 不会扩展能力。

预检查只检验每条验收文本是否出现在文档中，保存实际逐条结果、代码摘要、环境摘要、固定检查方法、目标与标准快照。报告的 observed_result 可以为 PASSED 或 FAILED；正式 Verification 始终为 INCONCLUSIVE，reason=ENFORCEMENT_UNAVAILABLE。真实 Runner 授权、Action、Binding、Lease、Workspace、UNKNOWN 恢复以及成功质量门属于 M1-02。Task 不因候选登记、审查或预检查推进；本项不声明 Task COMPLETED、完整协议兼容或 Bootstrap。

复现：在仓库根目录临时将 PYTHONPATH 指向 src 后运行：

```powershell
python -m unittest discover -s tests/m1 -t . -v
python -m unittest discover -s tests/m0 -t . -v
```

复核修订后的例子在 `artifacts/m1-01-demo-v2.json`、`artifacts/m1-01-candidate-v2.md` 和 `artifacts/m1-01-precheck-report-v2.json`，命令记录在 `Docs/development/evidence/2026-09-11-m1-01-development.json`；不带 v2 的初版保留。例子是两个受信 actor 的确定性夹具，不是真实模型自治，也不代表 TEST-028 已通过。
