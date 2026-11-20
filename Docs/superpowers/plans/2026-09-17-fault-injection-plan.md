# AETP 15 类故障注入实施计划

## 1. 目标

依据《AETP-设计方案.md》§18.2、§11.4、§14.1-14.4、§16，构建系统化可执行的 15 类故障注入测试套件（Fault Injection Suite），产出标准测试报告 `artifacts/fault-injection-report.json`，验证协议在各级事故下的反脆弱性。

## 2. 任务步骤

1. **第一阶段：设计方案（已完成）**
   - 编写 `Docs/superpowers/specs/2026-09-17-fault-injection-design.md`，明确 FI-01 至 FI-15 的场景、注入方式、对应机制与验证断言。
2. **第二阶段：测试框架与前 8 类故障夹具（FI-01 ~ FI-08）**
   - 编写 `tests/fault_injection/cases.py`，实现进程崩溃重分配、提交后响应丢失重试、幂等冲突、并发 CAS、缓存丢失纯重放、外部 UNKNOWN 对账、越权身份拦截与未授权高风险调用。
3. **第三阶段：后 7 类故障夹具（FI-09 ~ FI-15）与统一运行器**
   - 实现审批参数篡改拦截、审批超时升级路径、项目暂停屏障、任务跳级门禁拦截、代码基线前移拦截、跨工作区访问拦截、不可信输入拦截；
   - 实现调度器 `tests/fault_injection/runner.py` 并生成报告 `artifacts/fault-injection-report.json`。
4. **第四阶段：全量回归与进展闭环**
   - 运行故障注入测试套件及现有测试套件；
   - 运行 `tools/devprep.py check`，更新 `MEMORY.md` 记录。
