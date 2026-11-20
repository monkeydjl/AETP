# AETP Runtime Adapter Contract 与执行沙箱边界方案

## 1. 规范背景与定位

依据《AETP-设计方案.md》§13.9、§5.13、§6.4 与核心不变量 INV-001、INV-011、INV-013、INV-020：
AETP 不实现 Agent 本身，不实现 LLM，不实现 Coding Runtime——它定义这些执行设施如何组成一个受治理、受审计的 AI 工程组织。
外部 Coding Agent（Claude Code / Codex / Gemini CLI / OpenCode / Hermes 等）通过 **Runtime Adapter** 接入成为 AETP Agent。

---

## 2. 职责解耦与双向通信契约

### AETP → Runtime（控制面：受控下发）
- `start(session_params)`: 启动会话；
- `stop(reason)`: 终止当前执行；
- `pause()`: 进入受控暂停，冻结时钟与在途操作；
- `resume()`: 恢复执行；
- `assign_task(task_spec, binding)`: 绑定并下发任务；
- `get_capabilities()`: 查询已声明的能力与执行边界；
- `execute_tool(tool_call, authorization_token)`: 经过前置授权（pre-tool authorization）的工具执行。

### Runtime → AETP（上报面：审计留痕）
**核心约束**：Runtime 绝对不得直接产生权威 Event，不允许直接写 State（INV-001 / INV-011）。所有上报必须封装为 Command 提交给 AETP 核心校验管线：
- `execution.report_started`: 执行开始；
- `execution.report_progress`: 执行中间进度；
- `execution.report_finished`: 执行结束（仅表示本次执行退出，不等于 task.completed，后续仍受制于质量门与集成门禁）；
- `execution.report_failed`: 执行异常；
- `tool.report`: 工具调用结果上报（含结果摘要与状态）。

---

## 3. Runtime Capability 与强制执行模式（Enforcement Modes）

### 模式划分
1. **`mediated`（受控中介模式）**：
   - 具备前置工具调用授权检查（pre_tool_authorization）；
   - 凭据隔离（credential_isolation）与工作区隔离；
   - 暂停状态下能够阻断敏感执行；
   - 具备完整 AETP 兼容执行资格。
2. **`observation_only`（仅观测模式）**：
   - 无真实外部沙箱防护或无法拦截工具调用；
   - 仅能参与讨论、评审与提交候选产物，**不得**承接依赖受控沙箱的高风险任务，不得宣称完整兼容。

### 前置工具授权拦截机制（Pre-Tool Authorization Boundary）
在真实工具（Shell / Python / MCP / 网络）调用点之前，必须拦截并校验：
1. **Actor 一致性**：当前调用者是否持有该 Task 的合法 Binding 与有效 Lease 代次（epoch）；
2. **治理审批快照**：高风险操作是否持有未过期的有效 Approval 绑定，参数摘要是否严格匹配；
3. **暂停屏障（Pause Barrier）**：Project 是否处于 PAUSED 状态；
4. **防绕过保障**：禁止绕开受控命令解析器直接调用底层系统接口。
