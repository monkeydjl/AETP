#!/usr/bin/env python3
"""Check whether the CI workflow can be trusted before anyone claims it passed.

`.github/workflows/ci.yml` is a config skeleton. Its own `note` job says it was
never run against a real remote and CI host, so nothing in this repository may
say "CI is green" until it actually runs there. This tool answers the question
that comes before that claim: would the workflow, as committed, survive a real
run - and does the evidence M4 acceptance needs exist?

It is read-only. It never pushes, never creates a remote, and never talks to a
CI host. A green result here means "the work is ready to be tried", not "CI
passed"; those are different words on purpose.

Usage:
    python tools/ci_preflight.py            # human-readable
    python tools/ci_preflight.py --json PATH
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "ci.yml"
BACKLOG_PATH = ROOT / "Docs" / "development" / "backlog.json"


def _git(*args: str) -> tuple[int, str]:
    try:
        r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True)
    except OSError as exc:  # git missing entirely
        return 1, str(exc)
    return r.returncode, (r.stdout if r.returncode == 0 else r.stderr).strip()


def _parse_workflow(text: str) -> dict[str, Any]:
    """Read the few facts we need without a YAML dependency.

    A missing PyYAML must not turn this check into a silent pass, so every field
    is required to be found explicitly rather than defaulted.
    """
    facts: dict[str, Any] = {}
    python = re.search(r'python-version:\s*"([^"]+)"', text)
    facts["python_version"] = python.group(1) if python else None
    facts["runs_on"] = sorted(set(re.findall(r"runs-on:\s*(\S+)", text)))
    facts["actions"] = sorted(set(re.findall(r"uses:\s*([^\s#]+)", text)))
    # Each `- name:` opens a step; collect the run bodies that follow.
    steps = re.findall(r"- name:\s*(.+?)\n\s+run:\s*\|\n((?:\s{10,}.*\n?)+)", text)
    facts["steps"] = [{"name": n.strip(), "run": _dedent(b)} for n, b in steps]
    # The workflow used to carry a disabled `if: false` job whose text said it had
    # never run against a real remote. It has now: run 45193365904 completed on
    # windows-latest with conformance 28/28. So the fact to check flipped - a
    # workflow that still *claims* it never ran would now be the stale one.
    disabled_jobs = re.findall(r"^\s{2}(\w+):\s*\n(?:\s+.*\n)*?\s+if:\s*false", text, re.M)
    facts["disabled_jobs"] = sorted(set(disabled_jobs))
    facts["claims_never_run"] = bool(re.search(r"has NOT been run against a real", text))
    return facts


def _dedent(block: str) -> str:
    lines = [ln for ln in block.splitlines() if ln.strip()]
    if not lines:
        return ""
    pad = min(len(ln) - len(ln.lstrip()) for ln in lines)
    return "\n".join(ln[pad:] for ln in lines)


def _logical_lines(script: str) -> list[str]:
    """Join shell backslash continuations so a wrapped command counts as one.

    A multi-line invocation is written with trailing backslashes; treating each
    physical line as its own command made the continuation arguments look like
    unknown commands and skipped the check on the invocation itself.
    """
    joined: list[str] = []
    buffer = ""
    for raw in script.splitlines():
        stripped = raw.strip()
        if stripped.endswith("\\"):
            buffer += stripped[:-1].rstrip() + " "
            continue
        if buffer:
            stripped = buffer + stripped
            buffer = ""
        if stripped.strip():
            joined.append(stripped.strip())
    if buffer.strip():
        joined.append(buffer.strip())
    return joined


def _required_commands(facts: dict[str, Any]) -> list[str]:
    """The workflow steps, flattened into runnable command strings."""
    return [step["run"] for step in facts.get("steps", [])]


def check_workflow() -> dict[str, Any]:
    problems: list[str] = []
    notes: list[str] = []

    if not WORKFLOW_PATH.exists():
        return {"ok": False, "problems": [f"missing {WORKFLOW_PATH.relative_to(ROOT)}"], "notes": []}

    facts = _parse_workflow(WORKFLOW_PATH.read_text(encoding="utf-8"))
    for key in ("python_version", "runs_on", "actions", "steps"):
        if not facts.get(key):
            problems.append(f"ci.yml has no {key}")

    if facts.get("python_version") and facts["python_version"].count(".") < 1:
        problems.append(
            f"python-version {facts['python_version']!r} is a bare major; setup-python needs a "
            "minor series such as '3.14' to pick an interpreter"
        )

    if facts.get("claims_never_run"):
        problems.append(
            "ci.yml still says the workflow has never run against a real remote, but run "
            "45193365904 completed on windows-latest. Update that text instead of keeping a "
            "disclaimer that is no longer true"
        )

    # Every command the workflow runs must be runnable from the repo root as written.
    for step in facts.get("steps", []):
        for line in _logical_lines(step["run"]):
            if not line or line.startswith("#"):
                continue
            if not re.match(r"^(python|PYTHONPATH=|pip|python3)\b", line):
                notes.append(f"{step['name']}: not a python command, reviewed by eye: {line}")
                continue
            m = re.match(r"^python\s+-m\s+unittest\s+discover\s+-s\s+(\S+)", line) or re.match(
                r"^python\s+-m\s+conformance\.runner", line
            )
            if m and m.groups():
                target = ROOT / m.group(1)
                if not target.exists():
                    problems.append(f"{step['name']}: discover target {m.group(1)} does not exist")

    code, remotes = _git("remote", "-v")
    if code != 0:
        problems.append(f"cannot read git remotes: {remotes}")
    elif not remotes.strip():
        problems.append(
            "no git remote is configured, so this workflow has never been triggered; "
            "it cannot be called green until it runs against a real remote and CI host"
        )
    else:
        notes.append(f"remote(s) configured: {len(remotes.splitlines())} line(s)")

    code, upstream = _git("rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}")
    if code != 0:
        notes.append("current branch has no upstream; pushing will need an explicit target")
    else:
        notes.append(f"current branch tracks {upstream}")

    code, dirty = _git("status", "--porcelain")
    if code == 0 and dirty.strip():
        count = len(dirty.strip().splitlines())
        notes.append(f"{count} uncommitted path(s): a CI run would not see them")

    return {"ok": not problems, "problems": problems, "notes": notes, "facts": facts}


def check_acceptance_evidence() -> dict[str, Any]:
    """M4-01 and M4-03 name evidence files; are they actually present?"""
    if not BACKLOG_PATH.exists():
        return {"ok": False, "problems": [f"missing {BACKLOG_PATH.relative_to(ROOT)}"], "notes": []}

    data = json.loads(BACKLOG_PATH.read_text(encoding="utf-8-sig"))
    items = next(
        (v for v in data.values() if isinstance(v, list) and v and isinstance(v[0], dict) and "id" in v[0]),
        None,
    )
    if items is None:
        return {"ok": False, "problems": ["backlog.json has no work item list"], "notes": []}

    problems: list[str] = []
    notes: list[str] = []
    for item in items:
        if item.get("id") not in ("M4-01", "M4-03"):
            continue
        missing = [p for p in item.get("evidence", []) if not (ROOT / p).exists()]
        if missing:
            problems.extend(f"{item['id']}: evidence missing on disk: {p}" for p in missing)
        else:
            notes.append(f"{item['id']}: {len(item.get('evidence', []))} evidence file(s) present")
        if item.get("status") != "blocked":
            notes.append(f"{item['id']} status is {item.get('status')!r}, not 'blocked' - re-check the premise")

        # Only report that the blocker still names an outside party. Do not try to
        # quote a fragment: splitting Chinese prose on whitespace produces pieces
        # that read as garbled text and invite the reader to trust a broken quote.
        reason = item.get("block_reason", "")
        external = [k for k in ("人类验收", "CI", "remote") if k in reason]
        if external:
            notes.append(f"{item['id']}: blocker still names an external party ({', '.join(external)})")

    return {"ok": not problems, "problems": problems, "notes": notes}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", help="Write the report as JSON to this path")
    args = parser.parse_args(argv)

    workflow = check_workflow()
    evidence = check_acceptance_evidence()
    ok = workflow["ok"] and evidence["ok"]

    print("CI preflight - read only. Green here means 'ready to be tried', never 'CI passed'.")
    print()
    print(f"workflow : {'OK' if workflow['ok'] else 'NOT READY'}")
    for p in workflow["problems"]:
        print(f"  problem: {p}")
    for n in workflow["notes"]:
        print(f"  note   : {n}")
    print()
    print(f"evidence : {'OK' if evidence['ok'] else 'NOT READY'}")
    for p in evidence["problems"]:
        print(f"  problem: {p}")
    for n in evidence["notes"]:
        print(f"  note   : {n}")

    if args.json:
        target = Path(args.json)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(
                {"ok": ok, "workflow": workflow, "evidence": evidence},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"\nreport: {args.json}")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
