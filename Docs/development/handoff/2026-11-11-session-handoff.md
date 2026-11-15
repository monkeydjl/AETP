# 2026-11-11 会话交接：B5 证据链加固 + 受控证据命令 + 隔离探针修正

> 本文档只描述状态与证据，不改变任何工作项状态，也不等同于验收通过。
> 所有改动留在工作区，**未提交**。

## 1. 工作项状态

| 工作项 | 状态 | 说明 |
| --- | --- | --- |
| M4-01 Project Bootstrap 正式验收 | `blocked` | 卡在真实 CI remote + CRITICAL 人类验收（§9.4 / INV-019），外部资源 |
| M4-03 整里程碑验收与 product_completion | `blocked` | 同上；隔离等级口径经用户确认保持 fail-closed |
| 其余 21 项（PREP / M0 / M1 / M2 / M3） | `done` | 本轮未改动其判定 |

`product_completion_percent` 仍为 `0%`——只计 `done` 且需独立复核的正式验收项。

## 2. 本轮实质改动

### 2.1 `mission.verify` 证据不可伪造（`src/aetp/acceptance/mission.py`）

- 证据只认投影中的 `artifact:<id>`，不采信载荷自报。
- artifact 不存在 / 项目不符 / digest 不符 → `EVIDENCE_STALE`；空 digest → `INVALID_PAYLOAD`。
- PASSED 由 artifact 自身 `created_by` 提交 → `EVIDENCE_STALE`（自评不算独立验证）。
- 闸门未放宽：`tests/m3/test_mission_evidence_integrity` 12 条全绿。

### 2.2 新增受控证据命令 `artifact.observe`（acceptance 域）

- 终端事件 `artifact.observed`；载荷严格限定 `{content, observer_note}`。
- 作者恒为已认证 Agent；digest 服务端现算、不可覆盖；同一 id 不可重复观测（`REVISION_CONFLICT`）。
- **不依赖 Runtime Session/Task**——B5 阶段本就无 Task，这是它与 `artifact.capture` 的本质区别；但仍绑定项目与真实观测字节。
- 用例：`tests/m3/test_artifact_observe.py`（9 条）。

### 2.3 bootstrap runner 与夹具接入真实证据

- `src/aetp/bootstrap/runner.py`：B5 先由 a-1 真实观测，再由 a-2 用其真实 digest 调用 `mission.verify`。
- 受影响夹具同步改走真实证据：`tests/bootstrap/test_lifecycle.py`、`tests/m3/test_mission_acceptance.py`、`conformance/m3/test_028.py`、`tests/conformance/test_runner.py`。
- 上一轮登记在 `Docs/development/evidence/2026-11-11-b5-known-gap-registration.json` 的 11 处 `expectedFailure`/`skipped` **已全部摘除**；TEST-028 恢复 28/28。

### 2.4 隔离探针越界判据修正（`tests/conformance/test_isolation_probe.py`）

- 旧判据拿容器内 `/outside_escape` 判“越界”——该路径在任何容器自己的根文件系统里都可写，证明不了任何边界。
- 新判据：probe 根目录只读挂载、越界目标改指**宿主路径**、真相由**宿主侧**检查（canary 是否出现）。
- 结论更正：Docker 实际可达（`ServerVersion 29.2.1`），先前的 `docker_daemon_unreachable` 结论是错的。
- 复测：`os_sandbox` 实测 `observed=true`（越界写入 denied、宿主无 canary、work 写入 allowed 且宿主可见）。

### 2.5 其他已在本轮前落地的改动（同在未提交工作区）

`src/aetp/governance/{credential_broker,credentials,service}.py`、`src/aetp/runtime/{adapters,records}.py`、`conformance/{definitions,runner}.py`、`tools/devprep.py` 及对应测试——属更早的 M1–M3 切片，本轮未回退。

## 3. 证据路径

| 证据 | 路径 |
| --- | --- |
| B5 受控证据命令落地 | `Docs/development/evidence/2026-11-11-b5-bootstrap-evidence-command.json` |
| 已知缺口登记（已被 2.3 消解，保留作历史） | `Docs/development/evidence/2026-11-11-b5-known-gap-registration.json` |
| mission 证据完整性 | `Docs/development/evidence/2026-11-11-b5-mission-evidence-integrity.json` |
| 隔离探针复测 | `Docs/development/evidence/2026-11-11-isolation-probe-remeasured.json` |
| 容器隔离缺口（M4-03） | `Docs/development/evidence/2026-11-09-m4-03-container-isolation-gap.json` |
| 探针可被收集 | `Docs/development/evidence/2026-11-10-isolation-probe-collected.json` |

## 4. 复现命令与退出码

```bash
# 全量回归（PYTHONPATH 必须带 "src;."）
cd /d/Github/AETP
PYTHONPATH="src;." python -m unittest discover -s tests -t .
# => exit=0, Ran 1036 tests, OK

# 仓库自洽检查
PYTHONPATH="src;." python tools/devprep.py check
# => exit=0, OK graph nodes=101 edges=144; backlog items=23; skills=3; acyclic=yes;
#    status phase=preparation product_completion_percent=0%

# 隔离探针单跑
PYTHONPATH="src;." python -m unittest tests.conformance.test_isolation_probe
# => Ran 4 tests OK
```

注意：**不要用 pytest**，本仓库只用 `unittest`；漏掉 `PYTHONPATH="src;."` 会产生 85 个导入错误。

## 5. 未覆盖风险

1. **`mission.verify` 的 criteria 仍是 runner 自报项**：证据的 artifact 是真实的，但“哪些 criterion 算达成”由 runner 填写，没有独立审查者。正式验收仍欠这一环。
2. **`artifact.observe` 不强制 Runtime Session**：这是为 B5 无 Task 场景做的取舍；非 bootstrap 场景是否应要求 Session 绑定，尚未定论。
3. **`os_sandbox` 已实测但两处风险未关闭**：整里程碑验收未做；超过一次容器运行、网络/进程越界的覆盖面未扩。用户决定口径保持 fail-closed，故不计入资格。
4. **M4-01 / M4-03 无法由 Agent 闭合**：需真实 CI remote 与 CRITICAL 人类签字。
5. **仓库状态异常（重要）**：`Docs/` 工作区 10219 个文件、`artifacts/` 172 个，而 HEAD 仅跟踪 116 / 14 个。`git check-ignore` 对本目录无命中——即约 10100 + 158 个文件是**从未入库**，不是被忽略。任何 `git add -A` 都会把它们一次性卷入提交。本轮未改 `.gitignore`，也未动其跟踪状态。

## 6. 下一步（需用户决策）

- 是否单独开一个提交批次处理 `Docs/` / `artifacts/` 的入库问题（建议与本次代码改动分开）。
- M4-01 / M4-03 所需的 CI remote 与人类验收由谁、何时提供。
- 三选一仍可继续：A 审计 M2/M3 的 `done` 判定；B 新开工作项（如隔离探针补强）；C 已在此文档收口。
