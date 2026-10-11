# Integration contract boundary (M3-02)

This is a bounded, author-verified contract slice, not real Git Integration or
full M3-02 acceptance. Independent review remains pending.

## Supported entry and facts

`IntegrationContractService(TaskQualityService)` accepts
`project.integration.declare` from the current governance `human_owner`, with a
real configured `InputAuthority` receipt. Receipt object identity, Command digest,
actor and input provenance are checked at ingress, never reconstructed from JSON.
The resource gate is acquired before the shared SQLite writer. Current Project
`expected_revision` and payload `expected_task_revision` are checked together
against facts within that writer. No author Session is acquired or revived.

The sole success effect is `project.integration_declared`, with the exact
`aetp-integration-contract-1` envelope. It appends one immutable version under
`Project.integration_contract.tasks[task_id]`, advancing only Project revision.
Task stage, full revision, quality evidence, Lease and Binding are unchanged.
Declaration targets are data-only fixed OID/ref intent: no repository is opened.
The registry permits at most 64 Tasks and 64 versions per Task. Prior versions
cannot be removed, rewritten or downgraded. Staleness never restores exemption.

`validation.py` validates syntax only; `records.evaluate` deterministically
constructs a detached record and does not authenticate a live caller. Their older
DraftCommand tests remain pure fixtures, not authoritative receipt evidence.

## Shared fail-closed behavior

`git.merge` is registered **only as a typed rejection request**. The common
CommandHandler guard checks supported Project/Task, current Task owner and
revision, payload syntax, and the current declaration reference:

- no declaration: `INTEGRATION_DECLARATION_REQUIRED`;
- mismatched version/digest: `INTEGRATION_DECLARATION_STALE`;
- otherwise: `ENFORCEMENT_UNAVAILABLE`.

There is no merge Provider, dispatch, Action, success, conflict or UNKNOWN path.
The rejection does not require or grant an execution Session.

The shared guard also prevents `task.complete` / `task.quality.complete` for a
required Task (`INTEGRATION_REQUIRED`) and rejects configuration that restores a
current exemption (`INTEGRATION_SCOPE_CONFLICT`). Declaration and a current
standalone exemption are mutually exclusive. The guards run after original-result
idempotency lookup, inside the final writer, across legacy service entries.
A retry returns its original result without restoring old configuration.

## Replay, recovery and atomicity

`projection.reduce_record` independently recomputes the complete Project record
from the preceding prefix and exact Command/context/envelope. Merely naming the
Event as a declaration cannot bypass registry guards. `IntegrationCursor` binds
receipts, scope, digest, revisions, one effect and a single terminal result.
All five causal cursors, State, seen IDs and sequence publish only after every
check succeeds. Quality compound effects cannot be interleaved.

Full-store pending detection compares success bodies and rejection diagnostics
with the persisted Command. Events-only recovery cannot infer a rejected
Command's `expected_revision` from its digest, but validates the typed envelope,
address, current revision and causal receipt; full-store recovery additionally
binds the original precondition. Neither path calls an authority, runtime, clock,
network or subprocess to replay facts.

Registry-bearing aggregate caches cannot substitute for causal history; they
force rebuilding from facts. Old histories receive no default Integration key.
Command, receipt, effect and result are committed atomically. Tests cover actual
SQLite Event/result failures, original-key retry, cache loss/corruption, read-only
recovery, and two independently spawned processes competing on one revision or
on declaration versus exemption. Test processes are local deterministic fixtures,
not autonomous collaborating Agents or Conformance evidence.

## Limits and evidence

No READY_FOR_INTEGRATION, INTEGRATING, INTEGRATED or SYSTEM_VERIFIED transition;
no real merge or new system Verification; no Mission Acceptance, TEST-028,
Bootstrap or full M3-02 acceptance. Live contracts and older input/record/guard
slices are still pending independent review.

Design: `Docs/superpowers/specs/2026-09-15-m3-02-integration-contract-design.md`.
Current plan: `Docs/superpowers/plans/2026-09-16-m3-02-integration-live-contract.md`.
Run log: `Docs/development/evidence/2026-09-16-m3-02-integration-live-development.jsonl`.
Final author report (when generated): `artifacts/m3-02-integration-live-report-v1.json`.
