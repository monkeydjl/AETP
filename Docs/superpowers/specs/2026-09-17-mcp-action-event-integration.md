# MCP→Action/Event 集成设计

## 目标

将现有 `MCPClientAdapter` 接入 AETP 已实现的 `tool.*` / Action 事实链，使 MCP 工具调用受 AETP Command、Event Store、Projection、Lease、Approval、Pause Barrier 与 UNKNOWN reconciliation 约束。

## 已确认决策

- 复用现有 `tool.request`、`tool.dispatch`、`tool.report`、`tool.reconcile` 与 Action Projection；不新增平行 `mcp.*` 命令/事件模型。
- MCP Server transport、`server_id`、允许工具集合、风险等级与工具 schema 摘要来自受信宿主配置；Server 的 `tools/list` 只提供元数据，不自动授予权限。
- 未登记工具默认拒绝；高风险工具必须有 AETP Approval 与参数摘要绑定。
- MCP 结果通过现有 Action 结果/UNKNOWN 语义持久化；超时、断连或响应无法确认时保留 `unknown`，对账沿用同一 Action/幂等意图，不创建新调用。
- Replay 只重放既有 Event，不访问 MCP Server、不重新发送 JSON-RPC 请求。

## 数据流

```text
MCP request
  -> trusted tool registration + PreTool authorization
  -> existing tool.request Command
  -> existing Action Event / Projection (pending)
  -> existing tool.dispatch Command/Event
  -> MCP JSON-RPC tools/call (outside DB transaction)
  -> existing tool.report Command/Event (completed or unknown)
  -> existing tool.reconcile for UNKNOWN
```

## 边界

- 受信配置必须固定 `server_id`, tool name, risk level, schema digest 与 transport identity；远端 metadata 与配置不一致时拒绝。
- MCP adapter 不直接写 Event/State；所有持久事实由 `ExecutionService` / `ActionBroker` 产生。
- MCP 调用所需的 `task_id`, session, binding, lease epoch 与 authenticated actor 由 ExecutionService 的现有 session/context 提供。
- 当前切片使用本地 fake MCP Server 验证集成，不声称真实外部 MCP 网络互操作已经完成。

## 验收

1. 未登记 server/tool 在 `tool.request` 前拒绝，MCP Server 收到 0 请求；
2. 合法低风险工具通过现有 Action 生命周期，产生可重放的 request/dispatch/report 事实；
3. 高风险工具缺少 Approval、参数摘要漂移、actor/epoch 不匹配或 Project PAUSED 时在 MCP dispatch 前拒绝；
4. MCP 响应成功写入同一 Action 的 `tool.report`，响应错误/断连转为 `unknown`；
5. UNKNOWN 只允许同一 Action 的 reconcile，禁止新调用或新幂等键；
6. 删除 Projection/cache 后 Replay 得到相同 Action 状态，并且 Replay 不调用 MCP Server；
7. 现有 Runtime、MCP、Fault Injection、Bootstrap、Conformance runner 与 preparation 回归保持通过。
