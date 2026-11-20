# M3-02 Integration Declaration Records Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Inline continuation is established; do not spawn new agents.

**Goal:** Implement the pure declaration evaluator and append-only Project record builder, without opening any runtime Command/Event ingress.

**Architecture:** `integration.records.evaluate(command, state, at, context)` returns one prospective `(event_kind, aggregate, project_id, record)` tuple in a list. It reads a validated prefix snapshot and historical ingress proof, makes detached copies, and never persists or authenticates capabilities. A future live service must verify the real Command/authenticated connection/receipt and invoke this inside the shared writer transaction; future Projection must independently validate the envelope, causal prefix and recomputed result.

**Tech Stack:** Python 3.14.6, stdlib unittest; existing PolicyViolation, digest_value, source_record and fixed-document policies. No dependencies.

**Spec:** `Docs/superpowers/specs/2026-09-15-m3-02-integration-contract-design.md`, especially §§4–5. This is an internal subset of the already user-approved architecture, not a new authorization scheme.

## Global Constraints

- M3-02 in_progress; 19 done / 1 in_progress. No edits to backlog/status; no original acceptance criterion is satisfied by this slice alone.
- Fixed schema `aetp-integration-contract-1`; maximum 64 Tasks and 64 versions per Task. Only `required`, no revocation or downgrade.
- Full Project revision and payload expected_task_revision; only prospective Project revision increments.
- No registered Commands/Events, service, state publication, integration guards, Git effects or Task success migration in this slice.
- No Git repository, therefore no worktree/commit/push; use pre-edit snapshot and bounded write set in place. ClaudeLink and original reviewer unavailable; no new agents, no independent acceptance claim.
- All command execution evidence uses the new `2026-09-16-m3-02-integration-record-*` stem and unique labels. Prior files stay frozen; MEMORY only appended.
- Supplied state is a validated prefix, not arbitrary caller JSON. Historical proof is data, not a live capability. Pure evaluation success does not authenticate a caller.

## Frozen internal interface / error ordering

`evaluate(command, state: dict, at: int, context: dict) -> list[tuple[str,str,str,dict]]`. Structural command fields: id, project_id, actor_id, type, target_id, payload, expected_revision, digest(). The type must equal `project.integration.declare`. Tests use a standalone frozen dataclass with the same canonical wire digest; it is NOT a domain Command and InputAuthority.issue must reject it. Do not subclass/bypass model validation or temporarily register a command.

Context exact fields: channel (required, existing `agent` ingress convention, also used for human commands) and input_proof (optional syntactically). No caller authority/owner/Session/barrier values. This module cannot verify the authenticated connection; ACTOR_MISMATCH remains a service responsibility.

Order: observed_time and target syntax → context/channel/type → Project existence/executable/candidate/pause → target Project match and strict Project revision → current Governance human_owner principal/role → source_record (complete matching proof, typed malformed proof INPUT_CONTEXT_INVALID; absent/unknown/untrusted or marked ancestor SOURCE_UNVERIFIED) → declaration payload syntax → same-project Task existence and strict Task revision → Task fixed policies, stage, owner/Binding/epoch/workspace consistency → current task-quality Policy present and no exemption → history validation/caps/version → detached prospective record.

Source guards reuse source_record; reject malformed unhashable exposure before set membership. Missing governance uses ENFORCEMENT_UNAVAILABLE; missing Task quality policy TASK_QUALITY_POLICY_REQUIRED. Durable binding mismatch STALE_EXECUTION; workspace mismatch WORKSPACE_MISMATCH; unsupported fixed policy POLICY_UNAVAILABLE. No author participant, live Lease validity or Session check is needed for human configuration. Binding must name the Task owner, current ID/epoch and workspace; expires/revoked lease and absent/stopped Session are not reactivated or changed.

New version fields: payload fields (including expected_task_revision), declared_by, command_id, observed_at_ms, project_revision, task_revision, criteria_digest, owner_id, current_binding_id, lease_epoch, workspace_provider_id, governance {owner_id,version,content_digest}, task_quality_policy {version,content_digest}, source, content_digest. Both revision fields pin the pre-declaration full revisions. Digest is `digest_value(record_without_content_digest)`; target Git OIDs remain unprefixed. Governance and Task quality digests are checked against their saved policy contents before pinning.

History shape `{schema,tasks}`; Task entry `{current_version,versions}`; canonical contiguous numeric string keys. Existing version task_id/version/supersedes/required/digest must agree. These structural checks do not replace independent causal replay. Malformed history INVALID_REFERENCE. Full 64-version history rejects any further attempt INTEGRATION_DECLARATION_LIMIT; new Task at 64 Tasks likewise. Otherwise version/predecessor must be current+1/current (or 1/null), else INTEGRATION_DECLARATION_VERSION_CONFLICT. Existing unrelated Task histories remain byte-semantically identical.

### Task 1: Initial declaration / authority snapshot

**Files:** create `src/aetp/integration/records.py`, `tests/m3/integration_record_support.py`, `tests/m3/test_integration_declaration_records.py`; modify `src/aetp/integration/contracts.py` (SCHEMA/MAX_TASKS only).
**Consumes:** `validate_declaration_payload`, existing trusted-prefix policies and source_record.
**Produces:** evaluate returning prospective Project record only.

- [x] Freeze/check previous closeout, 1067 baseline mappings / 505 blobs / 6 pins and all existing local sources before product edits (`...-preflight-v1.json`).
- [x] Write initial tests using a real QualityCase snapshot, remove current exemption via its existing Command, then close fixture with `doCleanups()` (not tearDown alone). Mutated snapshots are unit counterexamples, not admitted Events.
```python
effects = evaluate(command, state, at, context)
assert effects[0][:3] == ("project.integration_declared", "project", "p-1")
record = effects[0][3]
assert record["revision"] == state["project:p-1"]["revision"] + 1
assert state == before
assert version["content_digest"] == digest_value({k:v for k,v in version.items() if k != "content_digest"})
```
- [x] RED: `python Docs/development/evidence/2026-09-16-m3-02-integration-record-record.py initial_red_v1 -m unittest tests.m3.test_integration_declaration_records.InitialDeclarationTests -v` (missing API assertion).
- [x] Implement controls in the frozen order, derive pins and detached singleton history; preserve all other Project fields. Test cases: owner/type/role/source substitution, missing/marked proof, strict revisions, cross-project, supported stages, expired execution still configurable, binding mismatch, exemption uses current policy, no policy mutation.
- [x] GREEN: same class, label `initial_green_v1`; old input tests with a separate recorded label.

### Task 2: Append-only supersession / limits / purity

**Files:** extend records.py and same tests; no other production module.
**Consumes/Produces:** same evaluate interface; supports canonical version histories.

- [x] Add behavioral tests after Task 1 GREEN.
```python
first = evaluate(command1, state, at, context1)[0][3]
state2 = {**state, "project:p-1": first}  # detached simulation, never live State publication
second = evaluate(command2, state2, at, context2)[0][3]
assert second["integration_contract"]["tasks"]["t-1"]["versions"]["1"] == first["integration_contract"]["tasks"]["t-1"]["versions"]["1"]
assert second["integration_contract"]["tasks"]["t-1"]["current_version"] == 2
```
- [x] RED label `history_red_v1`: append/preserve, same/jump version rejection, 64-version/64-Task cap, malformed schema/key/pointer/digest, preserving old requirement across policy/owner/execution changes.
- [x] Implement copied-history validation and exact one-version append; no overwriting or eviction.
- [x] GREEN label `history_green_v1`: entire new module, plus deterministic JSON roundtrip and detached result. Guard file/path/subprocess/os/socket/time/sqlite/authority calls during evaluator only; this is not a sandbox or complete Replay proof.

### Task 3: Verification / author-only handoff

**Files:** update `src/aetp/integration/README.md`, this plan; new evidence, `artifacts/m3-02-integration-record-report-v1.json`; append MEMORY.

- [x] Document structural internal API, synthetic historical proof and missing runtime closure honestly; keep existing input APIs unchanged.
- [x] Run serial recorded M0/M1/M2/M3 suites after implementation. No edits to loaded inputs during a suite. Do not reuse previous 670 executions as current results.
- [x] Run `python tools/devprep.py render`, `python tools/devprep.py check`, `python -m unittest discover -s tests/preparation -v` via recorder, each exit 0 before claims.
- [x] Author review diff against frozen pre-edit sources; verify unrelated sources/shared files/old evidence unchanged and previous MEMORY prefix preserved.
- [x] Create exclusive new report/handoff/closeout with argv, times, exit codes, input blobs, true RED/GREEN counts, setup failures and remaining risks. No independent reviewer available: author_verified_pending_independent_review only. No Git branch integration possible.

## Self-review / explicitly deferred design groups

This covers deterministic subsets of A/B/C/D/E/F and no-I/O portion of G/M, not their live/transaction acceptance. Real input capability identity (including copied receipt), authenticated actor, transaction dual CAS/races/idempotency, all-service guards, Projection/envelope/causal validation, rejection-only git.merge, recovery/full-store/events-only/cache compatibility and independent review remain unimplemented. No design requirement is silently called complete. Next closed slice must wire these before registering either new Command.


## Execution notes (author, not independent review)

- Initial RED: 20 API-missing assertion failures; initial_green_v1 exit 1 was a candidate-only test fixture error (schema alone is not mode). Existing guard reads `planning.mode=candidate_only`; corrected fixture, no product guard change. initial_green_v2 20/20 and input_regression_v1 26/26.
- history_red_v1: missing history caused 25 assertion failures and two KeyError test errors. Added explicit old-version presence assertions before lookup, no production changes; history_red_v2 has 27 failing subtest/assertions across 9 of 11 methods, no errors. history_green_v1 31/31.
- Early direct fixture inspection called tearDown without unittest cleanup stack, causing a WinError 32 temporary SQLite cleanup warning after exit 0. New test support calls doCleanups in finally; recorded tests have clean stderr apart from unittest output. No manual deletion outside workspace was attempted.
- No fresh pre-edit full-suite baseline was rerun: prior immutable input-slice report/closeout and all source hashes were checked. Final full suites below will be fresh evidence for this slice.

Final author verification 2026-09-16T00:49:30.350297+08:00: M0 156, M1 85, M2 167, M3 266, preparation 27; 701 suite executions total (674 product + 27 preparation), 31 new record methods. render/check exit 0. Report `artifacts/m3-02-integration-record-report-v1.json`. No independent review; M3-02 stays in_progress.
