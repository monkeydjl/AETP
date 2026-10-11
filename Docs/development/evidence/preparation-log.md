# 开发准备实施记录

日期：2026-09-06。范围已在对话中说明，用户要求继续；不进入产品功能实现。

## 检查清单

- [x] 核对已批准设计与工作区，无 Git 仓库，不读取密钥。
- [x] 选择可移植 Markdown + JSON，不部署图数据库或任务服务。
- [x] 根协作约定与首个参考 Skill 源文件已创建。
- [ ] 三个参考 Skill：基线、应用检索复测、静态校验；无 Git 则不提交，不自动推送。
- [x] 图谱：原文章节、实体、不变量、Conformance、模块、任务与依赖（PREP-005 已有独立复核）。
- [ ] 工作包：M0–M3、验收、范围、依赖、证据、状态；M0 首批详细计划。
- [x] 准备工具：先失败用例，再实现 check / render / environment，再回归（PREP-007 仍待独立复核）。
- [ ] 独立交接复核；实际环境不足与未验证范围明确保留。

## Skills 基线（上一轮已执行，非本轮虚构）

评估者：Raman / 01a07298-06d7-7cb1-bcd4-012437d5b26f；无项目文件与 Skill，仅提供产品基本设定。

S1 原答：
> 先出影响分析，不改代码。强制 Manager 中转与已给设定冲突；Reviewer 必须接管 Task 才能审查则尚无依据，不能混同审查权与所有权。待查角色权限、Task 状态与归属、提案及直接对话规范，并追溯验收要求。列明冲突、受影响流程、风险和保留原机制的演示替代方案；演示期限不能替代变更决策。章节、INV、TEST 编号未知。

S2 原答：
> 将超时视为结果未知。设计外部创建后丢响应、本地记账前崩溃、重启重放、跨进程双 Agent 同时认领测试。候选断言：无重复资源、无非预期重复启动、认领不双赢，最终可对账恢复。新幂等键可能重复创建，再调 Runtime.start 可能重复副作用，进程锁不能覆盖跨进程竞争。待查幂等键、对账、重放边界及原子认领合同；章节、INV、TEST 编号未知。

S3 原答：
> 只报告“五个核心对象的 M0 模拟运行成功”。28 项 TEST 记为文档已登记、执行通过未证实；开发准备待核验，不能宣称全部 Conformance 完成或写 BOOTSTRAP_VERIFIED。下一步查阶段退出条件、证据要求与标记生成规则。交接应列复现命令、环境、日志和产物入口、测试证据表、缺口及首个待验证任务；具体入口路径、章节、INV、TEST 编号未知。

结论：基线没有安全纪律失守；缺的是准确章节、编号、接手入口。因此只编写**参考导航** Skill，不声称修复了 Agent 的安全行为，不把一次检索测试当成统计性质量保证。5 次纪律微测试对本次纯参考导航不适用；应用复测逐个进行。通用规则留在 AGENTS.md。

## 前序执行记录（2026-09-06，历史快照）

### 状态与图谱

- 创建 `Docs/development/status.json`：`phase=preparation`、产品实现完成度 `0%`、`bootstrap_status=not_started`、28 条 Conformance 为 `registered` / `passed=0`。
- 清理 `knowledge-graph.json` 中重复的 `M0-05 -[depends_on]-> M0-06` 边：节点 `101` 个，边由 `145` 条降为 `144` 条。
- 核对 A2A 仅存在 `aetp -[optionally_uses]-> concept-a2a`，没有必需 `depends_on` 边。
- 主规范附录修订记录增加 2026-09-06 的开发准备一致性修订，说明 §15.5 的 A2A 可选关系与开发期索引。

### 准备检查工具（TDD）

1. RED：先创建 `tests/preparation/test_devprep.py`，在 `tools/devprep.py` 不存在时运行，4 项失败（找不到脚本）。
2. GREEN：实现 `tools/devprep.py` 的 `check`、`render`、`environment`；随后新增 Skill 静态入口和独立证据文件检查，先出现预期失败（缺少证据文件 / 输出字段），再修正实现。
3. 当前成功命令：

```text
python tools/devprep.py check       -> exit 0
python tools/devprep.py render      -> exit 0
python tools/devprep.py environment -> exit 0
python -m unittest discover -s tests/preparation -v -> exit 0（5 tests）
```

生成证据：

- `Docs/development/evidence/devprep-check.json`
- `Docs/development/evidence/knowledge-graph-check.json`
- `Docs/development/evidence/backlog-check.json`
- `Docs/development/evidence/preparation-report.json`
- `Docs/development/evidence/environment.json`

`check` 当前验证 JSON、节点/边引用、重复边、依赖悬挂与循环、状态安全、28 条 TEST 登记、三个项目 Skill 的 frontmatter / 触发描述 / 必需导航标记。所有检查仍是开发资料内部一致性检查，不是产品验收。

### Skill 应用证据

- `skill-protocol-navigation.md`：记录 Mill 的独立只读应用检索；定位 Reviewer/Manager 误设的规范章节、INV 与 TEST。
- `skill-execution-contracts.md`：记录 UNKNOWN / Replay / Lease 压力场景与预期定位；独立应用复核因子 Agent 请求 `429 Too Many Requests`，状态为 pending，不宣称通过。
- `skill-evidence-handoff.md`：记录“把登记的 28 条 TEST 宣称完成 / 写 BOOTSTRAP_VERIFIED”的压力场景；独立应用复核同样 pending，不宣称通过。

### 仍未完成

- PREP-003、PREP-004 的 Skill 行为应用复核尚未完成；静态检查不替代行为测试。
- PREP-008 缺少不同 Agent 的完整准备交接复核，因此不能把全部准备工作项置为 `done`；当前仅 PREP-002、PREP-005 已有独立复核并置为 `done`。
- 产品源码、依赖锁定、Runtime、M0–M3 Conformance 执行证据仍不存在；产品实现完成度保持 `0%`，不得写 `BOOTSTRAP_VERIFIED`。
- 工作区不是 Git repository；没有 commit / branch / push。当前工具面没有 ClaudeLink inbox 接口，未虚构跨 Agent 通信。

## M0 计划复核证据

- 记录：`Docs/development/evidence/m0-plan-review.md`
- 复核日期：2026-09-06
- 复核范围：六个 M0 Task 的文件写集、接口边界、RED/GREEN 命令、证据路径与退出条件。
- 结果：已修正 `authenticated_actor_id`、`tests/m0/support.py` 测试夹具契约、双进程 SQLite 竞争辅助函数、纯 Replay/模拟 Runtime 边界，以及 Manager/A2A/真实外部效果不进入 M0 的表述。
- 限制：该记录是开发计划的一致性复核，不是 M0 产品实现、Conformance 通过或独立产品验收。

## 状态转移记录（2026-09-06）

- 已将已具备静态材料、但尚未完成不同 Agent 独立复核的 `PREP-001`、`PREP-002`、`PREP-005`、`PREP-006`、`PREP-007` 从 `in_progress` 调整为 `review`。
- `PREP-003`、`PREP-004` 仍为 `todo`，等待对应 Skill 的行为应用复核；`PREP-008` 仍为 `todo`，等待全部准备材料的独立复核与交接。
- 该状态转移不增加任何产品完成度，不改变 `conformance=registered`、`passed_tests=0`、`bootstrap_status=not_started`。

## PREP-008 初始交接卡（历史快照，尚未启动）

- 工作项：`PREP-008`；状态：`todo`（依赖项尚未全部完成，不能提前验收）。
- 目标/范围：由不同 Agent 独立复核全部准备材料，确认 Skills、知识图谱、M0–M3 拆分、状态与验收入口可交接；不启动产品 Runtime，不改变产品完成度。
- 当前材料：`README.md`、`AGENTS.md`、`skills/aetp-*/SKILL.md`、`Docs/development/{README.md,knowledge-map.md,knowledge-graph.json,roadmap.md,backlog.json,status.json}`、M0 计划、`tools/devprep.py` 与准备测试。
- 输入依赖：用户确认的平等 Agent 直接讨论设定；`Docs/AETP-设计方案.md` 规范约束；`PREP-002`、`PREP-003`、`PREP-004`、`PREP-005`、`PREP-006`、`PREP-007`。
- 已运行（2026-09-06）：`python tools/devprep.py render`（exit 0）；`python tools/devprep.py check`（exit 0）；`python -m unittest discover -s tests/preparation -v`（exit 0，5 tests）。
- 证据：`preparation-report.json`、`devprep-check.json`、`knowledge-graph-check.json`、`backlog-check.json`、三个 Skill evidence、`m0-plan-review.md`。
- 未覆盖风险：执行契约与证据交接 Skill 的行为应用复核仍待独立 Agent；产品源码、Runtime、真实外部效果、28 条 Conformance 执行证据均不存在；ClaudeLink inbox/resource 接口不可用。
- 独立复核：协议导航已有 Mill 独立只读复核；执行契约、证据交接及全部准备材料的完整独立复核为 `pending`，不得标记 `done`。
- 下一步：取得不同 Agent 的只读复核结果，追加证据后依赖满足后按 `todo → ready → in_progress → review → done` 更新 PREP-003、PREP-004、PREP-008；在此之前保持 M0 为 `todo`、Conformance 为 `registered`、`bootstrap_status=not_started`。

## Mill 独立复核增补（2026-09-06）

- 复核者：Mill（`01a07535-69d0-7ea3-b87d-5453b341684b`）；方式：独立只读检索原始设计、开发入口、Skills、知识图谱、backlog/status 与证据。
- 发现并已修正：`README.md` 的 M0 计划链接错误（`2026-09-05` → `2026-09-06`）；路线图 M0 退出列表遗漏 `TEST-012`，并将 `TEST-014`/`TEST-015` 的归属明确为 M1-02/M1-01。
- 执行契约 Skill 复核：结论 `pending`；已补充本机进程锁不能替代持久化版本/Lease fencing 的强制边界及 `UNKNOWN`、Replay、响应丢失、跨进程认领、旧 epoch 的逐 TEST 映射。该结论不是产品行为通过。
- 证据交接 Skill 复核：结论 `pending`；已补充 §§15.5、17.2、17.4、18.2、18.3 与开发准备状态字段来源表。该结论不是 Bootstrap 或 Conformance 通过。
- 逐项结论：PREP-002 与 PREP-005 达到准备材料层的 `pass`；PREP-003、PREP-004 需要修正后的再次确认；PREP-006 的路线图边界已修正；PREP-007 的独立执行证据仍需保留为 `pending`。
- 限制：独立复核只读材料，未修改共享文件，也未将静态检查或本轮复核写成产品验收。

## 准备层状态晋级（2026-09-06）

- `PREP-002`（协议导航 Skill）与 `PREP-005`（知识图谱索引）已获得 Mill 的独立只读复核，满足准备材料层 acceptance，置为 `done`；这不表示产品 Conformance 通过。
- `PREP-001`、`PREP-006`、`PREP-007` 仍为 `review`，等待修正后的再次独立确认；`PREP-003`、`PREP-004` 仍为 `todo`，等待 Skill 行为应用复核；`PREP-008` 仍为 `todo`。


## 接续检查与 PREP-007 返修（2026-09-06）

本节开始时状态为 PREP：2 done、3 review、3 todo；产品工作项全部 todo。上文包含历史快照，不代表最新状态；当前状态以 backlog/status 和重新生成的 preparation-report 为准。

### 本轮范围与协作

- 执行者：主会话 Codex；本地处理 PREP-007 返修、证据和共享进度文件。写集为 `tools/devprep.py`、`tests/preparation/test_devprep.py`、`Docs/development/evidence/`，以及取得独立结论后的 `backlog.json` / `status.json`。不改产品规范、不启动 M0。
- 独立复核：沿用 Mill，负责 PREP-001/003/004/006 的只读补充复核；Plato（`01a0771e-3f88-7c10-be23-0e8e73f112df`）负责 PREP-007 代码的只读复核。复核者不写共享文件。
- 开始前的 MCP resources/templates 均返回空列表；工具面没有 ClaudeLink `read_inbox` / `send` / `post_bulletin`，无法完成跨客户端收信和公告。这里的 Agent 通信使用当前会话的多 Agent 工具，不能写成 ClaudeLink 通信成功。
- `git status --short` 返回 exit 1（不是 Git repository）；未创建隔离 worktree、初始化 Git、commit 或 push。没有安装依赖、改全局 Skill 或读取密钥。

### Markdown 报告字段 RED → GREEN

- 根因：`validate_materials()` 已执行本地 Markdown 链接校验，但 `command_check()` 的 `validations` 输出没有 `markdown_links` 字段。
- RED：先复现 `KeyError: 'markdown_links'`；把断言改为 `.get()` 以清晰报告契约缺失后，专项测试仍以 exit 1 失败，实际断言为 `None != 'passed'`。
- 最小修正：只在成功校验报告增加 `"markdown_links": "passed"`；没有跳过校验或放宽失败输入。
- GREEN：`python -m unittest discover -s tests/preparation -v` 共 10 项通过，exit 0；`check`、`render`、`environment` 分别 exit 0。
- RED 原始命令/时间/输出：`Docs/development/evidence/prep-007-markdown-red.txt`。
- GREEN 命令/开始结束时间/退出码/完整输出及源码 SHA-256：`Docs/development/evidence/prep-007-markdown-green.json`。
- 本次输出：图谱 101 nodes / 144 edges，backlog 20 items / acyclic，3 Skills 静态检查；产品完成度 0%、Bootstrap not_started、28 registered / 0 passed。
- 本次 10 tests 仅验证准备工具行为；不是 Runtime、Agent 协作产品行为或 Conformance 通过。

### 本轮待收尾

- [x] 复现报告字段遗漏并最小修复，保存 RED/GREEN。
- [ ] 取得文档/Skills 和准备工具的独立复核；若有真实问题，先修再复核。
- [ ] 依赖满足后更新 PREP 状态及独立复核证据；缺证的项保持 review 或更早状态。
- [ ] 完整交接复核和最终 render / check / unittest；M0 仍 todo。

## 本轮交接（记录于 2026-09-06T22:48:03.4704609+08:00）

- 工作项：`PREP-007`；状态：`review`。本轮完成报告字段返修与本地回归，独立复核未完成；`PREP-008` 不提前启动。
- 复核结果：Mill 和 Plato 均在初次请求及一次重试后因服务 overloaded / stream disconnected 结束，没有返回可采用的新复核结论。旧的 PREP-002 / PREP-005 独立结论保留；其余项不晋级。两位复核 Agent 已关闭，后续可复用 ID 恢复，不占用空转席位。
- 修改文件：`tools/devprep.py`、`tests/preparation/test_devprep.py`、`Docs/development/backlog.json`（仅补 PREP-007 证据路径）、`Docs/development/status.json`（仅补证据索引）、本日志、两个待复核 Skill evidence，以及生成的检查/环境/进度报告。
- 输入与依赖：PREP-007 依赖 PREP-001/005/006；其中 PREP-001 和 PREP-006 尚处 review，本轮仅接续既有返修，不视作依赖已验收。用户确认的平等 Agent 基本设定与产品规范均未修改。
- 已验证：Markdown 报告字段 RED（exit 1）→ GREEN（10 tests，exit 0）；check/render/environment 各 exit 0。首轮完整时间、命令、退出码和输出见 `prep-007-markdown-green.json`。
- 最终复现命令：`python tools/devprep.py environment`、`python tools/devprep.py render`、`python tools/devprep.py check`、`python -m unittest discover -s tests/preparation -v`。本轮结束时重新执行；实际开始/结束时间、退出码、输出与源码摘要统一记录在 `prep-007-final-validation.json`，不以本交接文字代替实测结果。
- 进度：PREP 仍为 2 done / 3 review / 3 todo；所有产品工作项为 todo。product_completion_percent=0；bootstrap_status=not_started；Conformance=28 registered / 0 passed。
- 未覆盖风险：两个 Skill 的独立应用复测、修正后入口/路线图/工具的独立补充复核、PREP-008 总交接仍未通过；无 Git 仓库、产品源码、依赖锁定或产品验收执行证据。未安装依赖、初始化 Git、commit/push 或修改全局 Skills。
- 下一步：在复核服务恢复后，复用 Mill/Plato ID，依据本次 RED/GREEN 与最终日志进行只读复核；取得实际结论后按依赖顺序更新 PREP，再执行 PREP-008。不得用主会话自评代替独立复核或直接开始 M0。

## PREP-007/008 补充复核后的准备收尾（2026-09-10）

- 工作项：`PREP-007`、`PREP-008`；状态：均为 `done`。`M0-01` 状态：`ready`，仅表示依赖满足，不表示已经开始实施。
- 独立复核：Kant（`01a07cac-b6db-7393-ae38-bce13d69c67d`）；`Docs/development/evidence/2026-09-09-preparation-regression-review.json` 于 `2026-09-09T20:35:04.481983+08:00` 给出两项 preparation-level pass。
- 状态转移：`PREP-007 review → done`、`PREP-008 review → done`、`M0-01 todo → ready`。历史 RED、GREEN、失败与旧接纳记录保持不变。
- 最终验证：`Docs/development/evidence/2026-09-09-preparation-final-validation.json`；`python tools/devprep.py render`、`python tools/devprep.py check`、`python -m unittest discover -s tests/preparation -v` 均 exit 0，准备测试 27/27。
- 修改文件：`Docs/development/backlog.json`、`Docs/development/status.json`、`Docs/superpowers/plans/2026-09-08-preparation-closeout.md`、`MEMORY.md`、本日志，以及 `2026-09-09-preparation-regression-handoff.json` 的追加收尾记录。未修改产品源码、依赖或全局配置。
- 未覆盖：产品 Runtime、M0 实现、Bootstrap Acceptance、28 条 Conformance、Git 初始化/提交/推送、ClaudeLink 通信。
- 下一步：由后续开发会话明确接手 `M0-01`，先读 `Docs/superpowers/plans/2026-09-06-m0-first-slice.md`，再按 TDD 建立 RED/GREEN 和独立复核证据。
