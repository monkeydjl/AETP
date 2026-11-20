# M3-02 Integration 契约前置批次详细设计

日期：2026-09-15（Asia/Shanghai）。工作项：M3-02。

**状态：范围已获用户确认，用户随后多次要求继续；2026-09-16 完成作者自查，先按独立计划执行纯输入切片。完整契约未实施、未独立验收。**
执行者：当前 Codex 会话；交接对象：用户与后续实施/独立复核者。

## 1. 决策、目标与非目标

用户已同意先形成“权威集成目标声明、豁免互斥、旧入口防绕过、能力缺失时拒绝”的详细设计。选择分批补齐契约，不一次引入真实 Git Provider 和系统 Runner：后者需要额外执行边界、真实引用更新、UNKNOWN 对账以及独立验收，不能由当前固定 JSON 文档能力代替。

本批实现目标（尚未实现）：

1. 当前 human_owner 通过认证 Command 为具体 Task 登记不可变、版本化的“需要集成”声明和目标意图。
2. 声明与当前质量 Policy 的无集成面豁免不能同时有效；历史豁免不能绕过后来的集成要求。
3. 所有服务共用持久化提交门，Projection 也拒绝不合法成功事实；缺少能力时保持关闭。
4. 不破坏已接受历史的逐前缀纯 Replay、幂等、完整 revision 和终止态规则。

明确不做：Git 初始化、真实 merge/commit/ref 更新、Provider 注册、系统 Runner、合并 Action、合并成功/冲突/UNKNOWN、Mission Acceptance、正式 Team/Blueprint 激活、Bootstrap、真实模型调用或 TEST-028。不得把不存在的 Git 操作登记为失败、冲突或 UNKNOWN。

本批不会推动 Task 进入 READY_FOR_INTEGRATION、INTEGRATING、INTEGRATED、SYSTEM_VERIFIED，亦不会为需要集成的 Task 开启 COMPLETED。未声明集成要求的旧 Task 仍只能按已接受的显式 standalone_fixed_json_document 豁免规则完成；“没填目标”不是新豁免。

## 2. 权威输入与当前事实

权威顺序不变：用户确认的基本设定 → 主规范 → 补充建议 → 本设计 → 派生索引。本文是限定实现方案，不修改主规范，不新增顶层 Entity，不改变平等 Agent 或审查权。

| 来源 | 本批使用的约束 |
| --- | --- |
| `Docs/AETP-设计方案.md` §§7.3、10.6 | VERIFIED 不等于 INTEGRATED；只有明确无集成面的 Policy 豁免可跳过 Integration；结果 commit 必须有新系统 Verification |
| 同文 §§7.6、7.10、13.9 | 执行 Binding/Lease/epoch、真实调用边界；能力声明不是执行证明；Runtime 不选择权威后态 |
| 同文 §§14.1–14.2、13.4、13.10、14.4 | 原子事实链、幂等与冲突、暂停、纯 Replay、外部 UNKNOWN 不盲重试 |
| `Docs/development/backlog.json` 的 M3-02 | 三项原验收不缩减；依赖 M3-01 已 done |
| `Docs/development/evidence/2026-09-15-m3-02-quality-next-slice-inputs.md` | 真实集成、Mission 与自主交付的缺口及后续证据要求 |
| `src/aetp/quality/`、`src/aetp/acceptance/` | 已有固定文档质量轮次与明确 Task 豁免，不具有 Git 集成能力 |
| `src/aetp/core/commands.py`、`src/aetp/core/projection.py` | 各服务共享的事务入口，以及因果游标和确定性重放入口 |

不可变基线：`Docs/development/evidence/2026-09-15-m3-02-integration-baseline.json`，SHA256 `eb2d9ced3df5029a5a900035f46f1a64ddd7a86009dbeb3479145e1a2dc3b751`。已于前置核验检查 1067 条归档映射、505 个 blob 和 6 个 pins；记录在 `Docs/development/evidence/2026-09-15-m3-02-integration-preflight-v2.json`。这些数字不是本设计的功能通过数。

当前 M3-02 in_progress，19 done / 1 in_progress。Verification 与 Task 质量两个限定批次 accepted；完整 M1 not_accepted；phase=preparation、product_completion_percent=0、bootstrap_status=not_started、完整 Conformance 28 registered / 0 passed。历史 README/AGENTS 中“尚无产品源码”的准备期描述不作为实时进度证据。

## 3. 架构与数据归属

新增 `IntegrationContractService(TaskQualityService)` 只受理声明。复用已存在的受信身份、InputAuthority、resource gate、SQLite writer transaction 与 CommandResult；不创建自己的事实库或可变权威缓存。

```text
当前 human_owner + 真实 ingress receipt
  → project.integration.declare
  → resource gate → BEGIN IMMEDIATE
  → 当前 Project/Task/治理身份/双 revision/豁免冲突校验
  → command.received + project.integration_declared
  → 同事务 CommandResult / idempotency result
  → Project.integration_contract Projection
```

集成需求是 Project 内按 Task ID 索引的版本化子资源，不是新的顶层 Entity、Task Lease 或 Integration 执行记录。成功声明只增加 Project revision，不修改目标 Task revision、quality_cycle、状态、Lease、Binding、Artifact、Review 或 Verification。

该放置方式避免仅登记需求就无依据地重标质量轮次。声明也不授予旧证据新的适用性：任何后续真实 Gate 必须另行检查完整质量证据、目标和执行快照。

新增模块边界：

| 模块 | 单一职责 |
| --- | --- |
| `integration/contracts.py` | 固定 schema、Command/Event 集合、纯输入类型/长度约束 |
| `integration/validation.py` | 纯输入形状、标识/ref/OID 与版本引用校验；不校验权限或当前 State |
| `integration/records.py` | 在给定事实状态、时间与来源证明下确定性生成声明记录 |
| `integration/service.py` | 收集受信 ingress 观察，使用 gate 与共享 CommandHandler |
| `integration/guards.py` | 共享提交门与 Projection 不变量；只读事实，不访问外部设施 |
| `integration/projection.py`、`integration/causality.py` | 复算声明、验证 receipt/digest/revision/终结与游标 |
| `integration/README.md` | 实际支持范围、拒绝契约和不支持的后续能力 |

## 4. 声明 Command 与固定数据模型

### 4.1 `project.integration.declare`

Command.target_id 必须等于 project_id；Command.expected_revision 是当前 Project 完整 revision。payload 固定字段如下，未知字段拒绝：

| 字段 | 语义 |
| --- | --- |
| `task_id` | 同一 Project 中已存在的 Task |
| `expected_task_revision` | 当前 Task 完整 revision，附加跨聚合读前提；不能代替 Command.expected_revision |
| `version` | 本 Task 声明版本正整数，首次为 1，后续严格为 current+1；bool 不当作整数 |
| `supersedes_version` | 首次显式 null；后续必须等于当前版本 |
| `requirement` | 固定字符串 `required`，无 `exempt`/`optional`/`none` 分支 |
| `target` | 下述固定目标意图结构 |
| `reason` | 去首尾空白后非空的理由，最多 2048 字符；不静默改写原请求 |

Target 结构固定为：

```json
{
  "provider_id": "future_git_provider",
  "repository_id": "project_repository",
  "object_format": "sha1",
  "source": {"ref": "refs/heads/agent/task_042", "commit": "1111111111111111111111111111111111111111"},
  "target": {"ref": "refs/heads/main", "expected_commit": "2222222222222222222222222222222222222222"}
}
```

此例仅为语法样例，不指向真实仓库或 commit。provider_id/repository_id 是当前 Project 命名空间内的**不解析的意图标识**，不是路径、URL、凭证或已注册能力。实现不据此访问文件、联网或创建 Provider。

输入界限：

- 每次只声明一个 Task；Project 最多 64 个不同 Task 的声明，每 Task 最多 64 个版本。上限达到则拒绝，不驱逐旧版本；后续扩容需另行设计。
- 两个标识均采用 ASCII `[A-Za-z0-9][A-Za-z0-9_-]{0,127}`。
- ref 最长 255 个 ASCII 字符，以 `refs/heads/` 开头；后续至少一个非空组件，每组件使用 `[A-Za-z0-9_][A-Za-z0-9_-]*`，组件之间仅一个 `/`；不接受 `.`、`..`、反斜杠或 shell 表达式。source.ref 与 target.ref 不相同。这是保守语法子集，不宣称完成 Git ref 语义校验。
- object_format 只允许 sha1/sha256；对应 commit 必须为 40/64 位小写十六进制且非全零。拒绝短哈希、符号引用、格式混用；不检查对象是否存在或是否为 commit。
- 所有层级拒绝多余字段；不接受 caller 提供的 author、binding、epoch、Policy 摘要、verified、result_commit、后态或 authority。
- 摘要使用现有 canonical_json/digest_value 约定；不得把 JSON 内容摘要当作 Git OID。

2026-09-16 作者自查补充：Task ID 复用既有 identifier 规则（非空、无首尾空白、有效 UTF-8、最多 512 字节）；reason 的 2048 上限按 Unicode 字符计算，拒绝代理码点，不裁剪原文。整数均为严格 int，revision 使用既有非负 64 位范围；版本限 1–64，前版引用必须与 version 自洽，当前历史匹配另在事务内校验。

### 4.2 服务端派生记录

Project 新增 `integration_contract`，固定 schema 为 `aetp-integration-contract-1`。其 `tasks[task_id]` 保存 current_version 和只追加的 versions。每版记录：

- task_id、version、supersedes_version、requirement、target、reason；
- declared_by（认证当前 human_owner）、command_id、observed_at_ms；
- 声明时完整 Project/Task revision；Task criteria_digest、owner_id、current_binding_id、lease_epoch、workspace_provider_id；
- 当前 Governance owner/version/content_digest、当前 Task Quality Policy version/content_digest；
- InputAuthority 验证后的完整 source 记录；
- content_digest：除自身 digest 字段以外全部上述版本记录的规范化摘要。

versions 使用版本整数的规范十进制字符串作为 JSON key；历史版本和各摘要不可覆盖。current_version 仅随合法 supersession 移动。

### 4.3 授权、目标与时态

声明属于人类需求配置，不是作者执行或 git.merge 批准：

1. actor 必须与认证连接一致，且在事务内仍是当前 Governance human_owner；bootstrap、其他人类/Agent、历史 owner 均无此权。
2. 必须有真实 InputAuthority receipt，绑定同一 Command digest/actor 和当前配置的 authority；source_record 的 untrusted_input 必须 false。伪造 JSON、复制 capability、缺失/unknown/marked 来源均拒绝，不用模型自述恢复信任。
3. Project 必须在已支持的 planning/active 状态且不在 candidate-only 执行禁区；本批不支持在 PAUSED 时新增或替换声明，不替代独立的治理暂停/取消入口。
4. Task 必须属于该 Project、具有现有固定文档 execution/quality policy 的支持范围以及一致的已归属 Binding/epoch 快照。允许阶段限定为 assigned、in_progress、ready_for_review、in_review、verified、rejected、blocked；terminal、pending、failed 和尚未实现的 Integration 阶段拒绝。
5. 声明不需要取得作者 Lease 或作者 Session；这是 human_owner 的配置职责，不是执行特权。记录过期执行快照不使其重新有效；本批不作 live execution attestation。
6. human_owner 的声明不修改 Governance 风险分级、不建立 Approval、不放行原本需审批的操作。本批无新增自动执行 action；真实合并的 Policy/Approval adapter 仍缺失。

### 4.4 版本过期与保守的持久要求

Task 的作者/Binding/epoch/criteria、当前 human_owner、治理或质量 Policy 改变时，记录的目标快照只能视为待重新确认的历史意图，不能作为未来 Gate 输入。普通质量生命周期 revision 增长也不自动扩展本声明的授权；未来 Gate 的复用契约另行设计。

**过期不等于解除“需要集成”。** 一旦出现合法 required 声明，该 Task ID 的要求在本批中保持；更换 owner、返工、清空 Policy 列表、选择旧版本或传入过期摘要均不能恢复豁免。当前 human_owner 可以带当前双 revision 和前版引用登记新 target；本批不提供删除、撤销、降级为豁免或复用 Task ID 的接口。

这是明确的支持范围限制，不是新增“人类永远不能撤回需求”的协议规则。误声明需等待另行设计的受控变更流程；不得通过编辑 State/数据库恢复豁免。终止 Task 的声明历史只保留，不复活 Task，也不追溯推翻声明前已完成的其他 Task。

## 5. 与已接受豁免的互斥和迁移

使用当前 Project Task Quality Policy 作为配置冲突判断，不用提交者提供的 Policy，也不只检查 Task 内旧 cycle：

- declare 时，如果当前 `integration_exemptions` 含目标 Task，拒绝 `INTEGRATION_SCOPE_CONFLICT`，Project/Task 均不变化。
- human_owner 应先通过原 `project.task_quality.configure` 发布**不含该 Task 豁免**的新完整 Policy，再以新的 Project revision 声明 required；不增加隐式删除豁免的副作用。
- 该 Policy 更新按原规则使绑定旧 Policy 的质量轮次过期；需要时沿既有 block/rework 重新执行，不能为了本批自动重签旧证据。
- required 已存在后，任何新的质量 Policy 若试图将此 Task 加入豁免，均在共同提交边界拒绝。对历史声明过期、Policy version 改变、Task 换代、旧服务实例同样如此。
- 同键重试已成功的旧配置只返回原 CommandResult，不重放领域效果、不恢复旧 Policy，因此不受新要求追溯拒绝；同键不同内容仍为 IDEMPOTENCY_CONFLICT。
- 未有 required 声明的 Task 不自动进入新契约：原显式豁免、完整 Review/Verification、实际执行上下文及双事实终态退役规则保持。

两次配置之间不存在“默认可完成”窗口：移除豁免后，新 Policy 无豁免且旧轮次失效；即使进程在声明前退出，也不允许默认完成。

## 6. 共享提交门及无执行能力的拒绝契约

### 6.1 不只依赖新 Service

`CommandHandler.handle` 的最终 BEGIN IMMEDIATE 内，从 Event Store 重建可信状态；在幂等命中检查之后、任何领域 `_evaluate` 之前运行 integration guard。所有继承服务必须经过该入口，不能相信调用者的 `integration_required=false`、schema、Policy 版本或旧实例缓存。

守卫至少覆盖：

- `project.task_quality.configure`：检查正在添加的每个豁免，拒绝任一已有 required 要求的 Task。格式错误回到明确的 INVALID_PAYLOAD 拒绝，不产生部分配置。
- `task.quality.complete`、旧 `task.complete` 以及本批注册的 `git.merge`；required Task 不能被旧完成入口推进。
- Project 更新不得丢掉/篡改已有 integration_contract；非专属声明事件必须保持该子资源字节语义一致。校验放在生成记录后的 Projection 不变量处，不能只对白名单配置路径打补丁。
- 未知 Command、受信 actor 不符、任意原始 status patch 仍遵循现有拒绝；不增加通用 Task 状态写入口。

守卫应返回拒绝结果，由既有受理链原子保存 command.received / command.rejected 与幂等结果。审计事件不是 Task/Project 领域迁移。

### 6.2 `git.merge` 的本批固定拒绝方言

为使能力缺失可观察，将 `git.merge` 注册为**只能拒绝的请求**：target_id 是 Task ID，expected_revision 是完整 Task revision，payload 仅允许 declaration_version（正整数）与 declaration_digest（`sha256:` 前缀加 64 位小写十六进制，沿用 `digest_value`）。其 source/target 只可引用服务器当前声明，不能传入 result、状态或替代 target。

共同纯守卫按以下次序判定：

1. 既有可信 actor、幂等和 Command 基础校验；
2. Project/Task 存在、同项目、支持范围、完整 revision、非终止与非 PAUSED；请求者须为当前有资格的 Task owner；
3. payload 形状和当前 required 声明存在、引用版本/摘要相等；
4. 返回 `ENFORCEMENT_UNAVAILABLE`，无论是否有人传入声称 ready 的 Provider/Runner/Session。

没有声明返回 `INTEGRATION_DECLARATION_REQUIRED`；错版本/摘要返回 `INTEGRATION_DECLARATION_STALE`；其他条件使用既有 typed 拒绝。声明快照是否仍可用于执行不在此请求中获准：即使引用正确也只能拒绝。这里不检查/签发一次合并的 live Session 权限，更不能把上述身份校验当作真实调用前的授权证明。

没有 `git.merge` 成功 handler、host record/dispatch 方法、integration.completed/conflict 领域事件、待执行 Action 或恢复查询。本批无可通过 dependency injection 打开的“测试成功模式”。需要真实 Provider 的后续方案必须新增受审实现版本，不能把本 schema 的开关翻为可执行。

`tool.request` 携带 git/shell 动作仍由现有固定 document action 白名单拒绝；不得为本批扩大 Tool/Runtime 能力。无 Runtime.start、shell、Git、网络、Provider.merge 或系统 Runner 调用。

## 7. Event Store、Projection 与历史兼容

声明的唯一成功领域事件是 `project.integration_declared`。保留原 command.received → 领域终结因果结构；payload 固定 integration_schema、原始 Command、受信来源 context、observed_at_ms、effect_index=0、effect_count=1、完整派生 record。receipt 地址/revision/digest、actor、project、correlation、causation 与实际 Command 一致。

Projection 重算声明，逐字段比较派生 record；不信任 payload 声称的 required、declared_by、摘要或成功后态。引入专属因果游标，拒绝缺失/重复 receipt、错误地址、篡改计数、重复终结、畸形 rejection、未知 schema 或把 schema 塞进 audit Event。

拒绝型 git.merge 只有 receipt/rejection 终结；游标拒绝同一请求出现成功领域事件。完整库验证还核对原始 Command/CommandResult；events-only 验证保留可从事实自证的 receipt/envelope 约束，不宣称替代外部库防篡改边界。

交叉守卫在 apply 前/派生记录校验后完成：

- 任一 required Task 的 integration_exempted 或 task.completed 成功事实拒绝；本批任何进入四个 Integration 状态的 Task 事实亦拒绝。这些判断不能仅依赖 integration_schema 存在。
- 为本批拒绝新伪造 Integration 成功事实，不重写原 Task 状态表，也不接受仅有合法状态字符串的事件。
- 任一 Project 事件不能无声移除、覆盖、倒退 integration_contract；仅合法声明可追加一个版本并移动对应指针。
- quality 双事实完成的连续性守卫仍有效，不允许在 integration_exempted 与 task.completed 之间插入声明；部分前缀不暴露 COMPLETED。
- 新 schema 引入后的游标、重复事件索引、State、last_sequence 必须在所有检查通过后一次发布；失败后保持调用前状态，不能“先写 State 再报错”。

旧前缀中不存在 integration_contract 时，不给 Project/Task 注入空对象、默认 required 或新 metadata。旧质量/治理 Event 继续原确定性算法；以**历史前缀当时的状态**检查冲突，不以当前 live 声明追溯否决历史完成。所有新旧冻结库逐前缀状态相等，历史库字节不变。

已有 Projection._from_cache 对 governance/planning/task_quality_policy 关闭不完整游标恢复；增加 integration_contract 的同等条件。持久结果恢复/未终结 Command 的检测也须识别新 receipt。不得只接入增量 apply 而漏掉完整库、events-only 或缓存恢复入口。

纯 Replay 不读当前时钟、文件、Session 注册表、InputAuthority.verify、Git、Runner 或 Provider；使用历史保存且经因果校验的来源证明。历史 receipt 不是可重新发行的 live capability。

## 8. 事务竞争、错误与恢复

- Project expected_revision 与 Task expected_task_revision 均在同一 writer transaction 内核对；第二个前提不能在事务外预读后缓存。
- 两条同基线声明、或配置豁免与声明竞争：至多一个成功；另一条拒绝 revision/conflict，不覆盖前者。
- Task complete 与 required 声明涉及不同聚合，但共享 SQLite 提交序列：若完成先提交，声明观察 terminal 并拒绝；若声明先提交，后到完成观察 required 并拒绝。不声称阻止已在过去合法发生的完成。
- 两条配置使用不重叠 Task 时仍遵循完整 Project revision；本批不放宽为字段级并发合并。
- 事务提交前失败：Command、审计/领域 Event、结果索引及 Projection 按既有事务原子回滚；事务提交后响应丢失：原 Command 原 key 重试返回原结果，不追加第二声明。
- 只有 receipt 的合成前缀保持无领域效果；异常实际存储提交由现有恢复契约处理，不据 receipt 自动创建领域效果。
- 本批没有外部效果，不能把 `abandoned`/UNKNOWN 对账测试假装真实 Git 恢复覆盖。暂停/恢复和在途文档/Verification 的已有语义不变。

错误码：复用 ACTOR_MISMATCH、PERMISSION_DENIED、REVISION_CONFLICT、IDEMPOTENCY_CONFLICT、INVALID_PAYLOAD、INVALID_TARGET/REFERENCE、PROJECT_INACTIVE、PLANNING_NOT_ACTIVE、INPUT_CONTEXT_INVALID、SOURCE_UNVERIFIED、INVALID_TRANSITION、ENFORCEMENT_UNAVAILABLE；新增限定业务拒绝为 INTEGRATION_SCOPE_CONFLICT、INTEGRATION_REQUIRED、INTEGRATION_DECLARATION_REQUIRED、INTEGRATION_DECLARATION_STALE、INTEGRATION_DECLARATION_VERSION_CONFLICT、INTEGRATION_DECLARATION_LIMIT。实现计划需逐条冻结错误优先序，不能把异常泛化为成功。

## 9. 验收与失败场景（待实现，非已通过）

下列编号是本设计内部场景标签，不是新的 Conformance TEST/INV 编号。RED 必须来自真实执行的失败断言，工具启动/夹具错误另记，不冒充产品 RED。

| 组 | 必须执行的正向/反向断言 |
| --- | --- |
| A 声明与派生 | 当前 owner + 实际 receipt + 双 revision 成功；仅 Project revision+1；Task/质量/执行对象不变；摘要和历史完整 |
| B 身份来源 | 冒充 actor、其他成员/旧 owner、bootstrap、缺 receipt、复制 receipt、错误 authority、unknown/marked 祖先拒绝；无领域效果 |
| C 输入 | 错字段/类型、bool revision/version、短/全零/混合格式 OID、非法 ref/path/URL、超长/超限、跨项目、无归属/terminal Task 拒绝 |
| D 版本 | 合法 supersession 只追加；跳版、旧 supersedes、相同版本新内容拒绝；旧原 key 重试仍返回原结果 |
| E 豁免 | 当前豁免阻止声明；先移除后可声明；声明后新旧配置入口均不能再加豁免；旧质量轮次不自动采用新 Policy |
| F 持久要求 | 换 owner/Binding/epoch、返工、质量 Policy 更新、旧版本请求不能降级；其他未声明 Task 保持原行为 |
| G 无能力 | 合格 git.merge 请求 ENFORCEMENT_UNAVAILABLE；缺声明/错引用得到对应拒绝；伪造 ready 描述、结果、状态不能放行；0 Action、0 Git/Runner/Provider/网络调用 |
| H 旧 API | 通过 CommandHandler、CollaborationService、ExecutionService、GovernanceService、AcceptanceService、TaskQualityService 与新服务逐一尝试绕过；旧实例、省略新 metadata 和已有缓存同样拒绝 |
| I 旧执行 | tool.request 请求 git/shell 仍拒绝；不允许通过旧 status patch、execution.report 或恢复/requeue 把 Task 推到成功态 |
| J Replay 篡改 | receipt/actor/address/digest/version/schema/context/record/rejection/计数缺失或变化拒绝；Project record 删除 registry、legacy schema 伪造豁免/完成拒绝；失败不推进 State/cursor |
| K 并发 | 两个独立进程共享数据库：同 Project revision 竞争、声明与豁免配置、声明与完成（两个确定提交顺序）、Task revision 在声明前变化；验证真实事务结果而非本机锁 |
| L 原子/重试 | 注入事务写入失败、提交后响应丢失、进程中止后重开；原 key 只产生一次领域效果；合法 rejection 可重放且无部分配置 |
| M 兼容 | 新样例完整库/events-only 每个前缀；所有已接受历史库逐前缀；库 SHA256 保持；显式执行/I/O/时间/authority 守卫零调用 |
| N 状态边界 | 从未宣称 Integration 成功；未声明固定文档原质量链仍可合法完成并退役执行权；candidate-only/PAUSED/终止态规则维持 |

验收组织为四项限定能力：版本化权威声明、互斥与全入口关闭、事务/因果/Replay 完整性、旧行为兼容。独立复核只可接受这四项前置能力，不可据此接受原 M3-02 的任一完整条件。

规范影响映射：§7.3/§10.6、INV-004/INV-017 关联质量门；§14.1–14.2 关联 Command/事务；§13.9/§14.4 关联执行边界；TEST-001/005/017/018 为局部事务/Replay 关联，TEST-009/024 为后续真实 Integration 关联。TEST-010/028 仍完全未被本批验收；映射本身不改变 registered/passed 计数。

## 10. 拟实施写集、证据与交接

以下为需在实施计划中登记的拟写集，不表示本文已经修改它们：

- 新增 `src/aetp/integration/`（上述模块与包入口）。
- `src/aetp/domain/models.py`：登记限定 Command/Event 词汇，不放宽任意状态迁移。
- `src/aetp/core/commands.py`：共同事务守卫、地址/schema 接线；`src/aetp/core/projection.py`：因果、交叉不变量、缓存与完整库验证接线。
- `src/aetp/quality/` 仅为共享守卫调用/文档解释所必需的窄改；不改旧质量算法和历史 schema。优先由共同入口拦截配置/完成，不在各服务复制规则。
- `tests/m3/test_integration_contract_*.py`、专用 support/scenario；必要时给既有回归添加防绕过覆盖。
- `Docs/superpowers/plans/2026-09-16-m3-02-integration-input-contract.md`（纯输入切片；完整契约另行细化）、本设计及独立的新 `Docs/development/evidence/2026-09-15-m3-02-integration-*`、`artifacts/m3-02-integration-contract-*`。
- 后续协调完成后才更新 `backlog.json`/`status.json` 的批次信息与文件范围，MEMORY 仅追加。原工作项三条件、done 计数、Conformance 与产品状态不变。

本轮实际写集仅为本设计、新设计检查报告及 stdout/stderr；项目要求的 render/check/preparation 会刷新既有准备报告。不写产品代码、共享 backlog/status 或历史 MEMORY，不创建/提交 Git。当前无 ClaudeLink 工具，不虚构协调消息；未派新代理。独立复核尚未进行。

实施前重新核验基线、live 写集及是否有其他 Agent 修改；范围冲突先协调，不覆盖他人工作。记录每条 RED/GREEN/回归的实际 argv、cwd、带时区起止时间、退出码、原始输出与运行前源码 blob；失败标签不可重用，候选与正式接受分开保存。候选生成后再交不同 Agent 复核；没有独立复核不能宣称 accepted/done。

最低回归：M0/M1/M2/M3 既有测试、新声明/边界/并发/重放用例；项目收尾仍执行 `python tools/devprep.py render`、`python tools/devprep.py check`、`python -m unittest discover -s tests/preparation -v`。静态设计检查和准备测试不是本批功能 GREEN。

## 11. 文档自查与下一步

作者自查应覆盖：是否存在空缺段落、含糊许可、声明与证明混淆、当前/历史 Policy 混淆、过期变豁免、旧入口或 Projection 漏接、跨聚合竞争遗漏、未实施却写已通过。作者自查不冒充独立审查。

本方案明确保留的限制：要求不可在本批撤销；只有固定文档 Task 的需求声明；无 Git 对象存在性/分支保护/系统测试证明；没有真实外部效果恢复或自主 Agent 链。未来解除这些限制必须另行设计和验收，不靠配置开关升级声明可信度。

09-15 原下一步为详细设计复核与分步计划；09-16 用户继续请求后的实际执行见 §12。本文不把范围同意、继续请求或作者自查等同于独立设计/实现验收。

## 12. 2026-09-16 执行切片与自查补记

本次继续请求按已宣布的 inline TDD 执行，不重复询问执行模式。首切片新增 `integration/validation.py`（纯载荷校验）和固定 `contracts.py` 界限；尚不接线 Command、Event 或 State。实现与用例、运行前 blobs、原始日志见 `Docs/superpowers/plans/2026-09-16-m3-02-integration-input-contract.md` 及 `Docs/development/evidence/2026-09-16-m3-02-integration-input-*`。§10 的“本轮实际写集”描述的是 09-15 设计轮，09-16 写集以新计划为准。

作者自查报告：`Docs/development/evidence/2026-09-16-m3-02-integration-input-design-check-v1.json`。修正摘要表示、字符/字节界限以及日期引用；未修改主规范。完整 A–N 矩阵中，只有 C 的静态输入部分在本切片实现，其余保留未实现，不能依据本次单测放行任何合并。独立审查尚未发生。
