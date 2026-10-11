# Fixed document execution (M1-02)

`ExecutionService` connects the existing SQLite Command boundary to a Windows document provider. It executes bounded JSON/text operations and records real files. It does not run Agent code, Shell, network calls, models, or arbitrary Runtime adapters; a working copy is not an OS sandbox.

The trusted host owns SQLite, `DocumentWorkspace`, `DocumentRuntime`, and authenticated actor channels. Agents submit data; they do not receive Python references to these objects. Bootstrap provisions the fixed Project policy through `project.execution.configure`. `task.create` through this service explicitly creates an execution Task; legacy M0/candidate Tasks retain their existing scope.

Typical host sequence:

1. Construct the service with a durable local SQLite store and an accessible Windows workspace root. Every ancestor must permit directory-handle pinning; inaccessible/reparse roots fail closed. Session sharing across Windows logon sessions and network filesystems are outside this implementation.
2. Call `recover(project_id)` before starting or dispatching. Resolve `pending_commands`, `unknown_actions`, or missing Sessions while the barrier is closed.
3. Submit `task.claim` at the current Task revision. Read the allocated `current_binding_id` and `lease_epoch` from facts.
4. Submit `execution.start` through `start_session(command, authenticated_actor_id=...)`. The returned registered Session is required for tool/Checkpoint requests. Retrying a previously accepted start after Runtime loss cannot mint a new Session.
5. Submit `tool.request` targeting the Task, with the current Task revision, `binding_id`, `lease_epoch`, `session_id`, `operation`, and `arguments`. This accepts an Action intent, not an external success. Call `dispatch(project_id, action_id, session=...)` for the returned Action.
6. Save `checkpoint.create` with bounded `context_snapshot` and `remaining_work` once actions are settled. Handoff uses `lease.revoke`, reconciliation, `task.requeue`, another claim/new epoch, and a new Session. `document.restore` uses the Binding's captured Checkpoint; `document.append` uses a confirmed document in the current copy.

Implemented operations:

| Operation | Arguments | Boundary |
| --- | --- | --- |
| `document.write` | `content` | New immutable object in current Binding's copy |
| `document.restore` | `checkpoint_id` | Query exact confirmed source, then create a new copy |
| `document.append` | `source_action_id`, `text` | Query source from current copy, then create a new object |

No operation accepts a path. Fixed Policy bounds UTF-8 content to 64 KiB. Shell/network/credential/publication requests require Approval and are refused; unknown tools lack enforcement and are refused. Client `risk_level=low` does not grant capabilities. Different callers' Session strings or copied Session objects do not grant authority.

The provider pins ancestors with directory handles participating in Windows sharing checks, rejects reparse points and hardlinks, and never overwrites an existing object. A named OS gate serializes resource calls and authority changes within the supported host; durable Task/Action revisions, current Lease epoch, actor, Session, Policy and wall-clock credential expiry are still checked at acceptance and actual access. Dispatch inside an existing database transaction is forbidden.

New objects remain delete-pending during content writes: this Windows filesystem state prevents new hardlinks, whereas sharing flags alone do not. The pending original name is excluded from the link count; any remaining link causes rejection before data is written. Only after the complete object is flushed does the provider clear delete-pending and retain the immutable file. A failed or interrupted unpublished write is discarded by handle closure, while its durable Action remains UNKNOWN and still requires reconciliation. No data is written after publication. This protects the fixed provider's write operation; it does not restrict a trusted host's later filesystem operations or provide a general OS sandbox.

PENDING is committed before IN_FLIGHT and before file effects. A crash or lost response leaves IN_FLIGHT/UNKNOWN; `reconcile` queries the original Action/target/argument/content identity. Missing or mismatched files remain UNKNOWN and cannot justify new-key retries. Replay only reduces facts; it does not query, start Sessions, or write files. Lease expiration uses Project governance time, while Session credentials continue expiring during pause.

The executable host examples are `Docs/development/evidence/2026-09-12-m1-02-demo.py` and the separate v2 output wrapper `2026-09-12-m1-02-demo-v2.py`. Their two actor channels are deterministic fixtures, not autonomous model agents. Artifact submission remains candidate provenance; formal Verification stays INCONCLUSIVE, Task quality gates stay closed, and whole-M1 acceptance remains outstanding.

M2-02 governance integration is described in `../governance/README.md`. Once governance is configured, fixed document requests require a snapshot/argument/actor-bound `approval_id`; the broker retains its provenance and rechecks Policy, expiry and revocation before the actual write. Bootstrap pause/resume is then disabled in favor of human governance Commands and Intervention facts. Governance and execution share the same OS resource gate. Recovery checks incomplete compound Commands as well as Session and Action state; it never interprets a historic approval or a successful Command retry as permission to repeat an effect.
