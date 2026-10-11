---
name: aetp-evidence-handoff
description: Use when splitting AETP work, taking over a backlog item, reporting progress, reviewing acceptance evidence, or handing a change from one Agent to another.
---

# AETP 证据、进度与交接参考

本 Skill 约束报告形状，不能把计划、静态检查或 Agent 自述变成产品验收。规范入口是 `AGENTS.md`、`Docs/development/backlog.json` 和 `Docs/development/knowledge-map.md`。

## 状态与证据

| 状态 | 意义 |
| --- | --- |
| `todo` | 已登记，当前不可直接开始或尚未排队 |
| `ready` | 依赖满足，可协商接手；不保证环境/权限 |
| `in_progress` | 执行者、范围与输入已确认 |
| `review` | 产物已有，等待不同 Agent 独立复核 |
| `done` | 验收证据、复现命令、退出码和独立复核齐全 |
| `blocked` | 有明确阻塞事实和解除条件；不等于成功 |

`planned`、`implemented`、`verified`、`accepted` 是证据层级，不可互换：实现完成不等于验证通过，验证通过不等于人类/任务验收。


## 开发准备字段来源与规范定位

开发准备报告中的状态字段必须能回到单一来源，不能凭口头进度推断：

| 字段/判断 | 来源 | 约束 |
| --- | --- | --- |
| 工作项状态、依赖、文件写集、验收条件 | `Docs/development/backlog.json` | `todo → ready → in_progress → review → done`；`done` 必须有验收证据、复现命令、退出码和不同 Agent 复核 |
| 里程碑统计与准备摘要 | `Docs/development/status.json`、`tools/devprep.py render` 生成的 `preparation-report.json` | 全计划按里程碑统计；PREP 准备口径取 `milestones.PREP`，不计作产品完成度 |
| `product_completion_percent` | `Docs/development/status.json` | 准备阶段保持 `0` |
| `bootstrap_status` | `Docs/development/status.json` | 准备阶段保持 `not_started`；没有 Bootstrap Acceptance 不得写 `BOOTSTRAP_VERIFIED` |
| Conformance | `Docs/AETP-设计方案.md` 的 TEST 登记与产品执行报告 | 只有登记是 `registered`；没有真实执行证据不能写 `passed` |

原始规范的验收入口：§§15.5（Bootstrap Mission/Acceptance）、17.2（M0 五对象与模拟 Runtime 边界）、17.4（v0.1 兼容范围）、18.2（故障注入）、18.3（TEST 是待执行验收要求）。对应压力场景至少覆盖 `TEST-010`、`TEST-012`、`TEST-028`，并明确静态资料检查不替代产品行为证据。
## 交接卡片（必须完整）

```text
工作项：<ID>；状态：<状态>
目标/范围：<不做什么也写出>
修改文件：<路径>
输入与依赖：<ID、规范章节、决策>
已运行：<命令>；退出码：<n>；时间：<ISO-8601>
证据：<报告、日志、fixture、commit；没有就写 none>
未覆盖：<失败场景、权限、环境、外部效果>
独立复核：<不同 Agent/未完成则写 pending>
下一步：<一个可执行动作>
```

只按已完成工作项计算进度；Conformance 另行统计。28 条 TEST 写入文档只表示 `registered`，没有执行报告不能写 `passed`。五对象 M0 模拟通过也不能写 `BOOTSTRAP_VERIFIED` 或完整成果验收。

## 接手前检查

先确认依赖状态、文件写集、未提交改动、规范来源和验收命令；与其他 Agent 协商后再改共享清单。`backlog.json` 是计划文件，不是跨进程原子 Lease 服务。若无法获得不同 Agent 的复核，保持 `review`，不要自评为 `done`。

## 常见误报

- “测试条目存在” ≠ “测试通过”。
- “脚本 exit 0” ≠ “产品行为符合协议”。
- “实现好了” ≠ “有 Artifact/Review/Verification/Acceptance”。
- “Manager 汇总过” ≠ “平等 Agent 直接协作已验证”。
- “本机进程锁” ≠ “跨进程认领安全”。

