# M1-01 Collaboration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking. The main agent implements inline; one independent reviewer is reused serially. User authorization is to continue the established backlog without ClaudeLink.

**Goal:** Deliver direct peer communication and an auditable candidate Artifact / Review / Verification chain, with unavailable execution gates closed.

**Architecture:** Keep process messages in an in-process MessageBus. Extend the existing Command / Event / Projection chain for immutable candidate documents and independent review; record actual deterministic precheck output with an INCONCLUSIVE formal Verification until M1-02 supplies execution authorization.

**Tech Stack:** Existing Python standard library, unittest, SQLite. No new dependencies.

**Spec:** `Docs/superpowers/specs/2026-09-11-m1-01-collaboration-design.md`

## Global Constraints

- Policy `m1-document-candidate-v1`; only bounded inline public/internal documents and effect-free checks.
- No ClaudeLink, at most one subagent, no Git initialization/commit/push or global configuration changes.
- No Task VERIFIED / COMPLETED, fake Binding, fake Action authorization, or full TEST-028 acceptance.
- Ordinary Message does not enter Event Store; authoritative writes retain current transactions, immutable history, actor checks and idempotency.
- Work in the existing non-Git workspace; snapshot sources before edits and preserve historical M0 evidence.

## Task 1: Peer communication

**Files:** Create `src/aetp/collaboration/__init__.py`, `messages.py`, `tests/m1/__init__.py`, `support.py`, `test_messages.py`.

**Interfaces:** `Message(...)`; `MessageBus(store).send(message, authenticated_actor_id=...)`; `inbox(project_id, authenticated_actor_id=...)`; `snapshots(project_id, message_ids, authenticated_actor_id=...)`.

- [x] Capture source hashes and run the existing M0 baseline.
- [x] Write failures for bidirectional communication without a Task, replies/challenges, membership/identity/reference checks, immutable message IDs and source propagation.

```python
before = store.read_events("p-1")
bus.send(proposal, authenticated_actor_id="a-1")
bus.send(challenge, authenticated_actor_id="a-2")
self.assertEqual(bus.inbox("p-1", authenticated_actor_id="a-1")[0].type, "challenge")
self.assertEqual(store.read_events("p-1"), before)
```

- [x] Run `python -m unittest tests.m1.test_messages -v` and preserve RED output.
- [x] Implement immutable process records, trusted actor membership checks, traceable references and inbox access.
- [x] Run the same tests and preserve GREEN output.

## Task 2: Candidate Artifact and independent Review

**Files:** Create `collaboration/contracts.py`, `policy.py`, `records.py`, `projection.py`, `service.py`, `tests/m1/test_evidence_chain.py`; modify only `domain/models.py` and `core/projection.py` for shared vocabulary and pure reduction.

**Interfaces:** `CollaborationService(store, messages=None).handle(command, authenticated_actor_id=...) -> CommandResult`; commands `task.create`, `artifact.submit`, `review.request`, `review.submit`; fixed Policy metadata and immutable snapshot records.

- [x] Write failures for real task/candidate creation, server-computed content digest, pinned conversations, versioned replacement, non-owner registration, independent review, rejected self-review, stale targets, approvals and unknown capabilities.

```python
before_owner = store.read_projection("p-1")["task:t-1"]["owner_id"]
result = service.handle(review_by_b, authenticated_actor_id="a-2")
self.assertEqual(result.status, "accepted")
self.assertEqual(store.read_projection("p-1")["task:t-1"]["owner_id"], before_owner)
```

- [x] Record `python -m unittest tests.m1.test_evidence_chain -v` RED.
- [x] Add strict payload / version / Policy / actor validation, durable immutable records and pure reducers. Reuse inherited handle/transaction/idempotency logic; no parallel State writer.
- [x] Run evidence-chain tests and the message tests; record GREEN.

## Task 3: Honest Verification and recovery

**Files:** Create `collaboration/checks.py`, `tests/m1/test_verification.py`; extend `service.py`, `records.py`, `projection.py`, and the core causal projection for verification batches. Extend `core/commands.py` only to share the new aggregate-address mapping, so base-handler rejections remain recoverable.

**Interfaces:** `verification.run` creates a trusted report Artifact and an INCONCLUSIVE Verification; `verification.submit`, `task.verify`, `task.complete` reject unsupported authorization / quality shortcuts. `Projection.rebuild` and `RuntimeRecovery` consume facts only.

- [x] Write RED tests for actual passing/failing observations, evidence/hash/input binding, no self-reported pass, missing-review/verification gates, idempotent replay, SQLite rollback, stale versions and cross-connection review races.

```python
verification = store.read_projection("p-1")["verification:v-1"]
self.assertEqual(verification["result"], "INCONCLUSIVE")
self.assertEqual(report["observed_result"], "PASSED")
self.assertEqual(store.read_projection("p-1")["task:t-1"]["status"], "assigned")
```

- [x] Record `python -m unittest tests.m1.test_verification -v` RED.
- [x] Implement fixed text checks, generated immutable evidence, honest missing-enforcement record, atomic multi-object events and pure causal/recovery support.
- [x] Run M1 tests and M0 regression; record GREEN.

## Task 4: Fixed candidate review and handoff

**Files:** `collaboration/README.md`, `artifacts/m1-01-test-report.json`, `Docs/development/evidence/2026-09-11-m1-01-*`, backlog/status and generated preparation summaries; refresh MEMORY only with sourced current facts.

- [x] Build a concrete two-actor conversation/candidate/review/precheck example, preserving the immutable transcript and real evidence outputs.
- [x] Run `python -m unittest discover -s tests/m1 -t . -v`, M0 regression, `python tools/devprep.py render`, `python tools/devprep.py check`, and `python -m unittest discover -s tests/preparation -v`.
- [x] Freeze candidate file hashes; change M1-01 to review and hand the same candidate to the independent reviewer.
- [x] Address blocking findings with a new RED/GREEN cycle; never rewrite failed evidence or impersonate a second reviewer. The first independent review requested R1 (inherited claim/release membership and Policy) and R2 (Message JSON decoding); seven regression methods recorded 21 RED assertion failures, then all 40 M1 methods passed after the two fixes.
- [ ] Only after independent limited acceptance update M1-01 to done, synchronize status counts, run the required final checks, and write a handoff with commands/exit codes/limits/next item. Do not auto-commit or push.

The checklist is frozen with candidate v2 for review. Subsequent independent acceptance and administrative closeout are recorded in `Docs/development/evidence/2026-09-11-m1-01-handoff.md`; they do not rewrite this reviewed input or the initial candidate.
