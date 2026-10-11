# M0 Conformance 子集

这是 [M0-06 / Task 6](../../Docs/superpowers/plans/2026-09-06-m0-first-slice.md) 的**开发期可执行验收夹具**，不是完整 Runtime，也不自行授予工作项接受状态。规范来自 [主设计](../../Docs/AETP-设计方案.md) §§13.4、13.10、14.1–14.2、17.2、17.4、18.3。源码与原文摘要随 CLI 输出记录。

## 运行

仅需已有 Python 3.11+ / SQLite / unittest，标准库；在仓库根运行，不安装依赖，不修改全局环境。保留 `tests/`：runner 明确复用其中的真实子进程和故障夹具，不把它们装入产品包。

```powershell
$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = (Join-Path $PWD 'src')
    python -m unittest tests.m0.test_conformance_subset -v
    python -m conformance.m0.runner --db .tmp/m0-conformance-rerun.sqlite --json artifacts/m0-conformance-rerun.json
} finally {
    $env:PYTHONPATH = $previousPythonPath
}
```

每次须使用**新的** DB、JSON 和对应 `.evidence` 目录名，DB 的 SQLite 辅助路径 `<db>-journal`、`<db>-wal`、`<db>-shm` 也必须不存在（文件、目录或链接均拒绝）。所有显式输出与上述辅助路径必须各不相同且互不嵌套；API 与 CLI 在任何输出写入前检查，发现冲突只拒绝，不删除或清理。该预检用于避免误用既存文件，不提供恶意宿主并发改路径（TOCTOU）防护或安全隔离。以上 `rerun` 路径若已存在也会拒绝；更换后缀，不清理或覆盖历史报告。`--db` 是真实写入的受控夹具数据库，**不得传业务数据库**。只终止／回收自己创建的故障注入子进程。不会运行真实模型、Shell 命令、网络请求或发布。

API：`run_m0_conformance(db_path, *, evidence_dir=None) -> dict`，返回所有 28 个 TEST。默认原始记录写入 `<db_path>.evidence/`；CLI 写入 `<json stem>.evidence/`。

退出码：`0` = 本轮已实现范围的夹具成功且源码摘要前后一致；`1` = 夹具失败（包括 skip、xfail、空／未完成夹具）或源码执行中变化；`2` = 参数、路径或证据 IO 失败。**exit 0 不代表完整 28 项通过、独立接受或 Bootstrap。**

数据库、报告与证据目录必须是互不重叠的新路径，不能互相嵌套。报告后缀为 `.evidence` 会与自动生成的证据目录重名，故在创建任何输出前拒绝。

## 两个状态维度

- 每项 `status`：`passed` 仅指声明的 M0 内核能力范围；`pending` 指只覆盖了原 TEST 的部分要求；`not_applicable` 明示后续里程碑尚未执行；`failed` 优先于部分覆盖的 pending。
- 每项 `execution.status`：`passed / failed / not_run`，来自当次实际执行，而非测试名、既存 JSON 或映射清单。
- 未执行项的 JSON 是 `scope registration only`，不伪造 stdout、时间或成功次数。
- CLI 报告的 `review.status=pending`、`claims.work_item_accepted=false` 固定表示 runner **不能自评接受**。不同 Agent 的后续审查及 [M0 交接](../../artifacts/m0-handoff.json) 才能接受该次报告的固定摘要；不得回写原始报告冒充运行时已审查。
- `Docs/development/status.json` / `devprep` 的 preparation、全协议 registered/0 passed 是原有准备口径；本轮有限验收在 `status.m0_subset` 单列，以该交接为依据。两种计数不可互换，不迁移整体产品百分比或 Bootstrap 状态。

## 12 条计划映射的实际边界

以下是夹具的目标分类，不是无需运行即可使用的通过声明；实际结果以本次输出为准。

| TEST | 当次实际夹具／故障注入 | 成功后的范围状态 | 仍不声明 |
| --- | --- | --- | --- |
| 001 | 真实 accepted/rejected Command 重投；比较原结果及完整 Event 流，单领域效果 | M0 `passed` | 外部恰好一次 |
| 002 | 修改只读返回副本、尝试改不可变 Command、提交不支持的直接 completion；核对事实与字面期望 State | M0 `passed` | 对特权 Python/SQLite 的隔离、真实 Workspace 边界 |
| 005 | 真实 create/claim/release 后删除全部 Projection cache 表；只读 Replay 等于字面 State 且不重建 cache 表 | M0 `passed` | 其他未实现对象恢复 |
| 011 | 不执行；Approval 过期／升级属于 M2-02 | `not_applicable` | Approval 行为 |
| 012 | 人工 receipt-only 存储故障；多个新只读恢复连接只返回待核对 IDs，重放不派发 | `pending` | 完整调度、Lease/epoch、Approval、Session/Binding、预算及 UNKNOWN |
| 014 | 不执行；Workspace/Provider 属于 M1 | `not_applicable` | 安全隔离 |
| 015 | 不执行；双 Agent Message/Review 属于 M1 | `not_applicable` | 产品直接讨论、独立审查质量门 |
| 016 | 受信连接 a-2 冒称 a-1 被拒，安全审计不污染协议事实／保留 key，合法 caller 随后可提交 | `pending` | Binding 冒用、真实执行授权 |
| 017 | 独立子进程 commit 后、客户端响应前被真实终止；新连接以原 Command/key 重试，原结果与单次领域批次保留 | M0 `passed` | 外部恰好一次、损坏结果索引修复 |
| 018 | 真实 claim、异内容同 key 拒绝、owner release、新 key/current revision reclaim；旧 claim/release 重投不得改变新 State | M0 `passed` | Lease/Binding |
| 019 | 两个独立进程／连接同读旧版本，再竞争最终 SQLite 提交；恰好一个成功，重试保留原结果 | `pending` | Lease/Binding 一致性与 fencing |
| 021 | 真实 Replay；逐一注入 forbidden-call 变异检验 tripwire，正常重放所有调用数为零 | M0 `passed` | 真实 model / Runtime.start adapter 与已确认 Action 历史 |

另外 16 项分别保留：003/008 Review/Verification、004/007/023/027 治理/审批/来源、006/022 Lease/epoch、009/010/024 集成与验收、013 路由协作、020 UNKNOWN、025 操作级暂停、026 真实边界、028 从想法到成果。均为 M0 `not_applicable`，原要求未删除；不是永久豁免。加上表中的 011/014/015，共 19 项不适用。

## 证据形状与限制

九个已执行夹具各自拥有独立 Project，实际使用同一新建 SQLite 文件。初始化通过 Command Handler；每个观测 JSON 固定初始 Event/State、输入 Command、受信测试来源、Runtime 能力、故障点、字面期望／实际断言、Replay State 和完整结束事实。每项另存原始 unittest 输出及 SHA-256。数据库 cache 的删除、receipt-only 是**特权存储故障夹具**，不是 Agent 权限或正常半提交窗口。

TEST-021 监控真实 simulator 与 `subprocess.Popen` / `os.system` / `socket.socket` / `urlopen` 出口；通过在 `RuntimeRecovery → Projection.rebuild` 中注入调用验证 trap 可检出。负控使用无效参数，即便 trap 失效也不会启动实际命令或请求。`model.invoke_sentinel`、`runtime.start_sentinel` 是缺失适配器的明确标记，不能当作真实适配器认证。

模拟器的 `simulation-only` 结果不充当协议 ACK。没有 Runtime.start adapter、Action/outbox、Lease/Binding、Approval、Review/Verification、集成或 Mission Acceptance；不会产生合规 Task COMPLETED 或 `BOOTSTRAP_VERIFIED`。报告是检查固定版本代码的证据，不是独立的授权系统，也不能证明任意后续代码版本兼容。
