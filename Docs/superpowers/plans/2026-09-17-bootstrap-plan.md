# AETP Project Bootstrap（Mission #0）实施计划

## 1. 目标

实现符合 AETP 规范 §15.5、§5.2、§17.2 与核心不变量 INV-019 的标准 Project Bootstrap 流程，支持由平等 Agent 团队自主执行 B0-B5 初始化步骤，经受信任证据核验与 human_owner 终验门禁，产生结构化证据与真实 BOOTSTRAP_VERIFIED 状态迁移。

## 2. 阶段与任务拆解

1. **阶段 1：规范设计与计划（已完成）**
   - 制定详细规范设计文档 `Docs/superpowers/specs/2026-09-17-bootstrap-design.md`。

2. **阶段 2：专属契约与验证规则（Contracts & Validators）**
   - 在 `src/aetp/bootstrap/` 目录下建立核心模块：
     - `contracts.py`：定义 Bootstrap 相关命令类型（`bootstrap.finalize` 等）与事件类型（`project.bootstrap_verified` 等）；
     - `discovery.py`：B0 环境探针证据结构与验证器；
     - `acceptance.py`：B5 Bootstrap 终验门禁验证规则。

3. **阶段 3：执行器与完整场景夹具（Runner & Tests）**
   - 实现 `src/aetp/bootstrap/runner.py` 与 `tests/bootstrap/test_bootstrap_lifecycle.py`：
     - 贯通 Mission #0 创建与激活；
     - 平等 Agent 协商产出 B0-B5 Task DAG；
     - 真实执行 B0 环境探针采集并记录 Evidence；
     - 经由 Task Quality / Verification 链路确认；
     - 执行 Mission Acceptance 逐条核验，并在 human_owner 授权下完成交付；
     - 执行纯事件重放，断言 Project 正式达到 `BOOTSTRAP_VERIFIED`。

4. **阶段 4：回归验证与进展归档**
   - 运行新写测试套件；
   - 运行环境测试与 `devprep.py check`；
   - 追加写入 `MEMORY.md` 闭环记录。
