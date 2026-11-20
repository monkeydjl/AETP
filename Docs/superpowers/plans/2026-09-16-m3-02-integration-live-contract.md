# M3-02 Integration 真实声明与关闭式请求 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans. 用户要求沿用当前执行者，不启动新 Agent。

**Goal:** 闭合真实 human_owner 声明、原子双 revision、独立因果 Projection 与恢复；git.merge 只有 typed rejection。
**Architecture:** IntegrationContractService 继承 TaskQualityService，复用共同 writer/resource gate 和 InputAuthority；确定性 records.evaluate 同时用于 live 和独立 reducer。IntegrationCursor 保存不可变 receipt/终结集合，所有检查后与 State 一起发布。
**Tech Stack:** Python 3.14.6/std lib、SQLite；无依赖安装或外部调用。
**Spec:** Docs/superpowers/specs/2026-09-15-m3-02-integration-contract-design.md，尤其 §§4、6、7、9。

## Global Constraints

- Command → Event Store → Projection；不写权威 State，不从历史 JSON 制造 live capability。
- 声明只提升 Project revision；Task 完整 revision 在同一最终 writer 读取，禁止自动获取作者 Session。
- 当前 owner、当前配置 authority、真实 receipt 对象身份；过期要求不恢复豁免。
- git.merge 只拒绝，绝无 Provider/Runner/Action、成功/冲突/UNKNOWN 或四种 Integration 状态。
- 新注册与因果/reducer/共同守卫/恢复一次闭合，不留测试开关或 bypass。
- 无 Git 目录；就地执行，不初始化/commit/push。旧证据不可覆盖，MEMORY 只追加；backlog/status/主规范不改。
- ClaudeLink 不可用；原 reviewer 不可寻址，作者验证不能替代独立复核。M3-02 in_progress。

## 写集

新增 src/aetp/integration/service.py、causality.py、projection.py、requests.py。
修改 integration/contracts.py、guards.py、README.md；domain/models.py、core/commands.py、core/projection.py。
新增 tests/m3/integration_live_support.py、test_integration_live.py、test_integration_live_replay.py、test_integration_live_concurrency.py。
旧输入/guard测试只在显式注册边界断言确需随本切片演进时更新，不删减非法 envelope/纯计算测试。
新增独占 2026-09-16-m3-02-integration-live-* 证据和 artifacts/m3-02-integration-live-report-v1.json、本计划、MEMORY 追加。

## Task 1: 真实受理与独立声明回放

Interfaces: IntegrationContractService.handle(command, authenticated_actor_id=..., session=None, input_receipt=None);
IntegrationCursor.advance(event) 返回新游标；reduce_record(event, previous, state) 重算完整记录；validate_command_effect(event, command) 验证完整库原始 Command。

- [x] 新增真实 SQLite/真实 Command 和 receipt 用例；缺 API assertion RED，不用 DraftCommand 冒充真实历史。
- [x] RED 场景：正确声明只改 Project、版本追加；错误 actor/owner/来源/复制 receipt；双 revision；typed rejection/旧入口拒绝；幂等重试与完整库 pending。
- [x] 新增 exact-envelope/receipt 地址、revision、digest、correlation、effect 0/1、bool/int、历史重签、重复终结/错误 rejection、无 schema/未知 schema、所有五游标原子发布的回放 RED。
- [x] 实现 service/cursor/reducer 和拒绝型 merge 检查；仅精确重算的合法声明可通过 Project 子资源单版本追加守卫，非专属事件仍保持完全相同。
- [x] 闭合模型枚举、共同审计地址、Projection/apply/pending-command 路径，再运行 targeted GREEN。旧 schema 拒绝测试仍拒绝所有非法 envelope；不能从 mere event name 放行。

## Task 2: 事务、并发、恢复与兼容

- [x] 测试真实 SQLite Event/result 回滚及原 key 重试、关闭重开与纯 events-only/full-store recovery；禁止 runtime/clock/authority 调用的纯回放。
- [x] 两独立进程：同 Project revision 声明竞争、声明与豁免配置竞争；Task revision 先提交变化后声明拒绝。测试明确区分进程与线程。
- [x] 完成/声明顺序以真实前缀测试，quality compound 中途不能插入声明。含声明的 cache 必须从事实重建。
- [x] 验证新历史每个前缀；复验旧不可变样例数据库逐前缀（若无法实际复验，则明确报告范围/缺口）。

## Task 3: 作者审查与证据

- [x] 对照设计检查没有引入成功合并或回放外部调用；记录 RED/GREEN 与夹具修正。
- [x] 串行 M0/M1/M2/M3 全套、render/check/preparation；报告实际计数/退出码，不叠加 targeted 重复测试。
- [x] 核验旧1067映射/505blobs/6pins和非写集；独占报告、handoff、作者自查、MEMORY追加；独立复核 pending。
- [x] 文档后 render/check/preparation 与收尾完整性核验；不提高整体接受状态。

后续仍需独立复核、真实 Integration Provider/系统 Verification、Mission Acceptance、真实双 Agent 自主交付与 TEST-028；本批不声称完成这些。
