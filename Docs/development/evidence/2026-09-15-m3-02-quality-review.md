# M3-02 Task quality v1 — independent review

Decision: **accepted for the four frozen batch criteria only**. M3-02 remains **in_progress**; the original work item is **not accepted**.

Reviewer: `/root/m1_reviewer`; executor: `/root`. Candidate v1 remains `review.status=pending`; this separate record is the independent decision.

Independent execution root: `D:\Github\AETP\.tmp\m3qr2`.

## Acceptance mapping

- **Explicit enrollment/submission and independent quality stages — accepted.** The Task opts in to task-quality-1 explicitly. Submission binds every official output of the current round; captures of the same Action cannot inflate the output set. Independent Review is an explicit quality stage, and unrelated legacy Review does not promote a Task. Evidence: `suite_m3_v1`, `probes_v1`, `fresh_demo_v1`.

- **Versioned evidence applicability without legacy promotion — accepted.** Evidence use binds the versioned cycle and complete Artifact set before applicability is evaluated. Expired or invalid records cannot be hidden by fresher results. PASSED plus pending/lost/error INCONCLUSIVE remains IN_REVIEW. Valid historical results remain usable after the actual QA Task ends, its Session disappears, and dispatch TTL expires, subject to current evidence-use policy and age limits. Evidence: `suite_m3_v1`, `probes_v1`, `fresh_demo_v1`.

- **Explicit Task-specific exemption and terminal execution retirement — accepted.** COMPLETED is demonstrated only for the specific human_owner declaration for t-1 as standalone_fixed_json_document. Completion retires the author execution and Lease, while both COMPLETED and CANCELLED reject old-entry resurrection. Copying a Session object does not create an author capability. Withdrawal or relevant revision changes prevent stale completion. Evidence: `suite_m3_v1`, `probes_v1`, `fresh_demo_v1`.

- **Atomic/retry/race integrity and pure old/new Replay — accepted.** SQLite rollback, retries, response loss, separate-connection races, strict causal receipt/cursor validation, and both completion effects were checked. The independent first-effect failure leaves no partial receipt or pending Command and can retry. Every prefix of ten frozen old/new databases plus two new independent databases rebuilds without guarded execution or I/O and without changing database bytes. Evidence: `suite_m3_v1`, `suite_m2_v1`, `suite_m1_v1`, `suite_m0_v1`, `probes_v1`, `frozen_replay_v2`, `fresh_demo_v1`.

## Verification

| Suite | Tests | Actual result |
| --- | ---: | --- |
| m3 | 209 | [suite_m3_v1](2026-09-15-m3-02-quality-review-runs/suite_m3_v1/result.json), exit 0 |
| m2 | 167 | [suite_m2_v1](2026-09-15-m3-02-quality-review-runs/suite_m2_v1/result.json), exit 0 |
| m1 | 85 | [suite_m1_v1](2026-09-15-m3-02-quality-review-runs/suite_m1_v1/result.json), exit 0 |
| m0 | 156 | [suite_m0_v1](2026-09-15-m3-02-quality-review-runs/suite_m0_v1/result.json), exit 0 |
| preparation | 27 | [suite_preparation_v1](2026-09-15-m3-02-quality-review-runs/suite_preparation_v1/result.json), exit 0 |

Total: **644 suite tests plus 13 independent probes**, all passed. Compile, devprep render, and devprep check also exited 0.

Replay: **10 frozen databases / 780 prefixes**, plus **2 fresh independent databases / 250 prefixes**. All 35 guarded calls stayed at zero; database bytes stayed unchanged.

The fresh two-output demonstration retains PASSED plus a lost-result INCONCLUSIVE, requires explicit rework, and later consumes valid historical PASSED after QA cancellation, Session loss, and dispatch TTL expiry. The intermediate completion prefix remains VERIFIED; final Task COMPLETED retires the Lease.

[Frozen integrity](2026-09-15-m3-02-quality-review-integrity-v1.json) checks 210 sources, 3 metadata snapshots, 2 prefixes, 498 baseline archives, 7 pins, and 418 first-batch frozen sources. Every recorded command archives all 169 mandatory files, including all 9 schemas, plus its executing reviewer scripts.

## Findings and retained failures

No Critical, Important, or Minor findings. Prior stale legacy-gate comment M3-02-R1 is corrected; the legacy gate remains closed.

`setup_v1` exited 1 because recursive historical references reached the 8000-file harness guard (109800856 bytes). Its failed `.tmp/m3qr1` copy and raw logs remain. `setup_v2` created the bounded final `.tmp/m3qr2` copy: 1364 files / 28885408 bytes. This was a harness setup failure, not a product test failure.

`frozen_replay_v1` also remains: the reviewer caller used default project p-1 for an older demo-project database, producing an empty state and a rejected digest comparison. The recorded diagnostic proves 0 prefixes with the wrong project and 24 matching prefixes with the correct project. Passing `frozen_replay_v2` explicitly selects each project and checks positive event/prefix/command counts and the pinned state digest. No candidate change was needed.

## Boundaries and handoff

The demonstrated COMPLETED state relies on a specific human_owner declaration for t-1 as standalone_fixed_json_document. There is no automatic integration-need detection. The identities are deterministic fixtures; no autonomous model delivery is claimed.

Original Integration Gate, per-criterion Mission Acceptance Verification, and autonomous equal-agent delivery remain not_accepted. First batch remains accepted; development stays at 19 done / 1 in_progress, full M1 not_accepted, preparation phase, product completion 0%, Bootstrap not_started, and full Conformance 28 registered / 0 passed.

Concurrent original suites retained their slower isolated TEMP/TMP and were not restarted; actual environments and elapsed times are pinned in their result records. The bootstrap provenance exception is retained explicitly in the JSON report.

Durable review artifacts are limited to the reviewer evidence namespace, `.tmp/m3qr1`, `.tmp/m3qr2`, and `artifacts/m3-02-quality-review-*`. Temporary execution locations are recorded per command. No candidate, historical source, metadata, MEMORY, product, or schema was edited by this reviewer.

[Machine-readable review](2026-09-15-m3-02-quality-review.json) pins the pre-generation journal prefix and every completed command result. Report generation uses `report_generate_v1`; the required later self-check uses `report_selfcheck_v1` and pins both reports separately. Its result is intentionally outside this immutable report to avoid self-reference.

Next: parent consumes this batch-only decision and its separate self-check, retaining M3-02 in_progress and the three original criteria not_accepted.
