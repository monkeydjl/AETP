# AETP MCP 客户端适配器与治理拦截架构方案

## 1. 规范定位与背景

依据《AETP-设计方案.md》§2、§2.1、§2.2、§13.9 与核心不变量 INV-006、INV-013：
- **MCP（Model Context Protocol）** 是 Agent 与外部 Tool / Data（工具与资源）交互的标准协议；
- **AETP 负责工程团队的组织与受控治理**：AETP 不替代 MCP，而是作为治理层包覆并约束 MCP 连接；
- 在 AETP 中，所有外部 MCP Tool Call / Resource Access 都必须纳入协议的执行边界，并在真实调用发生前受控于：
  1. **Pre-Tool 授权拦截**：身份对齐、有效活跃 Binding 与 Lease epoch 检查；
  2. **治理审批快照检查**：高风险工具调用必须绑定有效审批单与参数摘要防篡改；
  3. **暂停屏障（Pause Barrier）**：Project PAUSED 期间冻结工具派发；
  4. **受控审计留痕**：工具调用结果必须以 `tool.report` 事实规范上报，不可绕过协议事实链。

---

## 2. 核心架构与交互时序

```text
 Agent (LLM) ──► RuntimeAdapter.execute_tool("mcp:server/tool", args)
                        │
                        ▼
            PreToolAuthorizer.authorize()
            ├─ [1] 暂停屏障 (PAUSED?)
            ├─ [2] 身份与 Binding (ACTOR_MISMATCH?)
            ├─ [3] 租约代次 (LEASE_EXPIRED?)
            └─ [4] 治理审批 (PRE_TOOL_UNAUTHORIZED / APPROVAL_STALE?)
                        │ (通过)
                        ▼
            MCPClientAdapter.call_tool()
            ├─ 格式化 JSON-RPC 2.0 请求
            ├─ 派发给目标 MCP Server (进程管道 / 内存夹具)
            └─ 接收并校验 JSON-RPC 2.0 响应
                        │
                        ▼
            Tool Report Command / 结果返回上报
```

---

## 3. 对象与协议映射

依据规范 §2.1：
- **Agent Capability** ↔ MCP `Tools`；
- **Artifact / Context** ↔ MCP `Resource`；
- **Tool Ingress / Dispatch** ↔ MCP `JSON-RPC` (`tools/list`, `tools/call`, `resources/read`)。

---

## 4. 关键设计要求

1. **标准 JSON-RPC 2.0 消息契约**：完整遵循 MCP 规范的消息格式与错误码；
2. **工具与资源发现**：支持 `tools/list` 与 `resources/list`，并向 AETP 报告声明能力；
3. **安全拦截零穿透**：高风险工具、未授权调用、参数篡改与暂停状态下，在 JSON-RPC 派发前被 100% 物理拦截，严禁泄露请求到底层 Server。
