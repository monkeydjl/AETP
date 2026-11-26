"""AETP Full-Protocol Conformance Test Suite Runner (TEST-001..TEST-028).

Specification source: Docs/AETP-设计方案.md §§13.4, 13.9, 14.1-14.4, 15.1, 16, 17.4, 18.3.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import platform
import sys
import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional

# Imported for its side effect: this module's @register_fixture decorators are
# what populate FIXTURE_HANDLERS with the 28 executable fixtures. It looks
# unused to a linter and removing it leaves the registry empty, so every fixture
# silently reports "not run". Kept with the noqa for exactly that reason.
import conformance.fixtures  # noqa: F401  (registers standard executable fixtures)
from conformance.definitions import (
    CONFORMANCE_DEFINITIONS,
    FIXTURE_KINDS,
    ConformanceDefinition,
)
from conformance.registry import FIXTURE_HANDLERS


@dataclass
class TestResult:
    test_id: str
    title: str
    invariant: str
    domain: str
    status: str            # "passed" | "pending" | "failed" | "not_applicable"
    execution_status: str  # "passed" | "failed" | "not_run"
    summary: str
    details: Dict[str, Any]
    duration_ms: float
    fixture_kind: str = ""
    elements: Optional[Dict[str, str]] = None
    evidence_digest: str = ""


# counts is built from exact string matches on these two fields. A value outside
# the sets below - or a missing key - would leave a result counted by `total` and
# by no other counter, so the suite could report all-passed over a run in which
# that result never landed anywhere.
EXECUTION_STATUSES = ("passed", "failed", "not_run")
RESULT_STATUSES = ("passed", "pending", "failed", "not_applicable")

FROZEN_ELEMENT_KEYS = (
    "initial_state",
    "input_surface",
    "runtime_capability",
    "fault_injection",
    "expected",
    "replay_result",
)


def _canonical_digest(value: Any) -> str:
    import hashlib
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def elements_of(defn: ConformanceDefinition) -> Dict[str, str]:
    return {key: getattr(defn, key) for key in FROZEN_ELEMENT_KEYS}


def missing_elements(defn: ConformanceDefinition) -> List[str]:
    return [key for key, value in elements_of(defn).items() if not isinstance(value, str) or not value.strip()]


def run_conformance(
    db_path: str,
    *,
    filter_ids: Optional[List[str]] = None,
    evidence_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Execute AETP conformance suite and produce a standardized report."""
    if os.path.exists(db_path):
        raise FileExistsError(f"Database path already exists: {db_path}; conformance requires a clean new database.")

    from aetp.storage.sqlite_store import SQLiteStore
    store = SQLiteStore.open(db_path)

    results: Dict[str, TestResult] = {}
    started_at = dt.datetime.now(dt.timezone.utc).isoformat()
    start_perf = time.perf_counter()

    # A filter naming an id the suite does not define must not be quietly ignored.
    # Running a subset of what was asked for while reporting success is the same
    # defect as discovery skipping a directory it never entered.
    unmatched_filter_ids = [f for f in (filter_ids or []) if f not in CONFORMANCE_DEFINITIONS]

    target_ids = list(CONFORMANCE_DEFINITIONS.keys())
    if filter_ids:
        target_ids = [tid for tid in target_ids if tid in filter_ids]

    for tid in target_ids:
        defn = CONFORMANCE_DEFINITIONS[tid]
        handler = FIXTURE_HANDLERS.get(tid)
        elements = elements_of(defn)

        if handler is None:
            # Scope registration only, not yet executed in current pass
            results[tid] = TestResult(
                test_id=tid,
                title=defn.title,
                invariant=defn.invariant,
                domain=defn.domain,
                status="pending",
                execution_status="not_run",
                summary="Fixture not yet wired in this runner pass",
                details={},
                duration_ms=0.0,
                fixture_kind=defn.fixture_kind,
                elements=elements,
                evidence_digest=_canonical_digest(elements),
            )
            continue

        # §18.3 requires the six frozen elements before a result may be frozen.
        absent = missing_elements(defn)
        if absent:
            results[tid] = TestResult(
                test_id=tid,
                title=defn.title,
                invariant=defn.invariant,
                domain=defn.domain,
                status="failed",
                execution_status="failed",
                summary=f"Frozen-evidence elements missing: {', '.join(absent)}",
                details={"missing_elements": absent},
                duration_ms=0.0,
                fixture_kind=defn.fixture_kind,
                elements=elements,
                evidence_digest="",
            )
            continue

        # A declared evidence strength is not evidence. The frozen snapshot
        # republishes `fixture_kind` verbatim, so a value outside FIXTURE_KINDS
        # would publish a strength nobody established - and unlike the six frozen
        # elements, this field is bound by no digest, so nothing else would catch
        # it. Refuse it before the fixture runs.
        if defn.fixture_kind not in FIXTURE_KINDS:
            results[tid] = TestResult(
                test_id=tid,
                title=defn.title,
                invariant=defn.invariant,
                domain=defn.domain,
                status="failed",
                execution_status="failed",
                summary=f"fixture_kind {defn.fixture_kind!r} is not one of {FIXTURE_KINDS}",
                details={"invalid_fixture_kind": defn.fixture_kind},
                duration_ms=0.0,
                fixture_kind=defn.fixture_kind,
                elements=elements,
                evidence_digest=_canonical_digest(elements),
            )
            continue

        # Execute registered fixture
        t0 = time.perf_counter()
        try:
            res_dict = handler(store, project_id=f"p-{tid.lower()}")
            duration_ms = (time.perf_counter() - t0) * 1000.0
            problems = []
            execution_status = res_dict.get("execution_status")
            if execution_status not in EXECUTION_STATUSES:
                problems.append(f"execution_status {execution_status!r} is not one of {EXECUTION_STATUSES}")
            result_status = res_dict.get("status")
            if result_status not in RESULT_STATUSES:
                problems.append(f"status {result_status!r} is not one of {RESULT_STATUSES}")

            if problems:
                # Refuse it rather than let it fall through the gaps. A missing key
                # is included on purpose: absence is not evidence of passing.
                results[tid] = TestResult(
                    test_id=tid,
                    title=defn.title,
                    invariant=defn.invariant,
                    domain=defn.domain,
                    status="failed",
                    execution_status="failed",
                    summary="; ".join(problems) + " - refusing to count it as anything but a failure",
                    details={"unaccounted_result_fields": problems},
                    duration_ms=round(duration_ms, 2),
                    fixture_kind=defn.fixture_kind,
                    elements=elements,
                    evidence_digest=_canonical_digest(elements),
                )
            else:
                results[tid] = TestResult(
                    test_id=tid,
                    title=defn.title,
                    invariant=defn.invariant,
                    domain=defn.domain,
                    status=result_status,
                    execution_status=execution_status,
                    summary=res_dict.get("summary", "Test fixture passed successfully"),
                    details=res_dict.get("details", {}),
                    duration_ms=round(duration_ms, 2),
                    fixture_kind=defn.fixture_kind,
                    elements=elements,
                    evidence_digest=_canonical_digest(elements),
                )
        except Exception as exc:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            results[tid] = TestResult(
                test_id=tid,
                title=defn.title,
                invariant=defn.invariant,
                domain=defn.domain,
                status="failed",
                execution_status="failed",
                summary=f"Exception during test execution: {exc}",
                details={"error_type": type(exc).__name__, "error": str(exc)},
                duration_ms=round(duration_ms, 2),
                fixture_kind=defn.fixture_kind,
                elements=elements,
                evidence_digest=_canonical_digest(elements),
            )

    store.close()
    total_duration_ms = round((time.perf_counter() - start_perf) * 1000.0, 2)
    finished_at = dt.datetime.now(dt.timezone.utc).isoformat()

    counts = {
        "total": len(results),
        "executed_passed": sum(1 for r in results.values() if r.execution_status == "passed"),
        "executed_failed": sum(1 for r in results.values() if r.execution_status == "failed"),
        "not_run": sum(1 for r in results.values() if r.execution_status == "not_run"),
        "status_passed": sum(1 for r in results.values() if r.status == "passed"),
        "status_pending": sum(1 for r in results.values() if r.status == "pending"),
        "status_failed": sum(1 for r in results.values() if r.status == "failed"),
    }
    # Every result must land in exactly one counter. execution_status is a free
    # string, so a fixture reporting any other value would make its result
    # invisible: `total` counts it, the counters do not, and the suite reads green.
    accounted = counts["executed_passed"] + counts["executed_failed"] + counts["not_run"]
    # The status axis must account for every result too. not_applicable is a valid
    # status with no counter of its own, so sum it here rather than leave it able
    # to disappear from the status breakdown.
    status_accounted = (
        counts["status_passed"]
        + counts["status_pending"]
        + counts["status_failed"]
        + sum(1 for r in results.values() if r.status == "not_applicable")
    )

    report = {
        "suite": "AETP Full-Protocol Conformance",
        "specification": "Docs/AETP-设计方案.md §18.3",
        "started_at": started_at,
        "finished_at": finished_at,
        "duration_ms": total_duration_ms,
        "database": db_path,
        "environment": {
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
        },
        "counts": counts,
        # A test that executed nothing is not a pass. Reporting the suite as
        # all-passed while tests sat unrun is the same defect class as
        # `unittest discover` silently skipping a non-package directory. A run
        # that selected no test at all (total == 0) is likewise not a pass.
        "all_passed": (
            counts["total"] > 0
            and accounted == counts["total"]
            and status_accounted == counts["total"]
            and counts["executed_failed"] == 0
            and counts["status_failed"] == 0
            and counts["not_run"] == 0
            and not unmatched_filter_ids
        ),
        "unmatched_filter_ids": unmatched_filter_ids,
        "results": {tid: asdict(res) for tid, res in results.items()},
        "frozen_evidence": build_frozen_snapshot(results, db_path, counts),
    }

    return report


def build_frozen_snapshot(
    results: Dict[str, TestResult],
    db_path: str,
    counts: Dict[str, int],
) -> Dict[str, Any]:
    """§18.3 frozen-evidence snapshot.

    Fixes, for every example, the six required elements plus the observed
    execution outcome, and binds them with per-test and suite-level digests so an
    independent reviewer can verify the frozen set has not drifted.
    """
    entries: Dict[str, Any] = {}
    for tid, res in sorted(results.items()):
        entries[tid] = {
            "title": res.title,
            "invariant": res.invariant,
            "domain": res.domain,
            "fixture_kind": res.fixture_kind,
            "elements": res.elements,
            "elements_digest": res.evidence_digest,
            "observed_status": res.status,
            "observed_execution_status": res.execution_status,
            "observed_summary": res.summary,
            "duration_ms": res.duration_ms,
        }
    body = {
        "database": db_path,
        "counts": counts,
        "entries": entries,
    }
    return {
        "frozen_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "element_keys": list(FROZEN_ELEMENT_KEYS),
        "database": db_path,
        "counts": counts,
        "suite_digest": _canonical_digest({tid: e["elements_digest"] for tid, e in entries.items()}),
        "snapshot_digest": _canonical_digest(body),
        "entries": entries,
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="AETP Full Conformance Suite Runner")
    parser.add_argument("--db", required=True, help="Path to new clean SQLite database file")
    parser.add_argument("--json", help="Path to save report JSON")
    parser.add_argument("--frozen-evidence", help="Path to save the §18.3 frozen-evidence snapshot JSON")
    parser.add_argument("--filter", help="Comma-separated test IDs to run (e.g. TEST-001,TEST-028)")
    parser.add_argument("--summary", action="store_true", help="Print summary only")

    args = parser.parse_args(argv)

    filter_ids = [s.strip() for s in args.filter.split(",")] if args.filter else None

    try:
        report = run_conformance(args.db, filter_ids=filter_ids)
    except FileExistsError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Fatal error running conformance: {exc}", file=sys.stderr)
        return 2

    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"Report written to: {args.json}")

    if args.frozen_evidence:
        os.makedirs(os.path.dirname(os.path.abspath(args.frozen_evidence)), exist_ok=True)
        with open(args.frozen_evidence, "w", encoding="utf-8") as f:
            json.dump(report["frozen_evidence"], f, indent=2, ensure_ascii=False)
        print(f"Frozen evidence written to: {args.frozen_evidence}")

    counts = report["counts"]
    print(f"Conformance Results: {counts['executed_passed']} passed, {counts['executed_failed']} failed, {counts['not_run']} not run (Total: {counts['total']})")

    # The exit code follows all_passed directly rather than re-deriving it. Two
    # copies of the same judgement drifted apart once already: extending the status
    # enumeration left all_passed False while this returned 0.
    if not report["all_passed"]:
        if report.get("unmatched_filter_ids"):
            print(
                f"Error: --filter named tests this suite does not define: "
                f"{report['unmatched_filter_ids']}",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
