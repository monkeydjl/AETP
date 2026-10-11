# M2-02 v1 最终交接

工作项 M2-02 已独立接受并置 done；M3-01 ready。当前 **18 done / 1 ready / 1 todo**。执行者 `/root`，独立 reviewer `/root/m1_reviewer`，主线程消费不构成另一位独立 reviewer。

成果：Approval 绑定版本/参数/主体；过期、有限续期、委托与撤销保留升级路径；人类暂停/恢复和 Intervention 按 Command → Event → Projection 可重放。固定文档调用点重查实际授权，未配置 Runtime 的恢复也检查真实 pending Commands。

输入与范围：M2-01 已接受 v2；原规范 §§5.1、9.1–9.7、13.4、13.9–13.10、14.1–14.4、14.11、18.3。本项 spec/plan、backlog 三项标准和 `2026-09-12-m2-02-review-response.md` 提供设计、写集、失败与修复依据。

修改文件：新增 `src/aetp/governance/`、治理测试和本项证据；扩展 domain 模型、core Command/Projection、runtime 审批与恢复入口、meetings 原提案兼容。全部路径见 backlog 的 M2-02.files 及固定快照。SQLite schema、主规范和已接受历史未改写。

独立报告 `Docs/development/evidence/2026-09-12-m2-02-review.json`，SHA-256 `1b107a3cbf6ed7c59e1c629a9e87648583c69170706ee629ae3770adeb8b8b12`；主线程消费于 `2026-09-13T00:06:10.851363+08:00`，记录 `2026-09-12-m2-02-review-consumption.json`。受审报告 `artifacts/m2-02-test-report.json` SHA-256 `547e7a0509fe4ba37a69d4a8094e9c4f683936a3c3d91cfc257002674ef848a4`，236 输入快照 SHA-256 `bd07b57be12dd5c1480fec1e8218200fb2db9d16f598e996f012fb54677b7608`。候选 review pending 原样保留；接受依据单独记录。

| 作者已运行命令 | 退出码 | 测试方法 | 开始时间 |
| --- | --- | --- | --- |
| `python -m unittest discover -s tests/m2 -t . -v` | 0 | 167 | 2026-09-12T23:08:58.151687+08:00 |
| `python -m unittest discover -s tests/m1 -t . -v` | 0 | 85 | 2026-09-12T23:11:32.493015+08:00 |
| `python -m unittest discover -s tests/m0 -t . -v` | 0 | 156 | 2026-09-12T23:12:27.101724+08:00 |
| `python -m unittest discover -s tests/preparation -v` | 0 | 27 | 2026-09-12T23:15:35.464658+08:00 |

独立实际方法数：`{"m2_suite": 167, "m1_suite": 85, "m0_suite": 156, "preparation_suite": 27, "independent_probes_v2": 6}`。所有命令的绝对解释器、argv、cwd、起止时间、退出码和原始日志摘要分别见主 journal 与独立报告。R1 来源继承、R3 身份互斥、R2 父子因果和审计伪装、Manual 路由、旧 reducer 绕过及 receipt-only 恢复缺口均有真实 RED/GREEN；保留夹具/循环导入诊断和全部历史非零运行。

示例 `artifacts/m2-02-demo-candidate-v1.json` 及同名完整/仅事实 SQLite 库、Markdown 与 workspace：100 Event、两份真实文档、15 个 live-facility 守卫零调用、逐前缀 Replay。原提案经过独立审批后 active，原正文与异议保持；丢失 Session 时保持暂停，替换旧执行权后另一 Agent 在 epoch=2 恢复文档；veto 保留已发生输出，高风险到期 BLOCKED。旧 M2-01 两个数据库及 217 份旧输入归档保持。

未覆盖：仅 decision/task 两类目标适配器；其他合法目标与通用 Shell/网络/凭证/发布能力拒绝。InputAuthority 依赖可信宿主，固定文档 Provider 不是通用 OS sandbox；没有真实模型费用账本、后台 tick/外部通知或多主机执行证明。治理缓存因缺因果游标回退完整事实重放，不承诺吞吐。完整 M1 not_accepted、Verification INCONCLUSIVE、没有合法 Task COMPLETED；完整 Conformance 28 registered / 0 passed、product completion 0、Bootstrap not_started；完整 M2 未独立验收。

结束前准备检查标签是 `closeout_render_v1`、`closeout_check_v1`、`closeout_preparation_v1`；实际执行结果和最终状态回读由 `2026-09-12-m2-02-closeout.json` 记录。下一步为 M3-01 动态组队、Blueprint 与 Task DAG，按 backlog 先确认依赖和失败场景；本轮未实施 M3。

无 ClaudeLink、新代理、Git 初始化/提交/推送、依赖安装、联网或全局配置变化。M1-02 历史五个未在其 v2 执行的方法仍不计入那次接受。
