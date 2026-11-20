# M3-02 Trusted Verification Implementation Plan

> **For agentic workers:** Use executing-plans for inline implementation. Reuse `/root/m1_reviewer` for independent review; do not create another agent. Steps are tracked below.

**Goal:** Build the first independently reviewable M3-02 prerequisite: authorized, immutable, recoverable fixed-document Verification.

**Architecture:** AcceptanceService extends PlanningService, with its own ResourceGate/context boundary and a fixed data-only Runner. Verification owns its Action and Case-set; the existing global recovery assessment sees unfinished verification actions. New pure reducers preserve old schemas and keep all Task completion gates closed.

**Tech Stack:** Python standard library, SQLite, Windows ResourceGate, unittest.

**Spec:** `Docs/superpowers/specs/2026-09-14-m3-02-verification-design.md`

## Global Constraints

- M3-02 remains in_progress until its unchanged three backlog criteria are independently accepted.
- No ClaudeLink or new agent; no Git initialization/commit/push, installation, network or global configuration changes.
- phase=preparation, product_completion_percent=0, bootstrap_status=not_started, complete Conformance 28 registered / 0 passed.
- No Task COMPLETED, Integration, Mission Acceptance or TEST-028 success is inferred from this first batch.
- Preserve M3-01 sources before edits; use new immutable run labels and retain failures. Tests run with PYTHONPATH=src.

## 1. Baseline, strict Runner and genuine failures

Create `Docs/development/evidence/2026-09-14-m3-02-record.py`, `2026-09-14-m3-02-baseline.py`, `tests/m3/test_verification_runner.py`, `src/aetp/acceptance/contracts.py`, `runner.py` and `__init__.py`.

Interface: `FixedJsonRunner.descriptor` returns version/source/environment snapshots; `run(content, cases)` returns `{observed_result, checks, diagnostic}`. Each Case has criterion/path/equals. Example:

```python
result = runner.run('{"enabled": true}', [{"criterion": "Enabled", "path": ["enabled"], "equals": 1}])
self.assertEqual(result["observed_result"], "FAILED")
```

- [x] Verify and archive accepted M3-01 inputs; mark M3-02 in_progress with agreed write set.
- [x] Write missing-feature assertions and hand-derived JSON boundary cases; record runner_red.
- [x] Implement only the fixed bounded checker; record runner_green.

## 2. Single-use authorization and live dispatch

Create `tests/m3/verification_support.py`, `test_verification_authority.py`, `src/aetp/acceptance/records.py`, `service.py`, `projection.py`, `causality.py`. Modify domain/models.py and core/commands.py/core/projection.py for explicit vocabulary, receipt addresses and reducers; add the narrow Runtime validation interface if needed.

Interface: `AcceptanceService(store, execution=..., owner_id=..., input_authority=..., clock=...)`; `handle(command, authenticated_actor_id=..., session=None, input_receipt=None)`; `dispatch(project_id, verification_id, session=...)`; `recover_verifications(project_id)`. Commands: project.quality.configure, artifact.capture, verification.request, verification.revoke, verification.dispatch, verification.record. Only host code can supply dispatch/result contexts. Capture is limited to a completed current document.write Action with full inherited and current ingress provenance. Governance explicitly routes verification.execute; marked/unknown and unsupported approval paths remain denied.

```python
self.request_verification("v-pass", cases=[{"criterion": "Scope", "path": ["scope"], "equals": "local"}])
self.service.dispatch("p-1", "v-pass", session=self.qa_session)
self.assertEqual(self.state()["verification:v-pass"]["result"], "PASSED")
self.assertEqual(self.state()["task:t-1"]["status"], "in_progress")
```

- [x] Record authority_red for human Policy, independent execution Task, real Session, pinned Case-set and Agent-report rejection.
- [x] Implement request/configuration/revoke, then durable dispatch → actual Runner → report/terminal transaction.
- [x] Record authority_green; prove request and dispatch retries do not cause a second run.

## 3. Recovery, races and fact integrity

Create `tests/m3/test_verification_recovery.py`, `test_verification_replay.py`; modify `src/aetp/governance/controls.py` to expose unfinished nested Verification Action IDs in existing unknown_actions.

```python
self.dispatch_then_lose_result("v-lost")
self.assertFalse(self.execution.recovery_status("p-1")["checks"]["ready"])
self.service.recover_verifications("p-1")
self.assertEqual(self.state()["verification:v-lost"]["result"], "INCONCLUSIVE")
```

- [x] Record recovery_red_v2, integrity_red and replay_red; retain the earlier fixture failures separately. Cover revoke/pause/stale epoch, changed snapshots/Policy, crash/transaction rollback and duplicate dispatch.
- [x] Implement explicit recovery with no rerun; retain observations and exact reasons.
- [x] Verify missing receipts, resealed actors/reports, orphan evidence, duplicate terminal and atomic cursor failures.
- [x] Record recovery_green, integrity_green, replay_green and process_checks; include real process exit and cross-process contention at the durable grant boundary.

## 4. Demonstration and compatibility

Create `src/aetp/acceptance/README.md`, `Docs/development/evidence/2026-09-14-m3-02-demo.py`, a new `artifacts/m3-02-verification-demo-v1*` family and first-batch implementation report.

- [x] Produce actual PASSED, FAILED and INCONCLUSIVE fixed-document examples with full evidence and independent QA Binding; keep Task states uncompleted.
- [x] Replay new full/facts-only stores and all six accepted M3/M2 stores read-only with Runner/Runtime/IO guards.
- [x] Run M3/M2/M1/M0 suites, compile and preparation render/check/tests; record every actual count and exit code.

## 5. Independent review and continuing handoff

- [x] Freeze this first-batch candidate with immutable source and evidence references.
- [x] Hand the frozen candidate to the original reviewer in an independent copy; address findings with preserved RED/GREEN evidence.
- [x] Consume only a genuine independent result; keep M3-02 in_progress and all unexecuted Conformance unpassed.
- [x] Append MEMORY and a complete handoff with files, exact commands/results, evidence, scope limits and next Task-quality design step.

No automatic commit or branch operation is part of this plan.
