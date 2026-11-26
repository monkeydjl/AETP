# 2026-11-26 M4-01 Bootstrap 验收材料（供人类 CRITICAL 签字）

> 本文档为签字准备材料，**不改变任何工作项状态**，也**不构成验收通过**。
> M4-01 当前仍为 `blocked`；`bootstrap_status` 仍为 `not_started`；`phase` 仍为 `preparation`；
> `product_completion_percent` 仍为 `0`。
> 本文档只做一件事：把 B0–B5 的真实现状摊开，让你在签字前不必自己去翻 8 份证据文件。

## 0. 为什么需要你签字

`Docs/AETP-设计方案.md` §9.4 / INV-019 要求 Bootstrap Acceptance 由 **CRITICAL 人类验收**产生。
AI 代签即等同伪造签章，因此这一步无法在仓库内部完成。

以下三条**不能**由我代办，也已写进 `M4-01.block_reason`：

| # | 阻塞项 | 性质 |
| --- | --- | --- |
| 1 | CRITICAL 人类验收（§9.4 / INV-019） | 只有你能签 |
| 2 | `mission.verify` 的 criteria 仍是 runner 自报 | 产品能力缺口，非文档问题 |
| 3 | 知识图谱是静态开发索引，非协议运行 B3 构造 | 产品能力缺口 |

## 1. B0–B5 逐项实况

证据目录：`Docs/development/evidence/2026-10-09-m4-01-*.json`

| 阶段 | 断言 | 真实现状 | 证据文件 |
| --- | --- | --- | --- |
| B0 Environment | 环境事实来自真实命令输出 | **passed** — Windows 10 / AMD64 / 24 CPU / Python 3.14.6 / Node v24.18.1 / git 2.54.0 / Go 1.26.5 / uv 0.12.5 / Docker 29.2.1 | `b0-environment-profile.json` |
| B1 Architecture | 技术选型 | 已记录选型依据 | `b1-technology-selection.json` |
| B2 Environment | 红线与 git 初始化 | **passed** — `git init` 已完成，`git rev-parse --is-inside-work-tree` → true | `b2-environment.json` |
| B3 Knowledge | 知识图谱可验证 | **passed_partial** — 101 节点 / 144 边 / 无环，由 `devprep.py check` 校验；但这是**静态开发索引**，不是协议运行 B3 构造出来的 | `b3-b4-infrastructure.json` |
| B4 Build | 编译与 import 冒烟 | **passed** — `compileall` exit 0；import 冒烟通过。**无构建步骤**，从源码以 `PYTHONPATH` 运行 | `b4-build-verification.json` |
| B5 Bootstrap | 六项验证 | 见下节 | `b5-bootstrap-acceptance.json` |

## 2. B5 六项验证（原始结论：`NOT_VERIFIED`）

原始证据的 `verification_matrix`：

| 项 | 结果 | 说明 |
| --- | --- | --- |
| environment | passed | 见 B0 |
| dependency | passed | 仅标准库，零第三方依赖 |
| build | **blocked** | 无构建步骤（从源码运行） |
| test | passed | preparation 27 / conformance 28 / fault injection 15 / runtime adapter 11 |
| git | passed_partial | `git init` 完成；当时未提交、未推送 |
| knowledge | passed_partial | 静态图谱，非协议构造 |

聚合结论：`result = "NOT_VERIFIED"`。

### 2.1 原始证据的四条阻塞理由，与今日实况对照

**这是本文档最需要你注意的部分**：原始证据写于 2026-10-09，部分理由已随本会话工作失效，
但**失效并不等于验收通过**。

| # | 原始阻塞理由 | 今日实况 | 是否仍阻塞 |
| --- | --- | --- | --- |
| 1 | 「build/CI/lint step does not exist (no remote repo, no CI service, no pinned lint tool)」 | **CI 已失效该理由**：remote 已配置，`ci.yml` 真实跑通（run 45205671826，`windows-latest`，28 passed / 0 failed）。**lint 仍未安装**（ruff 不存在，产品零依赖） | CI 部分：否；lint 部分：**是** |
| 2 | 「knowledge graph is a static dev-prep index, not constructed by the protocol running B3」 | 未变，仍为静态索引 | **是** |
| 3 | 「the protocol cannot run Mission #0 itself — product-capability gap」 | 部分改善：新增受控证据命令 `artifact.observe`，使 B5 可诚实产出证据（见 `2026-11-11-b5-bootstrap-evidence-command.json`）。但 `criteria` 仍是 runner 自报的 B0..B5 名称，**未真实测量** | **是** |
| 4 | 「CRITICAL human acceptance cannot be produced in this environment」 | 未变，需要你 | **是** |

### 2.2 关于第 3 条的代码级依据

`src/aetp/bootstrap/runner.py`：

- `L311` — 自行遍历 `criteria` 列表
- `L317-318` — 观测内容由 runner 自己构造（`"recorded_by": "a-1"`、`"bootstrap_evidence": env_evidence`）
- `L333` — `"result": "PASSED"` 由 runner 自己写死

`artifact.observe` 保证的是「谁记录的、摘要由服务端现算」，
**不保证该 criterion 被真实测量过**。这是我把本条继续列为阻塞项的依据。

## 3. Conformance 的真实覆盖范围（务必在签字前查看）

`Docs/development/status.json` 的 `conformance.note` 明确写道：

> 28 conformance tests pass (reproducible, digest zero-drift) under a **LIMITED compatibility scope**:
> Runtime Adapter enforces a working_copy path-prefix boundary and mediated pre-tool authorization;
> real OS/container sandbox, credential isolation and network egress allowlist remain unimplemented.
> **Complete AETP Compatible (17.4) is therefore NOT claimed.**

也就是说：**28/28 通过 ≠ 完整协议兼容**。签 B5 时不应把它读成后者。

## 4. 签字前需要你逐项确认的判断

以下每一条都不是我能在仓库内替你回答的：

1. **是否接受 `build = blocked`**（无构建步骤，从源码运行）作为 B5 的合格状态。
   若接受，请明确这是「N/A 而非失败」的判定。

2. **是否接受 `knowledge = passed_partial`**（静态图谱）。
   原始证据把「非协议构造」列为阻塞，若你要放行，等于承认该条在 B5 阶段不适用。

3. **是否接受 `git = passed_partial`** 的现状：
   现已远超当时（有 26+ 提交、已推送 remote、CI 已跑），但**证据文件仍是当时写的**，
   我没有回填旧证据文件（那会篡改历史记录）。是否需要一份新的 git 现状证据？

4. **`mission.verify` 的 criteria 仍自报**（第 3 条）。
   这是产品能力缺口。你签字时是接受「B5 通过但该缺口随后续工作闭合」，
   还是要求先闭合再签？

5. **Conformance 的 LIMITED scope** 是否满足你对 B5 的预期。

## 5. 我不会做的事

- 不会把 M4-01 改为 `done` 或 `passed`。
- 不会写入 `bootstrap_status = verified`。
- 不会改动 `status.json` 的 `product_completion_percent`。
- 不会回填/重写任何历史证据文件使其「看起来通过」。

以上任何一项都只在你明确指示后进行。

## 6. 相关文件索引

| 类别 | 路径 |
| --- | --- |
| 工作项 | `Docs/development/backlog.json` → `M4-01` |
| 正式状态 | `Docs/development/status.json` |
| B0–B5 证据 | `Docs/development/evidence/2026-10-09-m4-01-*.json`（8 份） |
| 协议改造证据 | `Docs/development/evidence/2026-11-11-b5-bootstrap-evidence-command.json` |
| 已知缺口登记 | `Docs/development/evidence/2026-11-11-b5-known-gap-registration.json` |
| 自举复核 | `Docs/development/evidence/2026-10-09-m4-01-self-bootstrap-review.json` |
| CI 运行记录 | GitHub run `45205671826`（`windows-latest`，28/28） |
