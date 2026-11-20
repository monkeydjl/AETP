# M3-02 Task 质量迁移示例

真实 SQLite 与固定 JSON 文档 Runtime；身份和输入来自确定性夹具，没有真实模型自治调用。

| 轮次 | Verification | Task 判定 |
| --- | --- | --- |
| 结果事务失败后恢复 | INCONCLUSIVE / abandoned | IN_REVIEW |
| 明确返工后的错误内容 | FAILED | REJECTED |
| 再次返工后的正确内容 | PASSED | VERIFIED → 显式无集成面豁免 → COMPLETED |

每轮均正式提交完整成果、创建独立 Review 并执行受信检查。旧轮次保留且不复用；派发 TTL 到期后仍按证据最大年龄检查 PASSED。

完成依据是 human_owner 对这个具体 Task 的无集成面声明。系统没有自动识别真实集成需求，也没有完成真实 Integration Gate 或 Mission Acceptance。

task.integration_exempted 的中间前缀仍为 VERIFIED；只有 task.completed 才撤销 Lease、退役 Binding。旧 requeue 被拒绝。

125 个 Events / 59 个 Commands；两库共 250 个前缀只读重放，执行与 I/O 守卫零调用。

M3-02 整项仍 in_progress；完整 M1 not_accepted、Bootstrap not_started、完整 Conformance 28 registered / 0 passed。
