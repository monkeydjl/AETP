# MCP→Action/Event Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 MCPClientAdapter 接入现有 AETP `tool.*` / Action 事实链，确保 MCP 工具调用可授权、可审计、可对账、可重放。

**Architecture:** MCP adapter 只负责受信 server/tool 配置、JSON-RPC transport 和响应解析；调用生命周期委托给现有 `ExecutionService` / `ActionBroker`。`tool.request` 与 `tool.dispatch` 在数据库事务中只提交意图，外部 MCP 调用在事务外执行，随后使用同一 Action 的 `tool.report` 或 `tool.reconcile` 持久化结果。

**Tech Stack:** Python 3.11+、SQLite、现有 AETP Command/Event/Projection、`unittest`，无新增外部依赖。

**Spec:** `Docs/superpowers/specs/2026-09-17-mcp-action-event-integration.md`

## Global Constraints

- 必须遵守 `Command → Event Store → Projection`，MCP adapter 不直接写 State 或制造权威 Event。
- 受信配置提供 server identity、允许工具、风险等级和 schema digest；远端 `tools/list` 不自动授予权限。
- 高风险工具必须有有效 Approval 与参数摘要绑定；缺失时在 JSON-RPC dispatch 前拒绝。
- UNKNOWN 沿用现有 Action reconciliation，禁止新建 key 或盲目重试。
- Replay 不访问 MCP Server、不重新发送 JSON-RPC 请求。
- 不修改 `Docs/development/status.json` 的正式 Conformance 计数；不声称真实外部 MCP 已接入。

---

### Task 1: 受信 MCP Tool Registration 与 Action 入站接口

**Files:**
- Modify: `src/aetp/runtime/mcp.py`
- Create: `src/aetp/runtime/mcp_policy.py`
- Test: `tests/runtime/test_mcp_action_integration.py`

**Interfaces:**
- `MCPToolRegistration(server_id: str, tool_name: str, risk_level: str, schema_digest: str)`
- `MCPToolRegistry.register(registration) -> None`
- `MCPToolRegistry.resolve(server_id: str, tool_name: str) -> MCPToolRegistration`
- `MCPClientAdapter.request_action(execution_service, command, registration) -> dict`

- [ ] **Step 1: Write failing tests**

```python
def test_unregistered_mcp_tool_rejected_before_server_dispatch(self):
    registry = MCPToolRegistry()
    adapter = MCPClientAdapter(LocalMemoryMCPServer(), registry=registry)
    with self.assertRaises(AdapterSecurityError) as exc:
        adapter.request_action(self.execution_service, self.tool_request, server_id="trusted")
    self.assertEqual(exc.exception.code, "MCP_TOOL_NOT_REGISTERED")
    self.assertEqual(self.server.requests, [])
```

```python
def test_registered_tool_requires_schema_digest_match(self):
    registry.register(MCPToolRegistration("trusted", "fetch_context", "low", "sha256:expected"))
    server advertises a different schema digest
    assert request is rejected with MCP_SCHEMA_DRIFT
```

- [ ] **Step 2: Run RED**

Run:
```powershell
PYTHONPATH=src python -m unittest tests/runtime/test_mcp_action_integration.py -v
```
Expected: FAIL because registry and Action-bound request interface do not exist.

- [ ] **Step 3: Implement minimal registry**

```python
@dataclass(frozen=True)
class MCPToolRegistration:
    server_id: str
    tool_name: str
    risk_level: str
    schema_digest: str

class MCPToolRegistry:
    def __init__(self):
        self._entries = {}
    def register(self, registration):
        self._entries[(registration.server_id, registration.tool_name)] = registration
    def resolve(self, server_id, tool_name):
        try:
            return self._entries[(server_id, tool_name)]
        except KeyError as exc:
            raise AdapterSecurityError("MCP_TOOL_NOT_REGISTERED") from exc
```

`request_action` must resolve registration before calling `server.handle_request`; it receives a trusted execution command/context and delegates Action creation to `ExecutionService`, not direct Event writes.

- [ ] **Step 4: Run GREEN**

Run the same command. Expected: registration and pre-dispatch rejection tests pass.

---

### Task 2: Successful MCP Call Through Existing Action Lifecycle

**Files:**
- Modify: `src/aetp/runtime/mcp.py`
- Modify: `tests/runtime/test_mcp_action_integration.py`

**Interfaces:**
- `MCPClientAdapter.execute_registered_action(execution_service, action, session) -> dict`
- Uses existing `ExecutionService.handle`, `dispatch`, and Action result state; no new `mcp.*` events.

- [ ] **Step 1: Write failing test**

```python
def test_registered_low_risk_call_persists_action_facts(self):
    action = adapter.execute_registered_action(service, action, session)
    self.assertEqual(action["status"], "completed")
    event_types = [event.type for event in store.read_events("p-1")]
    self.assertIn("tool.requested", event_types)
    self.assertIn("tool.invoked", event_types)
    self.assertIn("tool.completed", event_types)
    self.assertEqual(Projection.rebuild(store.read_events("p-1")), store.read_projection("p-1"))
```

- [ ] **Step 2: Run RED**

Run:
```powershell
PYTHONPATH=src python -m unittest tests/runtime/test_mcp_action_integration.py::test_registered_low_risk_call_persists_action_facts -v
```
Expected: FAIL because adapter is not connected to ExecutionService Action lifecycle.

- [ ] **Step 3: Implement minimal bridge**

Use existing `tool.request` payload (`session_id`, `operation`, `arguments`, binding fence) and existing `ExecutionService.dispatch`. Keep external MCP `tools/call` outside SQLite transaction. On success, submit existing `tool.report` with the Action receipt; return projected Action state.

- [ ] **Step 4: Run GREEN**

Run the focused integration test and the existing `tests/runtime/test_mcp.py`. Expected: both pass and Event types are durable.

---

### Task 3: UNKNOWN, Pause, Approval, and Replay Integration

**Files:**
- Modify: `src/aetp/runtime/mcp.py`
- Modify: `tests/runtime/test_mcp_action_integration.py`

**Interfaces:**
- `MCPClientAdapter.execute_registered_action` must return projected Action `unknown` on transport/response uncertainty.
- `MCPClientAdapter.reconcile_action(execution_service, action_id) -> dict` delegates to existing `ExecutionService.reconcile` and never creates a new request key.

- [ ] **Step 1: Write failing tests**

```python
def test_unknown_mcp_result_reconciles_same_action_without_second_call(self):
    first = adapter.execute_registered_action(service, action, session)
    self.assertEqual(first["status"], "unknown")
    reconciled = adapter.reconcile_action(service, first["id"])
    self.assertEqual(reconciled["id"], first["id"])
    self.assertEqual(count_server_tool_calls(), 1)
```

```python
def test_pause_or_missing_approval_blocks_before_mcp_server(self):
    service.pause("p-1")
    with self.assertRaises(PolicyViolation):
        adapter.execute_registered_action(service, action, session)
    self.assertEqual(count_server_tool_calls(), 0)
```

```python
def test_replay_does_not_call_mcp_server(self):
    before = count_server_tool_calls()
    rebuilt = Projection.rebuild(store.read_events("p-1"))
    self.assertEqual(rebuilt, store.read_projection("p-1"))
    self.assertEqual(count_server_tool_calls(), before)
```

- [ ] **Step 2: Run RED**

Run:
```powershell
PYTHONPATH=src python -m unittest tests/runtime/test_mcp_action_integration.py -v
```
Expected: UNKNOWN/pause/replay integration tests fail until bridge delegates to existing Action recovery.

- [ ] **Step 3: Implement minimal recovery bridge**

Catch only transport/response uncertainty and submit existing `tool.report` outcome `unknown`; do not catch authorization violations as UNKNOWN. Delegate reconciliation to the existing ActionBroker, which already prevents cross-provider access and idempotency poisoning.

- [ ] **Step 4: Run GREEN**

Run:
```powershell
PYTHONPATH=src python -m unittest tests/runtime/test_mcp_action_integration.py -v
PYTHONPATH=src python -m unittest discover -s tests/runtime -v
```
Expected: all integration and runtime tests pass.

---

### Task 4: Final Verification and Handoff

**Files:**
- Modify: `MEMORY.md`
- Create: `Docs/development/evidence/2026-09-17-mcp-action-event-handoff.md`

- [ ] **Step 1: Run focused verification**

```powershell
PYTHONPATH=src python -m unittest tests/runtime/test_mcp_action_integration.py -v
PYTHONPATH=src python -m unittest discover -s tests/runtime -v
PYTHONPATH=src python -m tests.fault_injection.runner --json artifacts/fault-injection-report.json
```

- [ ] **Step 2: Run project checks**

```powershell
python tools/devprep.py render
python tools/devprep.py check
python -m unittest discover -s tests/preparation -v
```

- [ ] **Step 3: Record evidence without acceptance inflation**

Append to `MEMORY.md`:
- files changed;
- commands and exit codes;
- Action/Event evidence and UNKNOWN/replay behavior;
- limitation: local MCP fixture only unless an external server is explicitly approved;
- formal Conformance remains `28 registered / 0 passed`.

- [ ] **Step 4: Review handoff**

Keep formal status at `review`/pending until an independent reviewer different from `/root` can inspect and run the evidence. Do not mark formal Conformance passed or `BOOTSTRAP_VERIFIED` based only on author tests.
