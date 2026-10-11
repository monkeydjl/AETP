# Explicit Task quality contract

`TaskQualityService` extends the accepted fixed-document `AcceptanceService`.
All changes still pass through Command → Event Store → Projection. No handler
accepts a caller-supplied verification result or a desired Task status.

The current human owner configures an immutable Task quality policy version,
an evidence maximum age measured in wall-clock milliseconds, and any concrete
Task declarations of `standalone_fixed_json_document` scope. Each operation
also needs its explicit LOW/auto Governance rule and clean InputAuthority
provenance. Manual or approval-required paths remain closed here.

The author enrolls with an actual registered Session and current execution
fence. Enrollment/rework fixes the work revision. Submission must cover every
completed document write in that work period and exclude unresolved Actions.
It fixes immutable Artifact/source/action snapshots and moves the Task to
READY_FOR_REVIEW. Old documents and evidence cannot be silently promoted.

An authorized participant requests a complete set of independent Reviews.
Each selected peer responds through their own authenticated identity; the
author's Lease is not transferred. New Verifications bind to this formal
cycle and run under the selected peer's separate QA Task and actual Session.

Evaluation collects every accepted Verification in the cycle before checking
applicability. Invalid evidence rejects use, a valid negative produces
REJECTED, and all approved Reviews plus only PASSED verifications produce
VERIFIED. Missing, pending and INCONCLUSIVE results keep IN_REVIEW. Each use
records the original/current revision, evidence identities/digests, rule
versions and time. Dispatch grant TTL does not expire a completed PASSED;
the configured wall-clock maximum evidence age controls subsequent use.
Current author execution authority remains required. Historical QA execution
proofs are checked without requiring the QA Task to remain IN_PROGRESS.

COMPLETED requires a fresh assessment and the current human owner's explicit
declaration for this specific Task/criteria/author/Binding/epoch. The product
does not infer integration requirements or prove that a real integration
surface is absent. `task.integration_exempted` keeps VERIFIED and stores a
prevalidated continuation; only the following `task.completed` retires the
Lease/Binding and sets COMPLETED. Both facts and the Command/idempotency result
commit in one transaction. Incomplete, replaced or interleaved compounds are
rejected by pure Replay. Legacy execution cannot revive terminal Tasks.

The trusted host supplies separate requester/target live observations; an
omitted author Session cannot be filled from public descriptors. Replay never
registers Sessions, reads current time/files, invokes a Runner or re-authorizes
historical evidence as a new dispatch.

This bounded prerequisite does not accept real Integration Gates, Mission
criteria, full M1, Bootstrap, autonomous model delivery or TEST-028. M3-02
remains in progress. The frozen first-batch examples and reports retain their
original Task states and acceptance scope.
