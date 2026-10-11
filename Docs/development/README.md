# AETP 开发准备入口

更新：2026-09-06。这里是从设计文档进入 AI 开发的单一入口。它描述**开发期资料**，不是 AETP Runtime、Event Store 或 Knowledge Graph 的运行时实现。

## 资料地图

| 目标 | 入口 | 用途 |
| --- | --- | --- |
| 项目协作规则 | `AGENTS.md` | 平等 Agent、权限边界、状态与交接约定 |
| 规范定位 | `knowledge-map.md` | 从问题定位主规范章节、实体、不变量和测试 |
| 机器关系索引 | `knowledge-graph.json` | 稳定 ID、来源、边和工作项映射 |
| 路线与进度 | `roadmap.md`、`backlog.json`、`status.json` | M0–M3 的依赖、验收和真实状态 |
| M0 首批执行 | `../superpowers/plans/2026-09-06-m0-first-slice.md` | Core Kernel 的详细开发计划；当前只计划，不代表已开始 |
| 验证记录 | `evidence/preparation-log.md`、`evidence/` | 命令、结果、复核人和未覆盖风险 |
| 自动检查 | `tools/devprep.py` | `check`、`render`、`environment` |

## 快速命令

```powershell
python tools/devprep.py environment  # 只采集版本/能力，不读取密钥
python tools/devprep.py render       # 生成当前进度的可读摘要
python tools/devprep.py check        # 校验 JSON、引用、依赖、状态和材料入口
python -m unittest discover -s tests/preparation -v
```

`check` 通过只证明开发准备材料内部一致；不证明 Runtime、Conformance 或 Bootstrap Acceptance 通过。`environment` 的工具缺失是事实证据，不由脚本安装；网络、凭证、Git 初始化、Docker/WSL 等仍需按授权完成。

## 状态语义

- `todo`：已登记但依赖或范围还未满足。
- `ready`：依赖满足，可由一个 Agent 协商接手；不代表权限或环境已就绪。
- `in_progress`：已明确执行者和工作范围。
- `review`：产物完成，等待不同 Agent 的独立复核。
- `done`：有复现命令、证据和独立复核；只有此状态计入完成率。
- `blocked`：同一外部阻塞被记录，附解除条件；不把未知当成功。

`backlog.json` 是计划清单，不是跨进程原子认领服务。实际 Agent 协作仍通过项目支持的通信机制或人工确认进行。

## 当前边界

- 设计已确认：用户输入想法，至少两个平等、独立 Agent 直接互相回应、讨论方案、按方案协作交付；无 Manager 必经路径。
- M0 只做五核心对象和无危险模拟 Runtime；M1 才加入双 Agent、Message、Artifact、Review、Verification 和执行边界。
- A2A 是可选 Transport Adapter，不是 AETP 的必需依赖。
- 目前无产品源码、依赖锁定、Git 历史或已执行的 28 条 Conformance；不要写 `BOOTSTRAP_VERIFIED`。
