#!/usr/bin/env python3
"""Validate and render AETP development-preparation materials.

This tool is deliberately limited to development metadata. It does not start a
runtime, read credentials, install dependencies, or infer product conformance
from the presence of documents or test names.
"""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "Docs" / "development"
EVIDENCE = DOCS / "evidence"
BACKLOG_PATH = DOCS / "backlog.json"
GRAPH_PATH = DOCS / "knowledge-graph.json"
STATUS_PATH = DOCS / "status.json"
REPORT_PATH = EVIDENCE / "preparation-report.json"
ENVIRONMENT_PATH = EVIDENCE / "environment.json"
DEVPREP_CHECK_PATH = EVIDENCE / "devprep-check.json"
GRAPH_CHECK_PATH = EVIDENCE / "knowledge-graph-check.json"
BACKLOG_CHECK_PATH = EVIDENCE / "backlog-check.json"
SKILL_PATHS = {
    "protocol-navigation": ROOT / "skills" / "aetp-protocol-navigation" / "SKILL.md",
    "execution-contracts": ROOT / "skills" / "aetp-execution-contracts" / "SKILL.md",
    "evidence-handoff": ROOT / "skills" / "aetp-evidence-handoff" / "SKILL.md",
}
SKILL_MARKERS = {
    "protocol-navigation": ("knowledge-graph.json", "INV-", "TEST-"),
    "execution-contracts": (
        "Command", "Event Store", "Projection", "Replay", "UNKNOWN", "Lease",
        "幂等", "执行边界",
    ),
    "evidence-handoff": ("交接", "独立复核", "Conformance"),
}

STATUS_VOCABULARY = {"todo", "ready", "in_progress", "review", "done", "blocked"}
MILESTONES = ("PREP", "M0", "M1", "M2", "M3", "M4")
CONFORMANCE_IDS = {f"TEST-{n:03d}" for n in range(1, 29)}
MARKDOWN_ENTRY_PATHS = (
    Path("README.md"),
    Path("AGENTS.md"),
    Path("Docs/development/README.md"),
    Path("Docs/development/roadmap.md"),
    Path("Docs/development/knowledge-map.md"),
    Path("Docs/development/evidence/preparation-log.md"),
)
REQUIRED_PREPARATION_PATHS = (
    Path("README.md"),
    Path("AGENTS.md"),
    Path("Docs/development/README.md"),
    Path("Docs/development/backlog.json"),
    Path("Docs/development/knowledge-map.md"),
    Path("Docs/development/knowledge-graph.json"),
    Path("Docs/development/roadmap.md"),
    Path("Docs/development/status.json"),
    Path("Docs/superpowers/plans/2026-09-06-m0-first-slice.md"),
    Path("tools/devprep.py"),
    Path("tests/preparation"),
)


class MaterialError(ValueError):
    """Raised for an invalid preparation artifact."""


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise MaterialError(f"missing JSON file: {path.relative_to(ROOT)}")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MaterialError(f"cannot parse {path.relative_to(ROOT)}: {exc}") from exc
    if not isinstance(value, dict):
        raise MaterialError(f"JSON root must be an object: {path.relative_to(ROOT)}")
    return value


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _identity(value: Any) -> str | None:
    """The identity-bearing head of a declared actor, or None if none was declared.

    Entries are prose: "Boole (01a0...), 2026-09-07", "Codex main agent /root". The
    head before the first separator is the identity; a trailing date or note is not.
    """
    if not _nonempty(value):
        return None
    head = re.split(r"[,;(]", value.strip(), maxsplit=1)[0]
    return head.strip().casefold() or None


def _relative(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _without_fenced_code(text: str) -> str:
    lines: list[str] = []
    fence: str | None = None
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if fence is not None:
            if re.fullmatch(r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*", line.rstrip("\r\n")):
                fence = None
            lines.append("\n")
        elif marker:
            fence = marker.group(1)
            lines.append("\n")
        else:
            lines.append(line)
    return "".join(lines)


def _closing_bracket(text: str, start: int) -> int | None:
    depth, cursor = 1, start + 1
    while cursor < len(text):
        char = text[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char == "[":
            depth += 1
        elif char == "]":
            depth -= 1
            if depth == 0:
                return cursor
        cursor += 1
    return None


def _closing_link(text: str, start: int) -> int | None:
    depth, cursor = 1, start + 1
    quote: str | None = None
    angle = False
    while cursor < len(text):
        char = text[cursor]
        if char == "\n":
            return None  # This small validator supports single-line destinations.
        if char == "\\":
            cursor += 2
            continue
        if quote:
            if char == quote:
                quote = None
        elif angle:
            if char == ">":
                angle = False
        elif char in "\"'" and text[cursor - 1].isspace():
            quote = char
        elif char == "<":
            angle = True
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return cursor
        cursor += 1
    return None


def _markdown_destination(value: str) -> str | None:
    if not value.strip():
        return ""  # An empty inline destination refers to the current document.
    match = re.fullmatch(
        r"[ \t]*(?:<(?P<angle>[^<>\n]+)>|(?P<bare>(?:\\.|[^\s<>])+))"
        r"(?:[ \t]+(?:\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'|\([^()\n]*\)))?[ \t]*",
        value,
    )
    if match is None:
        return None
    target = match.group("angle") or match.group("bare")
    return re.sub(r"\\([!\"#$%&'()*+,\-./:;<=>?@\[\]^_`{|}~\\])", r"\1", target)


def validate_markdown_links(paths: Iterable[Path]) -> list[str]:
    """Check local file targets, not anchors or a complete CommonMark document.

    Supports inline links/images, quoted titles, angle/percent-encoded paths and
    full/collapsed/shortcut references with single-line definitions. Fenced and
    inline code are excluded. Recognized but unsupported link syntax fails
    closed; raw HTML/autolinks and document-anchor resolution are outside scope.
    """
    errors: list[str] = []
    for path in paths:
        try:
            text = _without_fenced_code(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError) as exc:
            errors.append(f"cannot read Markdown entry {path}: {exc}")
            continue

        def check_destination(value: str) -> None:
            target = _markdown_destination(value)
            if target is None:
                errors.append(f"{path}: unsupported local Markdown link syntax")
                return
            if not target or target.startswith(("#", "http://", "https://", "mailto:", "tel:", "//")):
                return
            try:
                local = unquote(target.split("#", 1)[0].split("?", 1)[0], errors="strict")
                candidate = (path.parent / local).resolve()
                if not candidate.exists():
                    errors.append(f"{path}: broken local Markdown link {local}")
            except (OSError, ValueError) as exc:
                errors.append(f"{path}: invalid local Markdown target ({type(exc).__name__})")

        # Normalize reference labels without interpreting surrounding prose as
        # links. Validate all definitions, including currently unused ones.
        references: set[str] = set()
        prose: list[str] = []
        for line in text.splitlines(keepends=True):
            definition = re.fullmatch(r" {0,3}\[([^\[\]\n]+)\]:[ \t]*(.*)", line.rstrip("\r\n"))
            if definition:
                label = " ".join(definition.group(1).split()).casefold()
                references.add(label)
                value = definition.group(2)
                if not value.strip():
                    errors.append(f"{path}: unsupported empty Markdown reference definition")
                else:
                    check_destination(value)
                prose.append("\n")
            else:
                prose.append(line)
        text = "".join(prose)
        cursor = 0
        while cursor < len(text):
            if text[cursor] == "\\":
                cursor += 2
                continue
            if text[cursor] == "`":
                run = re.match(r"`+", text[cursor:]).group()
                close = re.search(r"(?<!`)" + re.escape(run) + r"(?!`)", text[cursor + len(run):])
                if close:
                    cursor += len(run) + close.end()
                    continue
            if text[cursor] != "[":
                cursor += 1
                continue
            close = _closing_bracket(text, cursor)
            if close is None:
                cursor += 1
                continue
            label = text[cursor + 1:close]
            after = close + 1
            if after < len(text) and text[after] == "(":
                end = _closing_link(text, after)
                if end is None:
                    errors.append(f"{path}: unsupported or unclosed Markdown link syntax")
                    cursor = after + 1
                    continue
                if "[" in label or "]" in label:
                    errors.append(f"{path}: nested Markdown link labels are unsupported")
                check_destination(text[after + 1:end])
                cursor = end + 1
            elif after < len(text) and text[after] == "[":
                end = _closing_bracket(text, after)
                if end is None:
                    errors.append(f"{path}: unclosed Markdown reference link")
                    cursor = after + 1
                    continue
                reference = text[after + 1:end] or label
                if "[" in label or "]" in label:
                    errors.append(f"{path}: nested Markdown reference labels are unsupported")
                if " ".join(reference.split()).casefold() not in references:
                    errors.append(f"{path}: undefined Markdown reference {reference!r}")
                cursor = end + 1
            else:
                # Defined shortcut references were checked above. An undefined
                # standalone [label] is ordinary Markdown text, not a link.
                cursor = after
    return errors


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _counts_by_status(items: Iterable[dict[str, Any]]) -> Counter[str]:
    return Counter(str(item.get("status")) for item in items)


def _milestone_summary(items: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    summary: dict[str, dict[str, Any]] = {}
    for milestone in MILESTONES:
        group = [item for item in items if item.get("milestone") == milestone]
        counts = _counts_by_status(group)
        status = "done" if group and counts["done"] == len(group) else (
            "in_progress" if counts["in_progress"] or counts["review"] else (
                "blocked" if counts["blocked"] else "todo"
            )
        )
        summary[milestone] = {
            "status": status,
            "total": len(group),
            **{state: counts[state] for state in sorted(STATUS_VOCABULARY)},
        }
    return summary


def _find_cycles(items: list[dict[str, Any]]) -> list[list[str]]:
    dependencies = {
        item["id"]: item["depends_on"] for item in items
    }
    cycles: list[list[str]] = []
    visiting: list[str] = []
    visiting_set: set[str] = set()
    visited: set[str] = set()

    def visit(node: str) -> None:
        if node in visiting_set:
            start = visiting.index(node)
            cycles.append(visiting[start:] + [node])
            return
        if node in visited:
            return
        visiting.append(node)
        visiting_set.add(node)
        for dependency in dependencies.get(node, []):
            visit(dependency)
        visiting.pop()
        visiting_set.remove(node)
        visited.add(node)

    for node in dependencies:
        visit(node)
    return cycles


def _string_array(value: Any, *, allow_empty: bool = True) -> bool:
    return (
        isinstance(value, list)
        and (allow_empty or bool(value))
        and all(_nonempty(entry) for entry in value)
    )


def validate_backlog(backlog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    items = backlog.get("work_items")
    if not isinstance(items, list) or not items:
        return ["backlog.work_items must be a non-empty array"]

    # Validate shapes before hashing IDs or traversing relationships. In
    # particular, falsey JSON values must not be silently coerced to [].
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            errors.append(f"backlog.work_items[{index}] must be an object")
            continue
        item_id = item.get("id")
        label = item_id if _nonempty(item_id) else f"work_items[{index}]"
        if not _nonempty(item_id):
            errors.append(f"{label}: id must be a non-empty string")
        status = item.get("status")
        if not isinstance(status, str) or status not in STATUS_VOCABULARY:
            errors.append(f"{label}: invalid status {status!r}")
        if item.get("milestone") not in MILESTONES:
            errors.append(f"{label}: invalid milestone {item.get('milestone')!r}")
        for field in ("depends_on", "conformance_tests", "files", "acceptance", "evidence"):
            allow_empty = field in ("depends_on", "conformance_tests")
            if not _string_array(item.get(field), allow_empty=allow_empty):
                qualifier = "an array" if allow_empty else "a non-empty array"
                errors.append(f"{label}: {field} must be {qualifier} of non-empty strings")
        if status == "done":
            for field in ("acceptance_evidence", "reproduction_command", "independent_reviewer"):
                if not _nonempty(item.get(field)):
                    errors.append(f"{label}: done requires {field}")
            # Non-empty is not the same as independent. Where both identities are
            # declared and agree, the reviewer cannot have been a second party.
            executor = _identity(item.get("executor"))
            reviewer = _identity(item.get("independent_reviewer"))
            if executor is not None and executor == reviewer:
                errors.append(f"{label}: independent_reviewer must differ from the executor")
    if errors:
        return errors

    ids = [item["id"] for item in items]
    if len(ids) != len(set(ids)):
        return ["backlog work-item IDs are not unique"]
    by_id = {item["id"]: item for item in items}
    registered: set[str] = set()
    for item in items:
        item_id = item["id"]
        for dependency in item["depends_on"]:
            if dependency not in by_id:
                errors.append(f"{item_id}: dangling dependency {dependency}")
            elif item["status"] in {"ready", "in_progress", "done"} and by_id[dependency]["status"] != "done":
                errors.append(f"{item_id}: {item['status']} requires dependency {dependency} to be done")
            if dependency == item_id:
                errors.append(f"{item_id}: self dependency")
        tests = set(item["conformance_tests"])
        unknown_tests = sorted(tests - CONFORMANCE_IDS)
        if unknown_tests:
            errors.append(f"{item_id}: unknown conformance tests {unknown_tests}")
        registered.update(tests)
    cycles = _find_cycles(items)
    if cycles:
        errors.append("backlog dependency graph is cyclic: " + "; ".join(" -> ".join(c) for c in cycles))
    if registered != CONFORMANCE_IDS:
        errors.append(
            "backlog conformance registration mismatch: "
            f"missing={sorted(CONFORMANCE_IDS - registered)}, "
            f"unknown={sorted(registered - CONFORMANCE_IDS)}"
        )
    return errors


def validate_graph(graph: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    nodes = graph.get("nodes")
    edges = graph.get("edges")
    if not isinstance(nodes, list) or not nodes:
        return ["knowledge graph nodes must be a non-empty array"]
    if not isinstance(edges, list):
        return ["knowledge graph edges must be an array"]
    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"knowledge graph nodes[{index}] must be an object")
            continue
        for field in ("id", "type", "source", "summary"):
            if not _nonempty(node.get(field)):
                errors.append(f"knowledge graph nodes[{index}].{field} must be a non-empty string")
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            errors.append(f"knowledge graph edges[{index}] must be an object")
            continue
        for field in ("source", "target", "relation", "source_reference"):
            if not _nonempty(edge.get(field)):
                errors.append(f"knowledge graph edges[{index}].{field} must be a non-empty string")
    if errors:
        return errors

    node_ids = [node["id"] for node in nodes]
    if len(node_ids) != len(set(node_ids)):
        errors.append("knowledge graph node IDs are not unique")
    known = set(node_ids)
    seen_edges: set[tuple[str, str, str, str]] = set()
    for edge in edges:
        source, target = edge["source"], edge["target"]
        relation, source_reference = edge["relation"], edge["source_reference"]
        if source not in known:
            errors.append(f"edge has unknown source {source!r}")
        if target not in known:
            errors.append(f"edge has unknown target {target!r}")
        key = (source, relation, target, source_reference)
        if key in seen_edges:
            errors.append(
                "duplicate knowledge graph edge: "
                f"{source} -[{relation}]-> {target} ({source_reference})"
            )
        seen_edges.add(key)
    conformance_nodes = {node["id"] for node in nodes if node["type"] == "conformance"}
    if conformance_nodes != CONFORMANCE_IDS:
        errors.append(
            "knowledge graph conformance node mismatch: "
            f"missing={sorted(CONFORMANCE_IDS - conformance_nodes)}, "
            f"unknown={sorted(conformance_nodes - CONFORMANCE_IDS)}"
        )
    optional_transport_edges = [edge for edge in edges if edge["target"] == "concept-a2a"]
    if not any(edge["relation"] == "optionally_uses" for edge in optional_transport_edges):
        errors.append("A2A transport must be represented by an optionally_uses edge")
    if any(edge["relation"] == "depends_on" for edge in optional_transport_edges):
        errors.append("A2A transport must not be represented as a required depends_on edge")
    return errors


def validate_status(status: dict[str, Any], backlog: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if status.get("phase") != "preparation":
        errors.append("status.phase must remain preparation until product implementation starts")
    if status.get("product_completion_percent") != 0:
        errors.append("product_completion_percent must remain 0 during preparation")
    if status.get("bootstrap_status") in ("verified", "BOOTSTRAP_VERIFIED"):
        errors.append("preparation cannot claim BOOTSTRAP_VERIFIED")
    if status.get("bootstrap_status") != "not_started":
        errors.append("bootstrap_status must remain not_started during preparation")
    conformance = status.get("conformance")
    if not isinstance(conformance, dict):
        errors.append("status.conformance must be an object")
    else:
        counters: dict[str, int] = {}
        for field in ("registered_tests", "passed_tests", "failed_tests", "not_applicable_tests"):
            value = conformance.get(field)
            # bool subclasses int: True must not read as a count of 1.
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                errors.append(f"status.conformance.{field} must be a non-negative integer")
            else:
                counters[field] = value
        if conformance.get("status") not in ("registered", "passed"):
            errors.append("status.conformance.status must be registered or passed")
        if conformance.get("registered_tests") != len(CONFORMANCE_IDS):
            errors.append("status.conformance.registered_tests must equal 28")
        passed = conformance.get("passed_tests")
        if passed not in (0, len(CONFORMANCE_IDS)):
            errors.append("status.conformance.passed_tests must be 0 or 28")
        if passed == len(CONFORMANCE_IDS) and conformance.get("status") != "passed":
            errors.append("status.conformance.passed_tests=28 requires status passed")
        # The headline conclusion must agree with the count that supports it.
        if conformance.get("status") == "passed" and passed != len(CONFORMANCE_IDS):
            errors.append("status.conformance.status=passed requires passed_tests=28")
        # A full pass must name the evidence behind it. This checks only that the
        # reference is non-empty, not that the file exists: devprep's docstring
        # disclaims inferring product conformance from documents on disk.
        if conformance.get("status") == "passed" and not _nonempty(conformance.get("evidence")):
            errors.append("status.conformance.status=passed requires an evidence reference")
        # `registered` means no result exists yet - the record's own note says no
        # product test has been accepted as passed. Reporting any outcome under it
        # denies the status, and the sum guard cannot catch these cases: failed=28
        # alone, or failed=20 with not_applicable=8, sums to exactly registered_tests
        # and never exceeds it.
        if conformance.get("status") == "registered":
            for field in ("passed_tests", "failed_tests", "not_applicable_tests"):
                if conformance.get(field):
                    errors.append(
                        f"status.conformance.status=registered requires {field}=0"
                    )
        # The counters describe one set of results, so they cannot contradict each
        # other: nothing is both passed and failed, and a full pass leaves no room
        # for failures or non-applicable outcomes. One check covers both cases:
        # passed==registered with any failure implies the sum exceeds registered.
        if len(counters) == len(("registered_tests", "passed_tests", "failed_tests", "not_applicable_tests")):
            registered = counters["registered_tests"]
            accounted = counters["passed_tests"] + counters["failed_tests"] + counters["not_applicable_tests"]
            if accounted > registered:
                errors.append(
                    "status.conformance outcome counts contradict registered_tests: "
                    f"passed+failed+not_applicable={accounted} > registered={registered}"
                )
    items = backlog.get("work_items", [])
    expected_counts = dict(_counts_by_status(items))
    for state in STATUS_VOCABULARY:
        expected_counts.setdefault(state, 0)
    actual_counts = status.get("work_item_status_counts")
    if actual_counts != expected_counts:
        errors.append(
            "status.work_item_status_counts does not match backlog: "
            f"expected={expected_counts}, actual={actual_counts}"
        )
    expected_milestones = _milestone_summary(items)
    if status.get("milestones") != expected_milestones:
        errors.append("status.milestones does not match backlog-derived counts")
    expected_active = sorted(
        item["id"] for item in items if item.get("status") == "in_progress"
    )
    active = status.get("active_work_items")
    if not _string_array(active):
        errors.append("status.active_work_items must be an array of non-empty strings")
    elif sorted(active) != expected_active:
        errors.append("status.active_work_items does not match in_progress backlog items")
    return errors



def validate_skills() -> tuple[list[str], int]:
    """Validate portable project skill metadata and required navigation markers."""
    errors: list[str] = []
    for key, path in SKILL_PATHS.items():
        relative = _relative(path)
        if not path.is_file():
            errors.append(f"missing project skill: {relative}")
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
        except OSError as exc:
            errors.append(f"cannot read project skill {relative}: {exc}")
            continue
        if not text.startswith("---\n"):
            errors.append(f"{relative}: frontmatter must start with ---")
            continue
        end = text.find("\n---", 4)
        if end < 0:
            errors.append(f"{relative}: frontmatter closing delimiter is missing")
            continue
        frontmatter = text[4:end]
        name_match = re.search(r"(?m)^name:\s*([^\n]+)\s*$", frontmatter)
        description_match = re.search(r"(?m)^description:\s*(.+?)\s*$", frontmatter)
        if not name_match:
            errors.append(f"{relative}: frontmatter name is missing")
        else:
            name = name_match.group(1).strip().strip('"')
            if not re.fullmatch(r"[A-Za-z0-9-]+", name):
                errors.append(f"{relative}: skill name is not portable: {name!r}")
        if not description_match:
            errors.append(f"{relative}: frontmatter description is missing")
        else:
            description = description_match.group(1).strip().strip('"')
            if not description.startswith("Use when"):
                errors.append(f"{relative}: description must start with 'Use when'")
            if len(description) > 500:
                errors.append(f"{relative}: description exceeds 500 characters")
        for marker in SKILL_MARKERS[key]:
            if marker not in text:
                errors.append(f"{relative}: required marker missing: {marker}")
    return errors, len(SKILL_PATHS)

def validate_materials() -> tuple[list[str], dict[str, Any], dict[str, Any], dict[str, Any]]:
    errors: list[str] = []
    for relative in REQUIRED_PREPARATION_PATHS:
        if not (ROOT / relative).exists():
            errors.append(f"missing preparation path: {relative.as_posix()}")
    try:
        backlog = _load_json(BACKLOG_PATH)
    except MaterialError as exc:
        return [str(exc)], {}, {}, {}
    try:
        graph = _load_json(GRAPH_PATH)
    except MaterialError as exc:
        return errors + [str(exc)], backlog, {}, {}
    try:
        status = _load_json(STATUS_PATH)
    except MaterialError as exc:
        return errors + [str(exc)], backlog, graph, {}
    errors.extend(validate_markdown_links(ROOT / relative for relative in MARKDOWN_ENTRY_PATHS))
    backlog_errors = validate_backlog(backlog)
    errors.extend(backlog_errors)
    errors.extend(validate_graph(graph))
    skill_errors, _ = validate_skills()
    errors.extend(skill_errors)
    # Status derivation requires well-formed, unambiguous work items.
    if not backlog_errors:
        errors.extend(validate_status(status, backlog))
    return errors, backlog, graph, status


# Deliberately bounded stable-version formats, not a tool identity attestation.
# Build metadata is checked but never copied into reports or console output.
VERSION_PATTERNS = {
    "node": re.compile(r"(?P<version>v[0-9]+\.[0-9]+\.[0-9]+)"),
    "git": re.compile(r"(?P<version>git version [0-9]+\.[0-9]+\.[0-9]+)(?:\.windows\.[0-9]+)?"),
    "uv": re.compile(
        r"(?P<version>uv [0-9]+\.[0-9]+\.[0-9]+)"
        r"(?: \([0-9a-f]{7,40} [0-9]{4}-[0-9]{2}-[0-9]{2}"
        r"(?: [a-z0-9_]+(?:-[a-z0-9_]+){2,4})?\))?"
    ),
}


def _short_version(command: str, args: list[str]) -> dict[str, Any]:
    executable = shutil.which(command)
    if executable is None:
        return {"available": False, "version": None, "reason": "not_found"}
    try:
        completed = subprocess.run(
            [executable, *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        return {"available": False, "version": None, "reason": type(exc).__name__}
    result = {"available": False, "version": None, "returncode": completed.returncode}
    if completed.returncode != 0:
        return {**result, "reason": "nonzero_exit"}
    stdout, stderr = (completed.stdout or "").strip(), (completed.stderr or "").strip()
    pattern = VERSION_PATTERNS.get(command)
    # Do not choose a plausible stdout line while silently accepting unrelated
    # stderr or additional lines. Unknown output is never echoed, even on error.
    match = pattern.fullmatch(stdout or stderr) if pattern and not (stdout and stderr) else None
    if match is None:
        return {**result, "reason": "unrecognized_version_output"}
    return {**result, "available": True, "version": match.group("version")}


def collect_environment() -> dict[str, Any]:
    """Collect non-sensitive tool facts without inspecting environment variables."""
    return {
        "schema_version": "aetp-preparation-environment-0.1",
        "observed_at": _utc_now(),
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "python": platform.python_version(),
        },
        "tools": {
            "python": {
                "available": True,
                "version": platform.python_version(),
                "executable": sys.executable,
            },
            "node": _short_version("node", ["--version"]),
            "git": _short_version("git", ["--version"]),
            "uv": _short_version("uv", ["--version"]),
        },
        "workspace": {
            "root": _relative(ROOT),
            "git_repository_detected": (ROOT / ".git").exists(),
            "product_source_present": (ROOT / "src").exists(),
            "dependency_lock_present": any(
                (ROOT / filename).exists()
                for filename in ("uv.lock", "poetry.lock", "package-lock.json", "pnpm-lock.yaml")
            ),
        },
        "actions_performed": [],
        "limitations": [
            "仅采集版本和工作区事实；未读取凭证、环境变量或用户配置。",
            "脚本不安装依赖、不初始化 Git、不启动 Runtime。",
        ],
    }


def render_report(
    backlog: dict[str, Any] | None = None,
    status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if backlog is None:
        backlog = _load_json(BACKLOG_PATH)
    if status is None:
        status = _load_json(STATUS_PATH)
    items = backlog.get("work_items", [])
    registered = sorted({test for item in items for test in (item.get("conformance_tests") or [])})
    report = {
        "schema_version": "aetp-preparation-report-0.1",
        "generated_at": _utc_now(),
        "phase": status.get("phase"),
        "product_completion_percent": status.get("product_completion_percent"),
        "bootstrap_status": status.get("bootstrap_status"),
        "work_item_status_counts": dict(_counts_by_status(items)),
        "milestones": _milestone_summary(items),
        "conformance": {
            "status": status.get("conformance", {}).get("status"),
            "registered_tests": registered,
            "registered_count": len(registered),
            "passed_count": status.get("conformance", {}).get("passed_tests", 0),
            "evidence_is_product_acceptance": False,
        },
        "claims": {
            "product_implementation_complete": False,
            "bootstrap_verified": False,
        },
        "evidence_paths": status.get("evidence_paths", []),
        "limitations": status.get("limitations", []),
    }
    _write_json(REPORT_PATH, report)
    return report


def command_check() -> int:
    errors, backlog, graph, status = validate_materials()
    _, skill_count = validate_skills()
    if errors:
        for error in errors:
            print(f"ERROR {error}")
        return 1
    checked_at = _utc_now()
    common = {
        "schema_version": "aetp-preparation-check-0.1",
        "checked_at": checked_at,
        "command": "python tools/devprep.py check",
        "exit_code": 0,
        "product_acceptance": False,
        "bootstrap_verified": False,
    }
    _write_json(
        DEVPREP_CHECK_PATH,
        {
            **common,
            "validations": {
                "required_paths": "passed",
                "json_parse": "passed",
                "markdown_links": "passed",
                "markdown_link_scope": "selected entries; inline and single-line reference targets; excludes code, HTML/autolinks and anchors",
                "skills": {"status": "passed", "count": skill_count},
                "status_safety": "passed",
            },
        },
    )
    _write_json(
        GRAPH_CHECK_PATH,
        {
            **common,
            "graph": {
                "status": "passed",
                "nodes": len(graph["nodes"]),
                "edges": len(graph["edges"]),
                "dangling_edges": 0,
                "duplicate_edges": 0,
                "a2a_relation": "optionally_uses",
            },
        },
    )
    _write_json(
        BACKLOG_CHECK_PATH,
        {
            **common,
            "backlog": {
                "status": "passed",
                "work_items": len(backlog["work_items"]),
                "dependency_cycles": 0,
                "conformance_registered": len(CONFORMANCE_IDS),
                "status_counts": dict(_counts_by_status(backlog["work_items"])),
            },
        },
    )
    print(
        "OK "
        f"graph nodes={len(graph['nodes'])} edges={len(graph['edges'])}; "
        f"backlog items={len(backlog['work_items'])}; "
        f"skills={skill_count}; "
        "acyclic=yes; "
        f"status phase={status['phase']} product_completion_percent={status['product_completion_percent']}%"
    )
    return 0
def command_render() -> int:
    try:
        errors, backlog, graph, status = validate_materials()
        if errors:
            for error in errors:
                print(f"ERROR {error}")
            return 1
        report = render_report(backlog, status)
    except MaterialError as exc:
        print(f"ERROR {exc}")
        return 1
    print("AETP development preparation")
    print(f"phase: {report['phase']}")
    print(f"product_completion_percent: {report['product_completion_percent']}%")
    print(f"bootstrap_status: {report['bootstrap_status']}")
    print(f"conformance: {report['conformance']['status']} ({report['conformance']['registered_count']} registered, {report['conformance']['passed_count']} passed)")
    for milestone, summary in report["milestones"].items():
        print(f"{milestone}: {summary['status']} ({summary['done']}/{summary['total']} done)")
    print(f"report: {_relative(REPORT_PATH)}")
    return 0


def command_environment() -> int:
    report = collect_environment()
    _write_json(ENVIRONMENT_PATH, report)
    print("AETP development environment facts")
    for name, details in report["tools"].items():
        state = details.get("version") or "unavailable"
        print(f"{name}: {state}")
    print(f"workspace_git_repository: {report['workspace']['git_repository_detected']}")
    print(f"report: {_relative(ENVIRONMENT_PATH)}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "render", "environment"))
    args = parser.parse_args(argv)
    if args.command == "check":
        return command_check()
    if args.command == "render":
        return command_render()
    return command_environment()


if __name__ == "__main__":
    raise SystemExit(main())




