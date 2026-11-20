# M3-02 Integration 独立复核输入计划

> 使用 executing-plans / verification-before-completion。仅继续既有已实现契约的证据交接，不实现新产品行为，不启动新 Agent。

**Goal:** 冻结四个 Integration 契约切片，提供真实持久化样例与只读回放材料。
**Architecture:** 复用 QualityScenario 的确定性本地身份与现有 IntegrationContractService；Command → SQLite → Projection，不修改 src/tests。
**Tech Stack:** 当前 Python / stdlib / SQLite；不联网、安装或初始化 Git。
**Spec:** Docs/superpowers/specs/2026-09-15-m3-02-integration-contract-design.md。

## 范围与边界

- 工作项 M3-02，依赖 M3-01 done；交接对象用户与原 reviewer（当前不可寻址）。
- 新增 Docs/development/evidence/2026-09-17-m3-02-integration-review-inputs*、artifacts/m3-02-integration-demo-v1*、本计划；MEMORY 只追加。
- src/tests/backlog/status/主规范/旧证据不可改；只有 devprep 的五个派生 JSON 可重新生成。
- git.merge 仍仅拒绝；无 Provider、成功合并、UNKNOWN、系统 Verification 或新阶段迁移。
- SQLite 样例为开发证据，不是独立复核、双 Agent 自主交付或 Conformance。
- M3-02 in_progress；完整 M1 not_accepted；产品0/Bootstrap not_started/Conformance28 registered0passed。

## Task 1: 冻结与持久化样例

- [x] 校验上一收尾/源码快照和1067旧映射、505blobs、6pins；记录所有原文件哈希。
- [x] 独占 SQLite 样例复现 owner receipt 声明、版本追加、双revision拒绝、幂等、无/旧/当前声明merge拒绝、旧完成/豁免入口；比较Project以外对象不变。
- [x] 仅复制commands/events到facts-only数据库；逐前缀incremental/rebuild与events-only State一致；两个含commands的库pending一致；冷恢复只读，具名外部依赖零调用。
- [x] 回读样例并在冻结源码独立进程复验；记录真实输入/输出/返回码，不冒充独立Agent。

## Task 2: 复核交接

- [x] 串行重跑M0/M1/M2/M3与准备检查；保留失败日志，不把重复测试计为新增方法。
- [x] 固定候选包、四切片证据索引、复现命令、限制及reviewer检查清单。
- [ ] MEMORY追加、文档后render/check/preparation；核验旧证据与记忆前缀。

后续真实Integration Provider、外部效果恢复、系统Verification、Mission Acceptance与TEST-028需另行设计/授权/验收。
