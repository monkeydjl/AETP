# M3-02 受信固定文档验证示例

这是确定性身份夹具；没有真实模型自治交付或 TEST-028 验收。

| 场景 | Verification 结果 | 实际派发次数 |
| --- | --- | ---: |
| pass | PASSED | 1 |
| fail | FAILED | 1 |
| revoked | INCONCLUSIVE | 0 |
| lost | INCONCLUSIVE | 1 |

PASSED 仅说明固定 JSON 路径检查匹配。两个 Task 仍为 in_progress，旧 M1 预检查仍为 INCONCLUSIVE。

结果事务失败保留 in_flight 并关闭恢复屏障；取得同一资源锁后，恢复记为 abandoned，保留丢失输出的事实且不重新执行。

产物来自真实 document.write Action 的完成证据；固定内部输入由夹具入口完整证明，不把普通 Agent 输入重标为可信。

完整库 85 个 Event、40 个 Command；完整库和仅事实库均逐前缀只读回放一致。
