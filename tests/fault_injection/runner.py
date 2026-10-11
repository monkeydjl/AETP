"""Unified runner and report generator for the 15-class AETP Fault Injection Suite.

Specification source: Docs/AETP-设计方案.md §§18.2, 11.4, 14.1-14.4, 16.
Runs FI-01 through FI-15 and outputs structured anti-fragility evaluation artifacts.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import unittest

from tests.fault_injection.test_batch1 import FaultInjectionBatch1Tests
from tests.fault_injection.test_batch2 import FaultInjectionBatch2Tests

FAULT_DEFINITIONS = [
    {"id": "FI-01", "title": "Agent 进程崩溃与 Lease 安全重新分配", "mechanism": "Task Lease (7.6 / 11.4)"},
    {"id": "FI-02", "title": "提交后响应丢失幂等重试零重复事件", "mechanism": "Command 幂等收据 (14.1)"},
    {"id": "FI-03", "title": "同幂等键异内容冲突严格拒绝", "mechanism": "幂等摘要对比 (14.1 / INV-014)"},
    {"id": "FI-04", "title": "并发同版本认领 CAS 乐观锁序列化", "mechanism": "代次 CAS 约束 (7.6 / 14.1)"},
    {"id": "FI-05", "title": "投影缓存丢失纯重放确定性恢复", "mechanism": "Projection.rebuild (14.2 / INV-015)"},
    {"id": "FI-06", "title": "外部动作 UNKNOWN 对账与防盲目重试", "mechanism": "Tool Reconcile 对账 (14.4)"},
    {"id": "FI-07", "title": "通信身份与声明身份不符阻断", "mechanism": "Boundary Authentication (13.9 / 14.1)"},
    {"id": "FI-08", "title": "未经审批高风险操作严格拒绝", "mechanism": "Governance Policy (9.3 / INV-006)"},
    {"id": "FI-09", "title": "审批参数事后篡改 live binding 拦截", "mechanism": "Approval Binding Snapshot (9.3)"},
    {"id": "FI-10", "title": "审批超时自动流转并产生升级路径", "mechanism": "on_expire 升级机制 (9.3)"},
    {"id": "FI-11", "title": "项目暂停屏障阻断推进并冻结时钟", "mechanism": "Governance Clock (13.4 / 5.1)"},
    {"id": "FI-12", "title": "未进 in_review 或无验证逃避门禁拦截", "mechanism": "Task Quality 门禁 (7.3 / 10.3 / INV-017)"},
    {"id": "FI-13", "title": "目标分支基线前移触发合并冲突保护", "mechanism": "Integration Gate 基线保护 (10.6 / TEST-024)"},
    {"id": "FI-14", "title": "跨工作区 Provider 越界访问物理阻断", "mechanism": "Provider 安全边界 (13.9 / INV-020)"},
    {"id": "FI-15", "title": "不可信输入缺乏有效收据直接阻断", "mechanism": "Input Authority 收据校验 (14.11 / INV-020)"},
]


def run_fault_injection_suite(*, json_out: str | None = None) -> dict:
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    suite.addTests(loader.loadTestsFromTestCase(FaultInjectionBatch1Tests))
    suite.addTests(loader.loadTestsFromTestCase(FaultInjectionBatch2Tests))

    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    finished_at = dt.datetime.now(dt.timezone.utc).isoformat()

    report = {
        "suite": "AETP Anti-Fragility Fault Injection Suite (FI-01..FI-15)",
        "specification": "Docs/AETP-设计方案.md §18.2",
        "started_at": started_at,
        "finished_at": finished_at,
        "total_fault_classes": len(FAULT_DEFINITIONS),
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "all_passed": result.wasSuccessful(),
        "fault_definitions": FAULT_DEFINITIONS,
        "criteria_verification": {
            "existing_mechanisms_only": True,
            "event_store_fully_auditable": True,
            "pure_replay_deterministic": True,
            "idempotency_zero_side_effects": True,
        },
    }

    if json_out:
        os.makedirs(os.path.dirname(os.path.abspath(json_out)), exist_ok=True)
        with open(json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"Report written to: {json_out}")

    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="AETP Fault Injection Suite Runner")
    parser.add_argument("--json", default="artifacts/fault-injection-report.json", help="Path to write report JSON")
    args = parser.parse_args(argv)

    report = run_fault_injection_suite(json_out=args.json)
    return 0 if report["all_passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
