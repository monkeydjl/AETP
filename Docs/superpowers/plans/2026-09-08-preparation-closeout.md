# AETP Preparation Closeout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans for applicable implementation work; this round primarily uses requesting-code-review for acceptance-only work. Steps use checkbox syntax for tracking.

**Goal:** Close PREP-003/004/006/007 only with real independent preparation-level acceptance, then independently review PREP-008; do not begin M0.

**Architecture:** Following the user's one-subagent limit, retain only Kant and reuse that independent reviewer serially. Zeno's completed PREP-006 review is historical evidence; Rawls was closed after a concurrency error without a conclusion. The main session handles source fixes, the single backlog/status write set, reproducible verification and final handoff. Kant (different from the executor, not a new independent identity on each reuse) also audits the integrated PREP-008 deliverable.

**Tech Stack:** Existing Python standard library preparation tools and Markdown/JSON; no new dependencies.

**Spec:** `AGENTS.md`, `Docs/development/README.md`, acceptance and dependencies in `Docs/development/backlog.json`; normative navigation through `Docs/development/knowledge-map.md`.

## Global constraints

- Only preparation acceptance is in scope; `product_completion_percent=0`, `bootstrap_status=not_started`, Conformance remains 28 registered / 0 passed.
- Independent review is not gated on implementing a product Runtime; it checks preparation acceptance criteria and scenario navigation, without calling that product behavior verification.
- No protocol changes, Git initialization, commits/pushes, dependency installs, global configuration changes or external side effects.
- ClaudeLink is unavailable. Coordinate these session agents explicitly; do not claim cross-terminal coordination or an atomic backlog lease.
- No Git/worktree is available. Record source SHA-256 values; reject stale shared-file snapshots before a write. This is change detection, not cross-process locking.
- Reviewers never write backlog/status, source files or shared generated reports. Any CLI/test verification by a reviewer uses a private temporary copy containing only project materials, not user configuration.
- On a real defect: reproduce RED, make the smallest scoped fix, verify GREEN and obtain a fresh independent conclusion for changed sources.

## Task 1: Independent preparation reviews

**Evidence files (initial assignments retained historically; remaining reviews run serially with Kant):**
- `Docs/development/evidence/2026-09-08-prep-003-004-review.json`
- `Docs/development/evidence/2026-09-08-prep-006-review.json`
- `Docs/development/evidence/2026-09-08-prep-007-review.json`

**Inputs:** Actual backlog acceptance criteria, relevant Skill/source files and prior review findings.
**Output interface:** Each JSON report records reviewer identity, start/end times, work-item assessments, each acceptance criterion, scenario/probe results, findings with severity and source location, exact commands/exit codes, source hashes and limitations. Assessment is `preparation-level pass` or `changes_required`; no fabricated product pass.

- [x] Agree scopes and capture initial source/state hashes; later record the user's one-subagent limit.
- [x] PREP-003/004 reviewer independently applies both Skills to the recorded pressure scenarios and finds the original normative sections.
- [x] PREP-006 reviewer rechecks prior R1/R2/R3 findings, test discovery/fixtures, exact write sets, evidence paths and phase boundaries.
- [x] PREP-007 reviewer audits current check/render/environment code, fail-closed behavior and regression evidence; execute tests only in a private copy.

## Task 2: Integrate findings and preparation evidence

**Main-session write set:** Existing Skill evidence Markdown, `Docs/development/evidence/2026-09-08-preparation-closeout.json`, a dated handoff, `Docs/development/backlog.json`, `Docs/development/status.json`, `MEMORY.md`, this plan and standard generated reports. Edit Skill/plan/tool/test source only for verified review defects, with scope communicated first.

- [x] Assess reviewer feedback against the actual acceptance requirements; do not turn absence of product implementation into a circular PREP blocker.
- [x] If required, fix verified defects using RED → GREEN and ask the sole retained independent reviewer to re-review (preserving original findings).
- [x] Verify reviewed source hashes, record real status transitions and per-item independent acceptance; update derived status counts from backlog.
- [x] Preserve historical evidence and clearly date superseding conclusions; do not silently rewrite old failure records.

## Task 3: PREP-008 independent integrated handoff

**Files:** `Docs/development/evidence/2026-09-08-preparation-handoff.md`, `Docs/development/evidence/2026-09-08-prep-008-review.json`, updated closeout log, backlog/status, plan and memory.

- [x] After PREP-002..007 dependencies are done, move PREP-008 through ready/in_progress/review and prepare the integrated handoff.
- [x] A separate reviewer audits acceptance evidence, identities, source-hash applicability, scope and honest product/environment limitations.
- [x] Only a real preparation-level pass permits PREP-008 done; otherwise retain review and describe the remaining work.
- [x] Mark M0-01 ready only if PREP-008 is done; ready is not execution or environment authorization. Do not create product files.
- [x] Refresh the memory snapshot and handoff with final actual states and verification, without claiming automatic memory loading.

## Verification and final handoff

Run and record full stdout/stderr, timestamps and exit codes:

```powershell
python tools/devprep.py render
python tools/devprep.py check
python -m unittest discover -s tests/preparation -v
```

The test suite also refreshes environment and preparation reports. Validate JSON, reviewed-source hashes and updated document paths. Final handoff includes work IDs, changed files, commands, evidence, independent reviewers, uncovered risks and the next authorized action; no automatic commit/push.

## 2026-09-09 final-regression extension (preparation only)

The first done/ready finalization exposed a fixture bug: the positive dependency test demotes PREP-003 while live PREP-008 stays done. The dependency validator is correct. PREP-007/008 are reopened to review and M0-01 returned to todo; prior acceptance entries above are historical, not current closeout.

- [x] Reproduce the actual positive test against pre-closeout and completed-PREP synthetic snapshots; preserve RED.
- [x] Isolate only this test fixture from live operational statuses/acceptance metadata; do not change tool behavior or plan contracts.
- [x] Verify GREEN with the regression probe, existing material probes, full preparation suite and a completed-PREP private snapshot.
- [x] Freeze a supplemental handoff, preserve old immutable reports/index, and obtain Kant's fresh independent PREP-007/008 applicability review.
- [x] Only after supplemental pass restore PREP-007/008 done and M0-01 ready, then run the full suite against actual final state.
- [x] Update current MEMORY and append dated handoff; preserve both actual failed finalization and successful follow-up evidence.
