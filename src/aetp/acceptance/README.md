# Fixed document Verification prerequisite

This is the first M3-02 prerequisite. It does not implement Task success
transitions, Integration, Mission Acceptance, Bootstrap or TEST-028. The old
M1 `verification.run`/`verification.completed` schema still records an
INCONCLUSIVE precheck; it is never relabeled as an authorized Runner result.

`AcceptanceService` extends `PlanningService`. Its new Commands have their own
ResourceGate → SQLite writer transaction boundary:

| Command | Purpose |
| --- | --- |
| `project.quality.configure` | Current human_owner selects a bounded grant TTL; all other checker constraints are fixed. |
| `artifact.capture` | Capture the bytes produced by a completed, current `document.write` Action. |
| `verification.request` | Pin exact Artifact, criteria, Cases, policies and the verifier's independent execution Task. |
| `verification.revoke` | Record explicit withdrawal by the verifier or current human_owner. |
| `verification.dispatch` | Host-only durable single-use dispatch fact. |
| `verification.record` | Host-only atomic report Artifact and terminal fact. |

The caller supplies authenticated identity through a trusted host channel.
Agent-facing `handle` accepts Command data, a registered Session capability
and an optional InputAuthority capability supplied by the trusted ingress.
It cannot select host/recovery contexts or report an authorized result.

The host calls `dispatch(project_id, verification_id, session=...)` and, after
an interrupted result transaction, `recover_verifications(project_id)`.
The same OS resource gate covers the entire bounded Runner call, while no
SQLite transaction spans that call. Losing a result leaves a durable
in_flight Action. Acquiring the exclusive gate after that synchronous fixed
call has exited permits an explicit abandoned result, not a repeated call.
This termination argument applies only to this in-memory checker with no
external effects, in the fixed Windows current-session host boundary.

Quality and Governance constraints intersect. Governance must explicitly
allow `verification.execute` with effective low risk and auto routing in
selective/autonomous mode. Manual, higher risk and unsupported approval
paths refuse execution. Quality configuration is not per-request Approval.

Capture derives content, author, content/arguments/result digests and Task
criteria from the exact completed Action; it does not read the current
Workspace file. The Action's requested Task revision must still match.
Original authorization/source and the capture request's own ingress source
are both retained. Missing/unknown/marked sources stay marked. Verification
inherits them and records its own input proof; a new clean proof cannot erase
an ancestor's exposure. The new reducer alone produces the top-level
`capture_origin`. Old inline candidates cannot obtain auto eligibility by
editing an extensible legacy source mapping. Report IDs are reserved for
host reports; a pre-existing historical collision prevents a new grant.

The verifier and Case author must differ from the Artifact author. The
verifier uses a different real execution Task, with current Binding, Lease,
epoch and the actual registered Session object. Copying Session fields is
not authorization. Cases are authored by the authenticated request actor;
the payload cannot nominate a test author. Target/criteria, full Task
revision, both policies, input source and Runner descriptor are pinned and
rechecked at dispatch, actual invocation and result recording. This first
batch conservatively invalidates evidence when full Task revision changes;
future lifecycle transitions need a separately designed reuse contract.

The checker accepts 1–32 ordered `{criterion, path, equals}` Cases, exactly
one per target criterion, at most 16384 canonical UTF-8 bytes. A path has at
most 16 string keys or nonnegative integer indices. Target JSON is at most
65536 UTF-8 bytes and 32 nesting levels. Duplicate keys, invalid Unicode,
NaN/Infinity, nonfinite numbers and numeric tokens exceeding 128 characters
are rejected. Equality distinguishes booleans, integers and floating-point
numbers, including nested values; missing paths are not null. It never
evaluates expressions, user code, file paths or network requests.

PASSED means every declared fixed check actually matched. It does not imply
understanding or independently proving the natural-language criterion.
Invalid target JSON or a mismatch is FAILED. No execution, lost authority,
exception or uncertain output is INCONCLUSIVE. Observations obtained before
a revocation are retained even when the final result is INCONCLUSIVE.

Replay validates receipts, Command content, addresses, revisions, sources,
report bytes and terminal consistency without invoking the Runner, Runtime,
input authority or Provider. A prefix ending with an intermediate report
remains pending and cannot carry a usable Verification result. A subsequent
fact must be its matching terminal. Failed incremental validation publishes
neither State nor cursor. Global recovery includes nested in_flight Actions.

Run the M3 tests with `PYTHONPATH=src`:

```powershell
python -m unittest discover -s tests/m3 -t . -v
```

Recorded execution, immutable source blobs, failures and review evidence are
under `Docs/development/evidence/2026-09-14-m3-02-*`.
