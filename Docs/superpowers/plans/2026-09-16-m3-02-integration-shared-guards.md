# M3-02 Integration Shared Guards Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. No new agents; independent review stays pending.

**Goal:** 接入默认关闭的共享提交/Projection 守卫，阻止 required Task 经旧路径获豁免/完成，并保护声明历史；本切片不登记声明或 git.merge。

**Architecture:** 从已批准 Integration 设计拆出共同安全边界。纯历史校验器从现有 records._history 提取，CommandHandler 在 writer 事务内、幂等查询后、领域求值前调用 command_error；Projection 在领域求值前后检查，并保持原子发布。既有前缀缺少 integration_contract 时不注入默认状态。

**Tech Stack:** Python 3.14.6 / stdlib unittest / SQLite；不安装依赖、不联网。

**Spec:** `Docs/superpowers/specs/2026-09-15-m3-02-integration-contract-design.md` §§5–8；主规范 §§7.3、10.6、14.1–14.2、13.10。

## Global Constraints

- Command → Event Store → Projection；不直接写权威 State。
- required 历史不因 owner/Binding/epoch/Policy 变化而撤销；无声明不等于豁免。
- 最多64 Task ×64版本；历史字典键为连续规范十进制字符串。
- 不实现四种 Integration 成功状态、真实 Git/Provider/Runner、Action 或 UNKNOWN。
- 同键同内容优先返回旧结果；同键异内容 IDEMPOTENCY_CONFLICT；actor mismatch 优先拒绝。
- 当前非 Git 仓库，用户已确认就地推进；不初始化/commit/push。不改 backlog/status/主规范；MEMORY 只追加。
- ClaudeLink 不可用；不声称已协调/独立评审。交接对象为用户和后续独立复核者。

## 范围、依赖与影响

依赖 M3-01 done、已接受的质量/Verification 切片和作者验证的输入/声明记录切片。现有记录器报告 hash 已核验。这个切片对应设计 E/F/H/I 的守卫子集，不等于完成 A–N 或真实双聚合 CAS。

实际 live 前缀目前不能包含新声明：Command/Event 均未注册。正向来源/receipt、声明因果游标与 reducer、完整库恢复接线必须在后续闭合后才能登记。测试使用 records.evaluate 产生的**合成候选快照**验证守卫数据逻辑，明确不是已接受 Event 历史。共享事务位置测试以真实旧前缀/真实 SQLite 拒绝审计为基础，对边界决策做故障注入；不能宣称跨进程声明竞争已验证。

写集：新增 `src/aetp/integration/history.py`、`guards.py`；修改 `records.py`（等价提取）、`README.md`、`src/aetp/core/commands.py`、`projection.py`；新增 `tests/m3/test_integration_shared_guards.py`、`test_integration_guard_wiring.py`；新增独占 `2026-09-16-m3-02-integration-guard-*` 证据、`artifacts/m3-02-integration-guard-report-v1.json`、本计划及 MEMORY 追加。

## Task 1: 纯历史和防绕过守卫

**Interfaces:**
- `validated_history(project) -> dict | None`：缺键返回 None；存在时校验现有结构/摘要并返回深副本；畸形 INVALID_REFERENCE。不是全历史因果验证。
- `command_error(command, state) -> str | None`：只处理 `project.task_quality.configure`、`task.complete`、`task.quality.complete`，其余 None。
- `validate_fact(event, state) -> None`：required 的 exempted/completed 拒绝。
- `validate_record(event, previous, updated, state) -> None`：Project 声明 key 的存在性与规范 JSON 必须不变；所发布的当前 Policy 豁免不得与 required 相交；Task 不得进入四种未实现状态或 required completed。

冻结错误顺序：共享旧 planning/reserved-artifact gate 保持优先；对三种守卫命令，先确认当前 Project 的声明结构（畸形 INVALID_REFERENCE）。没有声明则完全委托既有处理，不提前重写旧 payload 错误。存在声明时 configure 先校验完整载荷形状/全部条目，再判断交集 INTEGRATION_SCOPE_CONFLICT。scope 不支持保持 INTEGRATION_SCOPE_UNSUPPORTED，重复 Task 保持 INVALID_REFERENCE。complete 命中 required 直接 INTEGRATION_REQUIRED；其余权限/revision/业务条件委托原 evaluator。unknown 命令不获得新权限。

本阶段 Project 声明的新增/修改一律拒绝，即使 Event 自称 integration_declared；后续真实 reducer 实现时才能限定允许经重算的单版本追加，不能先加 bypass 开关。

- [x] 新增纯守卫测试：缺失 API 明确 assertion RED；历史结构、快照过期不撤销、全载荷校验优先、canonical bool/int、深副本与无副作用。
- [x] 运行 `python <recorder> pure_red_v1 -m unittest tests.m3.test_integration_shared_guards -v`，预期 assertion failure，非 ImportError。
- [x] 提取 `_history` 结构校验；实现纯守卫。核心模式：

```python
history = validated_history(project)
required = frozenset() if history is None else frozenset(history['tasks'])
if command.type in {'task.complete', 'task.quality.complete'}:
    return 'INTEGRATION_REQUIRED' if command.target_id in required else None
```

- [x] 跑新纯模块与旧31记录/26输入测试 GREEN。

## Task 2: 共享事务与原子 Projection 接入

**Interfaces:** 原有 `CommandHandler.handle`、`Projection.apply`、`Projection._from_cache` 保持签名；新增守卫在所有 Service 的共同基础入口内执行。

- [x] 增加 RED 测试：真实 SQLite 各旧 Service 共同 gate；调用时 in_transaction=True 且 state 来自当前事实；拒绝无 `_evaluate`/领域变化；原 key 重试和 actor/conflict 不再调用 gate；事务故障回滚全部事实与结果。
- [x] 增加 Projection RED 测试：无 integration_schema 也运行 pre/post 守卫，故障不发布 State/sequence/seen/已有四游标；后续同事件可重试。合成候选状态仅用于白盒守卫测试。
- [x] 增加 reserved schema 和 cache 测试：所有 audit/domain 中 integration_schema 仍拒绝（尚未接入）；integration_contract key 存在即禁止无游标 cache continuation，包括空/null。
- [x] `python <recorder> wiring_red_v1 -m unittest tests.m3.test_integration_guard_wiring -v`，查看真实预期失败。
- [x] 最小接入：

```python
# inside writer, after idempotency and preexisting gates
if not planning_error and command.type in INTEGRATION_GUARDED_COMMANDS:
    planning_error = integration_command_error(command, Projection.rebuild(self.store.read_events(command.project_id)))
# Projection: before reduction
integration_validate_fact(event, self._state)
# after derivation, before any cursor/state publication
integration_validate_record(event, self._state.get(key), updated, self._state)
```

- [x] 跑 wiring GREEN；不得修改 domain models/新命令注册、服务或 store。

## Task 3: 回归、证据与交接

- [x] 作者自查：没有 acceptance/命令入口提前开启；原历史保持；失败是模型异常而非中途 State 发布；不把合成数据称受理成功。
- [x] 顺序执行 `python -m unittest discover -s tests/m0 -v`、m1、m2、m3；最后 `python tools/devprep.py render`、`check`、`python -m unittest discover -s tests/preparation -v`，全部经独占 recorder 留档。
- [x] 验证1067旧映射/505 blobs/6 pins与所有非写集文件；生成只标作者验证的报告/交接，MEMORY append；独立复核 pending，M3-02 in_progress。
- [x] 文档结束后再跑 render/check/preparation。不提交 Git。

## 后续闭合接线（本计划不声称已实施）

1. IntegrationContractService 的真实身份/InputAuthority、writer 内双 revision、单声明 Event batch。
2. 独立 reducer 与专属因果游标：receipt 地址/revision/digest、exact envelope、拒绝终结、原子发布；精确重算后才许可 Registry 单版本追加。
3. 全库/纯 Events/待终结检测/cache 恢复、冻结历史逐前缀对比与跨进程 CAS。
4. 所有上述路径测试通过后才同步登记 declaration 和拒绝型 git.merge；后者缺声明 REQUIRED、错引用 STALE、其余 ENFORCEMENT_UNAVAILABLE。
5. 独立复核；真实 Integration/Mission/TEST-028 仍另行交付。
