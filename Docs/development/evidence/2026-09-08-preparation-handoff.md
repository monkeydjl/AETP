# AETP 开发准备集成交接（PREP-008 待独立验收）

日期：2026-09-08。执行者：主会话 Codex；交接对象：Kant 独立审查、用户与后续 M0 接手 Agent。

## 范围与依赖

本轮只收尾开发准备。PREP-001..007 已按真实独立证据接纳；PREP-008 依赖 PREP-002..007，目前为 review，尚未宣称 done。M0–M3 全部 12 项仍为 todo；产品实现未启动。

输入：AGENTS.md、Docs/development/README.md、backlog 验收/依赖、knowledge-map 导航到的规范、原始独立审查和 RED/GREEN 记录。执行计划：Docs/superpowers/plans/2026-09-08-preparation-closeout.md。

## 逐项证据与独立身份

| 工作项 | 本稿状态 | 独立复核 | 原始证据（Docs/development/evidence/） |
| --- | --- | --- | --- |
| PREP-001 | done | Boole，2026-09-07 | 2026-09-07-prep-001-006-review.json，PREP-001 结论 |
| PREP-002 | done | Mill，2026-09-06 | skill-protocol-navigation.md；preparation-log.md 的 Mill 增补 |
| PREP-003 | done | Kant，2026-09-08 | 2026-09-08-prep-corrections-review.json；skill-execution-contracts.md 当日增补 |
| PREP-004 | done | Kant，2026-09-08 | 2026-09-08-prep-corrections-review.json；skill-evidence-handoff.md 当日增补 |
| PREP-005 | done | Mill，2026-09-06 | preparation-log.md 的 Mill 增补；图谱静态报告只是辅助，不单独证明独立复核 |
| PREP-006 | done | Kant，2026-09-08 | 2026-09-08-prep-corrections-review.json；旧 Boole/Zeno changes_required 保留 |
| PREP-007 | done | Kant，2026-09-08 | 2026-09-08-prep-007-review.json：27 项准备测试、25 项有界独立审计场景 |
| PREP-008 | review | 待 Kant 总审查 | 本稿、2026-09-08-prep-acceptance-index.json 和 closeout JSON；主会话汇总不是独立结论 |

完整真实身份、文件摘要和验收条件索引见 2026-09-08-prep-acceptance-index.json。Kant 会话为 01a07cac-b6db-7393-ae38-bce13d69c67d，与源材料执行者主会话不同；其先前 Codex 别名不是第二名审查者。Zeno 已关闭，Rawls 无有效结论且已关闭；用户限制只保留 1 个子代理，后续总审查只复用 Kant。

## 已修订内容与写集

- 两个 Skill：区分纯 Projection Replay 与恢复查询/对账；PREP 统计使用 milestones.PREP。
- M0 首批计划：保留 command.received，单独筛选一次领域效果；同键重试比较完整 Event 流。TEST-011 实际执行归 M2-02，M0-06 只做非适用登记；同步 roadmap/backlog 映射。
- 上述仅修订准备材料。规范、知识图谱、准备工具与原有测试源未改动；初始/受审/接纳摘要在 closeout 和 acceptance-index 中。
- 主会话写集：上述已审窄修订、backlog/status、收尾计划、两个 Skill 历史证据的日期增补、MEMORY.md、本稿、closeout JSON、acceptance-index、独立材料探针与主会话验证记录。
- Reviewer 独占写集：其各份实际审查 JSON；PREP-008 仅 2026-09-08-prep-008-review.json。主会话不改写独立结论。
- 固定命令/测试会刷新五个生成报告：preparation-report、devprep-check、knowledge-graph-check、backlog-check、environment。没有新建产品源码、M0 测试或产品成果。

## 验证口径与证据缺口

修订前 10 项有界材料探针中 7 项失败（exit 1），修订后 10 项通过（exit 0），记录在 2026-09-08-preparation-corrections-red/green.json。探针只对文档与提取的方法注入内存反例，不是产品 RED/GREEN；RED 方法行号是提取块相对行号。首次自写审查器误判与修正记录保留，不冒充产品缺陷。

PREP-007 独立审计的 56 条命令均记录起止和退出码。corrections 复核共 16 条命令，14 条有完整起止；两条辅助历史命令分别缺结束或开始时间，但各有一个真实时间点、退出码和明确缺失说明（structural-inspector-attempt1、read-old-scenario-ids-and-fixture-contract）。不倒推补造时间；总审查须独立评估此记录是否满足验收要求。本轮实际验收重跑统一记录完整起止、退出码与输出。

## 环境、权限和未覆盖风险

- 阶段保持 preparation；产品完成率 0%；Bootstrap not_started；Conformance 28 registered / 0 passed。五对象模拟、Runtime、28 条产品验收和 Bootstrap Acceptance 都未执行；缺少产品实现不是准备验收的循环前置条件。
- git status --short 实际退出 128：不是 Git repository。未初始化、分支、commit/push，也无 Git worktree 隔离。明确写集与 SHA-256 只是变更检测，不是跨进程锁。
- ClaudeLink 无可用工具，MCP resources/templates 为空；真实协作使用会话 Agent 消息，不虚构收信/公告或外部在线成员。
- 未安装依赖、改全局/用户配置或读取密钥。environment 只报告本地可识别版本/能力，不认证可执行文件，不能证明第三方内部绝不读配置，更不授予后续外部执行权限。
- check 失败不会删除旧成功报告；使用方必须核对本次命令退出码、时间与来源。Markdown 校验有界，不是通用语法/所有链接解析器。

## 冻结审核及通过后的限定收尾

本稿与 acceptance-index 是 PREP-008 的待审输入，不预先承诺通过。Kant 独立核验逐项证据、真实身份、源摘要适用性、命令记录与产品边界；审查期间主会话冻结这些输入和共享状态，reviewer 仅在材料私有副本执行会写报告的命令。

只有真实 PREP-008 preparation-level pass 且摘要适用后，主会话才可将 PREP-008 review → done，随后 M0-01 todo → ready，其他产品项保持 todo。只更新实际状态/计数/证据元数据、MEMORY 当前快照、计划勾选与生成报告，并在本稿末尾追加最终接纳记录；此前受审正文保留不改。允许变更详列 acceptance-index 的 permitted_post_pass_finalization；受审静态材料、稳定 backlog 契约和原始独立报告保持不变。

下一步：交给唯一 Kant 作 PREP-008 总审查；若不通过保留 review。即使通过，也不自动启动 M0、安装依赖或初始化 Git。

## 送审前实际验证（冻结证据）

完整命令、开始/结束时间、退出码与 stdout/stderr：`Docs/development/evidence/2026-09-08-preparation-integrated-validation.json`。

| 命令 | 开始时间（+08:00） | 结束时间（+08:00） | 退出码 |
| --- | --- | --- | --- |
| `git status --short` | 2026-09-08T21:54:07.825305+08:00 | 2026-09-08T21:54:07.871170+08:00 | 128 |
| `python Docs/development/evidence/2026-09-08-preparation-corrections-probe.py` | 2026-09-08T21:54:07.871266+08:00 | 2026-09-08T21:54:08.117673+08:00 | 0 |
| `python tools/devprep.py render` | 2026-09-08T21:54:08.117753+08:00 | 2026-09-08T21:54:08.329582+08:00 | 0 |
| `python tools/devprep.py check` | 2026-09-08T21:54:08.329657+08:00 | 2026-09-08T21:54:08.546456+08:00 | 0 |
| `python -m unittest discover -s tests/preparation -v` | 2026-09-08T21:54:08.546530+08:00 | 2026-09-08T21:54:10.787407+08:00 | 0 |

结果：27 项准备工具测试及 10 项有界材料探针通过；静态图谱 101 节点 / 144 边、20 工作项无环、3 Skills。以上不是产品测试。

状态整合的第一轮 render 曾因主会话遗漏零值状态计数 exit 1，完整 RED 保留于 `2026-09-08-preparation-integrated-validation-red.json`；只补齐 status.json 的六种计数键后完成上述 GREEN，未修改工具、测试或受审契约。

<!-- PREP-008-FROZEN-HANDOFF-END -->

## 2026-09-09 最终接纳记录（取代正文中的送审状态）

记录时间：2026-09-09T19:13:32.737359+08:00。以上 2026-09-08 冻结正文完整保留，属于送审历史；当前状态以本节与 backlog/status 为准。

- PREP-001..008：8/8 done；M0-01：ready、未启动；其他 11 个产品项 todo。全计划 8 done / 1 ready / 11 todo 不是工时或产品完成率。
- PREP-008 独立 reviewer：Kant（01a07cac-b6db-7393-ae38-bce13d69c67d），不同于集成交接执行者主会话；真实完成于 2026-09-09T19:07:57.143853+08:00，三项验收 preparation-level pass。
- 报告：Docs/development/evidence/2026-09-08-prep-008-review.json；文件名沿用 9 月 8 日任务标识，不是完成日期。SHA-256 e987af3ae6b1fb361a33771edbb86fc509eba58ddbe8bcc8945c9212592136e6。
- 主会话接纳前重新核验 42 个受审路径摘要、8 个冻结 payload 与稳定 backlog 契约；三项验收和限定 post-pass finalization 均获独立接受，真实状态转换记在 closeout.json。
- 准备验收没有改变产品边界：phase preparation、产品 0%、Bootstrap not_started、Conformance 28 registered / 0 passed。没有 M0 产品文件、运行时或产品测试。
- 历史 corrections 两条辅助命令的单端点记录与缺失原因保留；独立审查根据实际验收文字接受，不补造时间，也不误报为完整双端点。
- 修改仅为已接受的状态/证据/计数、MEMORY 快照、收尾计划勾选、本节追加和标准生成报告刷新；冻结 index、旧独立报告、规范/Skill/图谱/roadmap/M0 计划/工具测试源均不改。
- 后续动作：在下一次获准接手 M0-01 时，确认文件范围、环境/权限、失败夹具与独立复核安排，再开始 TDD。当前 ready 不等于已经实施，不自动初始化 Git、安装依赖或启动外部效果。
- 最终主会话复验：Docs/development/evidence/2026-09-08-preparation-final-validation.json（沿用计划文件名，真实日期以起止时间为准）；测试只证明准备工具，不是新的独立评审。

### 2026-09-09T19:19:06.098595+08:00 最终回归返修（暂缓上一节接纳）

27 项准备测试中 positive ready fixture 在 PREP-008 done 状态下失败；工具正确拒绝矛盾依赖。已将 M0-01 撤回 todo、PREP-007/008 重开 review，其余六项 done。仅修准备测试夹具，须唯一 Kant 补充独立审查；旧报告/index/冻结正文均保留。失败证据：2026-09-09-preparation-regression-red.json；范围见 closeout.regression_rework。
