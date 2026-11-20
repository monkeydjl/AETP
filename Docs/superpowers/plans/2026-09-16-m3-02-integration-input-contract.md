# M3-02 Integration Input Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Build deterministic, strict input validators for the Integration prerequisite, without opening a Command or an execution path.

**Architecture:** This is the independently testable input-only subproject of the full design, not a durable Integration implementation. Pure functions accept JSON-compatible dictionaries, return detached validated data without normalization, and raise the existing `PolicyViolation("INVALID_PAYLOAD")` for unsupported syntax. Later live/replay evaluators must call them and separately enforce identity, current state and transactions.

**Tech Stack:** Python 3.14.6 here, standard-library unittest; existing Python package under `src`, no new dependencies.

**Spec:** `Docs/superpowers/specs/2026-09-15-m3-02-integration-contract-design.md` §§4.1, 6.2, 12; original §§7.3, 10.6, 14.1–14.2 remain authoritative.

## Global Constraints

- M3-02 remains in_progress; 19 done / 1 in_progress; original three acceptance conditions unchanged.
- phase=preparation; product_completion_percent=0; bootstrap_status=not_started; full Conformance 28 registered / 0 passed; full M1 not_accepted.
- No Git initialization/commit/push, dependency installation, global configuration, network, Provider, Runner, Task state transition or new authority.
- No Command/Event vocabulary registration in this slice. Valid syntax is neither authentication nor authorization, repository existence nor a verified commit.
- ASCII provider/repository IDs: `[A-Za-z0-9][A-Za-z0-9_-]{0,127}`. Branch refs: at most 255 ASCII characters, `refs/heads/` followed by `[A-Za-z0-9_][A-Za-z0-9_-]*` components separated by single `/`; source and target differ.
- Git sha1/sha256 OIDs: exactly 40/64 lowercase hex characters, nonzero. Declaration content digest: `sha256:` plus 64 lowercase hex characters; never confuse these namespaces.
- Version 1–64; supersedes_version null for 1, otherwise version-1. Current version sequencing and 64-Task history capacity are deferred to the durable evaluator.
- expected_task_revision: strict integer 0 through 2**63-1, not bool; actual current full revision checked later in a single writer transaction.
- Task ID: existing `text(identifier=True, limit=512)` UTF-8 byte limit. reason: 1–2048 Unicode scalar characters, not whitespace-only, preserve exact input including surrounding whitespace.
- Every object level has an exact field set; no caller authority/status/result/binding/policy overrides. Never mutate input or alias a nested returned mapping.
- ClaudeLink unavailable; old reviewer not addressable by a current agent ID; no new agent. Author self-check is not independent review. No shared backlog/status edits without coordination.
- Workspace is not a Git repository; work in place with immutable run-source blobs. Historical evidence and MEMORY prefix remain intact; unique labels only.

## File map and API

Create:
- `src/aetp/integration/__init__.py`: package description only; no registration/import side effects.
- `src/aetp/integration/contracts.py`: fixed input limits (no Service/Event vocabulary).
- `src/aetp/integration/validation.py`: `validate_target(value: object) -> dict`, `validate_declaration_payload(value: object) -> dict`, `validate_merge_payload(value: object) -> dict`.
- `src/aetp/integration/README.md`: supported syntax, exact non-goals, next integration points.
- `tests/m3/test_integration_contract_inputs.py`: three unittest classes, table-driven independent fixtures; dynamic import assertion for an intentionally absent API in RED.
- `Docs/development/evidence/2026-09-16-m3-02-integration-input-record.py`: adapted serial recorder; snapshots actual inputs before each command, captures raw output, argv/cwd/time/exit code, exclusive run labels.
- New evidence under `Docs/development/evidence/2026-09-16-m3-02-integration-input-*` and summary `artifacts/m3-02-integration-input-report-v1.json`.
Modify only the existing Integration design (dated author self-review), generated preparation reports via required commands, and append MEMORY at handoff. No old source/test files, accepted evidence, main specification, graph, backlog or status edits.

Shared dependencies: `PolicyViolation` and `text` from collaboration.policy; `fields` from governance.policy; `natural` from meetings.policy. Both live and pure replay consumers later receive fresh dictionaries from these functions, not trusted capability objects.

## Preparation checkpoint

- [x] Read inputs, architecture, original spec, and immutable baseline; no unexpected protected changes since preflight-v2.
- [x] Archive previous design; author self-review fixes prefixed digest, Unicode length and date references; independent review pending.
- [x] Record existing M3 baseline using recorder label `baseline_m3_v1`.

Recorder prefix for commands below:
`python Docs/development/evidence/2026-09-16-m3-02-integration-input-record.py <label>`.
It runs Python with `-B`, `PYTHONPATH=src`, UTF-8 and no bytecode writes, saving all raw output and pre-run source blobs.

### Task 1: Fixed target syntax (TargetInputTests)

**Files:** create package, contracts, validation and test file from file map.
**Consumes:** exact target shape in design §4.1.
**Produces:** `validate_target(value: object) -> dict`, detached JSON-compatible target or typed rejection.

- [x] Write failing tests with this hand-built fixture:

```python
value = {"provider_id": "future_git_provider", "repository_id": "project_repository",
         "object_format": "sha1",
         "source": {"ref": "refs/heads/agent/task_042", "commit": "1" * 40},
         "target": {"ref": "refs/heads/main", "expected_commit": "2" * 40}}
self.assertEqual(validate_target(value), value)
# Negative table: missing/extra fields at each level; wrong containers;
# URL/path/Unicode IDs; ref traversal/shell/space/dots; equal refs;
# short/symbolic/uppercase/all-zero/mixed-format OIDs.
```

- [x] Run label `target_red_v1`, args `-m unittest tests.m3.test_integration_contract_inputs.TargetInputTests -v`. Expected assertion failure: input validation module missing; unrelated import errors must propagate.
- [x] Implement only target shape/ID/ref/OID checks using fullmatch, type checks before membership, and fresh nested dict construction. No Git validation subprocess.
- [x] Run identical args under `target_green_v1`; require exit 0. Test legal maximum/one-over lengths and mutation isolation; do not substitute source-text assertions.

### Task 2: Declaration payload (DeclarationInputTests)

**Files:** extend validation/contracts/test file only.
**Consumes:** `validate_target`; legacy text/natural/fields validators.
**Produces:** `validate_declaration_payload(value: object) -> dict` (not a signed declaration record).

- [x] Add tests using exact payload:

```python
payload = {"task_id": "task_042", "expected_task_revision": 7,
           "version": 1, "supersedes_version": None, "requirement": "required",
           "target": target_fixture(), "reason": "  需要集成  "}
self.assertEqual(validate_declaration_payload(payload), payload)
# Later version: version=64, supersedes_version=63 accepted syntactically.
# Reject bool/floats/string revisions, version=65, predecessor mismatch,
# optional/exempt, blank/surrogate/2049-character reason, extra authority keys.
```

- [x] Run label `declaration_red_v1`, args `-m unittest tests.m3.test_integration_contract_inputs.DeclarationInputTests -v`; expect missing function assertion, not a fixture/import error.
- [x] Implement exact seven fields, strict natural numbers, local predecessor relation, required-only value, character-limit reason preserving original, task ID and recursive target validation. Return fresh nested target.
- [x] Run all input tests under `declaration_green_v1`; require exit 0 and original input unchanged on invalid cases. Actual state equality/CAS remain explicitly unimplemented.

### Task 3: Merge reference input (MergeInputTests)

**Files:** extend validation/test file; add README.
**Consumes:** fixed version limit; content-digest convention `digest_value` (not called to derive test expectations).
**Produces:** `validate_merge_payload(value: object) -> dict`; no successful `git.merge` command handler.

- [x] Add positive literal `{"declaration_version": 1, "declaration_digest": "sha256:" + "a" * 64}` and version 64. Reject bare/upper/short/space digest; bool or out-of-range version; source/target/result/ready/authority extras; wrong containers and omissions. Prove valid reference input does not resolve a declaration or execute anything.
- [x] Run label `merge_red_v1`, args `-m unittest tests.m3.test_integration_contract_inputs.MergeInputTests -v`; expect missing function assertion.
- [x] Implement exact two fields, natural version and prefixed digest fullmatch; no state lookup or I/O.
- [x] Run full input suite under `merge_green_v1`; require exit 0.
- [x] Document syntax-only behavior and next steps, including trusted ingress/owner checks, double CAS, immutable Project registry, no-revocation limit, mutually exclusive exemption, common guards and full replay wiring. Do not claim these are implemented.

## Final checkpoint and evidence

- [x] Run all product suites separately with recorder labels `suite_m0_v1`, `suite_m1_v1`, `suite_m2_v1`, `suite_m3_v1`: `-m unittest discover -s tests/mN -v`.
- [x] Run required preparation commands with labels `render_v1`, `check_v1`, `preparation_v1`: `tools/devprep.py render`; `tools/devprep.py check`; `-m unittest discover -s tests/preparation -v`.
- [x] Inspect real outputs, hashes and missing coverage, verify immutable baseline/pins and unchanged existing source; write author report and append MEMORY. No independent acceptance/done claim.

## Coverage self-review / explicit remaining work

This plan implements only design test group C's input portion and the static syntax in §6.2. Tasks 1–3 cover every stated rule of that subproject; no placeholder implementations. Full design groups A/B/D–N and C's project history capacity still need separate sequenced plans. Do not mark full contract complete just because all boxes here are checked.

Next coherent slice: pure declaration evaluator + immutable record; then live service and shared guard/Projection wiring as one closed transactional path before registering new Command vocabulary. Test RED for current human owner/ingress, no lease required for declaration, exemption conflict, Task and Project revisions and illegal stages. Later add rejection-only git.merge, all old-entry guards, malicious replay, real process races and historical-prefix compatibility. These are dependencies, not steps falsely claimed executed here.

Execution chosen: inline continuation as already announced; author will not re-ask the user to choose execution mode. No commit step because project authorization explicitly prohibits automatic commits.

## Execution checkpoint (2026-09-16)

Tasks 1–3 completed locally with recorded expected RED and GREEN (11, then 21, then 26 passing methods); baseline M3 209 passed. Full regressions are running. Baseline discovery started before the new test/module files existed and overlapped target/declaration work; its frozen 209-test source set contains only unchanged pre-existing code. It is not evidence for the new validators. Final regressions will use the completed frozen input set. The recorder has unique per-run directories but no cross-process label claim mechanism; journal order reflects actual finish order.

Author implementation self-check: exact field validation, fullmatch (including trailing-newline rejection), strict int checks, Unicode scalar/byte limits, non-aliasing, and no registration/I/O reviewed. No independent review was performed.

## Final verification checkpoint

M0 156, M1 85, M2 167, M3 235, preparation 27 passed (670 suite methods including 26 new input tests); render/check exit 0. Three expected RED runs remain immutable. Author-only verification; independent review pending. Full Integration contracts and original M3-02 acceptance remain unimplemented/unaccepted. Evidence: `artifacts/m3-02-integration-input-report-v1.json`.
