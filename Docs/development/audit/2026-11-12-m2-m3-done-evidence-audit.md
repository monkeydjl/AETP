# 2026-11-12 审计：M2/M3 四项 `done` 判定与证据对照

> 审计范围：`M2-01`、`M2-02`、`M3-01`、`M3-02`。
> 审计方式：重算 `acceptance_evidence` 中所有「路径 + SHA256」配对；核验 `evidence` 清单文件是否存在；
> 核对复核者与执行者的独立性；复跑宣称的复现命令。
> **本审计不改变任何工作项状态**，只列出发现。

## 实证结果（可复现）

复现脚本位于会话临时目录；核心逻辑：

```python
import hashlib
from pathlib import Path
got = hashlib.sha256(Path(path).read_bytes()).hexdigest()
assert got == claimed_sha256
```

| 工作项 | 钉住的 SHA256 配对 | 文件存在 | `evidence` 清单缺失 | 复跑 |
| --- | --- | --- | --- | --- |
| M2-01 | 2 对（v2 测试报告、v2 复核） | ✅ 全 OK | 0 / 15 | — |
| M2-02 | 2 对（测试报告、复核） | ✅ 全 OK | 0 / 11 | — |
| M3-01 | 2 对（测试报告、复核） | ✅ 全 OK | 0 / 11 | — |
| M3-02 | 1 对（final-review，在正文中以 `SHA256:` 内联） | ✅ OK | 0 / 56 | ✅ Ran 17 tests OK |

M3-02 的 `acceptance_evidence` 未使用「路径 SHA256」连续格式，正则未命中，但逐项核对后
`2026-09-17-m3-02-final-review.json` 的哈希与声明一致。

## 发现

### 1. 证据文件层面：充分

四项的钉住证据**全部可重算且一致**，`evidence` 清单无一项缺失。这一点比预期好——
说明当时的“固定版本 + 哈希钉住”流程确实执行过，不是事后补写。

### 2. 复核独立性：记录可核，但复核者身份不可复核

四项的 `reviewer` 均为 `/root/m1_reviewer`，`executor` 为 `Codex main agent`（M2-02/M3-01/M3-02 为 `Codex main agent /root`）。

- 记录层面**字面上满足**「复核者 ≠ 执行者」；
- 但 `/root/m1_reviewer` 是会话内的 Agent 标识，**不是可独立验证的身份**。本环境无法确认它是
  “另一个独立 Agent”还是“同一进程扮演的第二个角色”。
- `M2-02`、`M3-01`、`M3-02` 的执行者字段包含 `/root`，而复核者是 `/root/m1_reviewer`，
  两者是同一命名空间下的不同路径。严格讲这是**标识不同**，不等于**主体独立**。

**结论**：按 AGENTS.md「不得用一个 Agent 的自评伪装两个独立审查者」，现有记录没违反字面规则，
但若不接受“同命名空间下的第二个 session 标识”算独立，这四项的独立性均有疑义。

### 3. 声明范围与当前状态的一致性：存在漂移

四项的 `acceptance_evidence` **都明确写了**未涵盖的部分，摘录：

- M2-01：「No provider billing, Approval/activation, whole-M1/M2 acceptance, formal Verification or full Conformance claim.」
- M2-02：「Whole M1/M2, formal Verification, legal Task COMPLETED and full Conformance remain unaccepted.」
- M3-01：「Formal Bootstrap, Team/Blueprint activation, legal Task COMPLETED, whole M1/M2/M3 and TEST-028 remain unaccepted.」
- M3-02：无此类保留说明。

**问题**：`M3-01` 的验收证据写着 “TEST-028 remain unaccepted”，但 `M3-02`（后一项）的验收证据称
TEST-028 已「verified」，且当前 `backlog.json` 里 `M2-01` 的 `conformance_tests` 与
`M3-01` 的 `conformance_tests` 都**列入了 TEST-028**。

这不是矛盾——M3-01 完成时 TEST-028 确实未实现，后来在 M3-02 补上。但**已完成的
`M2-01`/`M3-01` 的 `conformance_tests` 字段现在指向一个当时并不存在的测试**，会让读者误以为
这两项的 done 依赖了 TEST-028。建议（不执行，只建议）在字段中区分「完成时已通过」与「事后补入映射」。

### 4. 方法层面的实际风险（比哈希更重要）

四项全部是**单元/集成测试 + 文档证据**，没有一项包含真实外部 Agent 的协商运行：

- M3-02 的 TEST-028 是 `conformance/m3/test_028.py` 里**脚本化的双 Agent 场景**；
  此前轮次已确认 `aetp.collaboration.delivery` 模块不存在，peer delivery 为未实现功能。
- 所以「两名以上平等 Agent 从粗糙想法讨论到成果交付」这一条验收标准，**当前证据支撑的是
  “系统在脚本化双 Agent 场景下能正确决策”，不是“真实两个 Agent 自主协商并交付”**。

这是四项里**唯一实质性的证据薄弱点**，且不是审查者疏忽——当时的
`scope_note` / `acceptance_evidence` 已经用 “TEST-028 autonomous equal-agent negotiation” 措辞
限定在测试范围内。只是「M3-02 done」这个状态本身容易被读成“产品已能自主交付”，而事实不是。

### 5. 与后续轮次的关系

本轮对 `mission.verify` 的收紧（证据必须是真实 artifact）**没有让上述任何一条失效**：
四项的证据都是已完成的历史快照，本轮改的是「新证据如何产生」，不是「旧证据是否有效」。

但反过来要注意：**本轮收紧后，runner 自报 criteria 仍是未解决问题**（见交接文档 §5.1）。
若日后做整里程碑验收，M3-02 的“逐条 Acceptance Verification”需要重新在收紧后的闸门下走一遍。

## 汇总判定

| 维度 | M2-01 | M2-02 | M3-01 | M3-02 |
| --- | --- | --- | --- | --- |
| 哈希钉住可重算 | ✅ | ✅ | ✅ | ✅ |
| evidence 文件齐全 | ✅ | ✅ | ✅ | ✅ |
| 复现命令仍可跑 | 未跑 | 未跑 | 未跑 | ✅ |
| 复核者独立性可验证 | ⚠️ 标识层面 | ⚠️ 标识层面 | ⚠️ 标识层面 | ⚠️ 标识层面 |
| 验收标准覆盖真实自主 Agent | — | — | — | ⚠️ 仅脚本化 |

**总体结论：`done` 判定在“文档证据可重算”意义上是站得住的，没有发现伪造或缺失；
但在“独立复核主体可验证”与“真实多 Agent 自主交付”两点上，证据不足以支撑更强的解读。**

建议将第 2、4 点作为已知缺口记录，而不是回退 `done`——回退会否认已完成工作的真实价值。
是否记录、记到哪里，由你决定。
