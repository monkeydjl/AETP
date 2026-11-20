# AETP 全协议 Conformance 测试套件实施计划

## 1. 目标

实现全协议统一的 Conformance 测试调度器（`conformance/runner.py`）并接入 28 项标准测试夹具（TEST-001 至 TEST-028），输出统一结构化评估报告。

## 2. 实施步骤

1. **架构与映射设计**（已就绪）：
   - 编写设计规范 `Docs/superpowers/specs/2026-09-17-conformance-suite-design.md`，明确 28 项 TEST 的映射关系、状态标准和调度架构。
2. **统一调度器与运行框架实现**：
   - 实现 `conformance/runner.py` 与 `conformance/base.py`，提供 `run_conformance(db_path, ...)` API 与 CLI 入口；
   - 支持全新数据库环境检测、安全隔离、时间戳与环境信息注入、结果汇总与 JSON 序列化。
3. **分领域测试夹具集成**：
   - 整合 M0 的内核与事务夹具（TEST-001, 002, 005, 017, 018, 021 等）；
   - 整合 M1/M2/M3 的治理、质量门、集成门禁与端到端自主交付夹具（TEST-004, 009, 010, 024, 028 等）；
   - 运行并生成初始全量报告 `artifacts/conformance-report.json`。
4. **全面验证与收尾**：
   - 运行自动化测试核验调度器与各夹具运行；
   - 运行 `python tools/devprep.py check` 与准备测试，保持环境整洁无冲突。
