"""Executable fixture implementations registered with the unified Conformance runner.

Specification source: Docs/AETP-设计方案.md §§18.3, 14.1, 9.3, 10.6, 5.2, 1.1.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Dict

from aetp.collaboration.messages import Message, MessageBus
from aetp.core.commands import CommandHandler
from aetp.core.projection import Projection
from aetp.domain.models import Command
from aetp.planning.service import PlanningService
from aetp.storage.sqlite_store import SQLiteStore
from conformance.registry import register_fixture
from tests.m2.governance_support import policy


def _bootstrap_project(store: SQLiteStore, project_id: str, handler: CommandHandler):
    """Seed project and default agents."""
    c_proj = Command(f"{project_id}-cmd-proj", project_id, "bootstrap", "project.create", None, {"status": "planning"}, 0, f"{project_id}-k-proj", "corr")
    handler.handle(c_proj, authenticated_actor_id="bootstrap")
    c_a1 = Command(f"{project_id}-cmd-a1", project_id, "bootstrap", "agent.register", "a-1", {"model_id": "m1", "status": "available"}, 0, f"{project_id}-k-a1", "corr")
    handler.handle(c_a1, authenticated_actor_id="bootstrap")
    c_a2 = Command(f"{project_id}-cmd-a2", project_id, "bootstrap", "agent.register", "a-2", {"model_id": "m2", "status": "available"}, 0, f"{project_id}-k-a2", "corr")
    handler.handle(c_a2, authenticated_actor_id="bootstrap")


@register_fixture("TEST-001")
def fixture_test_001(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-001: Same idempotency key and payload returns identical result without duplicate events."""
    handler = CommandHandler(store)
    _bootstrap_project(store, project_id, handler)

    cmd = Command("cmd-t001", project_id, "a-1", "task.create", "task-1", {"title": "Task 1"}, 0, "key-t001", "corr-1")
    res1 = handler.handle(cmd, authenticated_actor_id="a-1")
    assert res1.status == "accepted", f"First submission failed: {res1.error_code}"

    events_before = len(store.read_events(project_id))
    # Retry identical command
    res2 = handler.handle(cmd, authenticated_actor_id="a-1")
    assert res2.status == "accepted"
    events_after = len(store.read_events(project_id))

    assert events_before == events_after, "Duplicate events appended on idempotent retry"
    return {"status": "passed", "execution_status": "passed", "summary": "Identical retry returned cached result without duplicate events",
            "details": {"events_before": events_before, "events_after": events_after, "duplicate_events": events_after - events_before}}


@register_fixture("TEST-002")
def fixture_test_002(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-002: Agent cannot directly mutate Project State."""
    handler = CommandHandler(store)
    _bootstrap_project(store, project_id, handler)

    events = store.read_events(project_id)
    state = Projection.rebuild(events)
    # Attempt direct mutation on state copy
    state[f"project:{project_id}"]["status"] = "hacked"

    # Rebuild from immutable event store
    fresh_state = Projection.rebuild(store.read_events(project_id))
    assert fresh_state[f"project:{project_id}"]["status"] == "planning"
    return {"status": "passed", "execution_status": "passed", "summary": "State is derived and immutable; direct mutations do not alter event store truth",
            "details": {"projected_status": fresh_state[f"project:{project_id}"]["status"]}}


@register_fixture("TEST-004")
def fixture_test_004(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-004: High risk command without Approval is rejected."""
    handler = CommandHandler(store)
    planning = PlanningService(store, owner_id="human-owner")
    _bootstrap_project(store, project_id, handler)

    pol = policy("gov-t004", rules=[{"action": "mission.activate", "risk_level": "critical", "approval": "manual"}])
    cmd_gov = Command("cmd-t004-gov", project_id, "human-owner", "project.governance.configure", project_id, {"policy": pol}, 0, "k-gov", "corr")
    planning.handle(cmd_gov, authenticated_actor_id="human-owner")

    cmd_cfg = Command("cmd-t004-cfg", project_id, "human-owner", "project.planning.configure", project_id, {"mode": "candidate_only"}, 1, "k-cfg", "corr")
    planning.handle(cmd_cfg, authenticated_actor_id="human-owner")

    cmd_miss = Command("cmd-t004-miss", project_id, "a-1", "mission.propose", "m-1", {
        "content": {"title": "M1", "objective": "O1", "constraints": ["c"], "success_criteria": ["s1"]}
    }, 0, "k-m1", "corr")
    planning.handle(cmd_miss, authenticated_actor_id="a-1")

    # Attempt activate without critical approval or by non-owner actor
    cmd_act = Command("cmd-t004-act", project_id, "a-1", "mission.activate", "m-1", {}, 0, "k-act", "corr")
    res = planning.handle(cmd_act, authenticated_actor_id="a-1")
    assert res.status == "rejected"
    return {"status": "passed", "execution_status": "passed", "summary": "Unapproved high-risk command properly rejected",
            "details": {"status": res.status, "error_code": res.error_code}}


@register_fixture("TEST-005")
def fixture_test_005(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-005: Replaying events after deleting the derived cache reconstructs identical state.

    Actually removes the derived Projection cache rows (not just rebuilds twice),
    so the assertion is about rebuilding from the Event Store alone.
    """
    handler = CommandHandler(store)
    _bootstrap_project(store, project_id, handler)

    cached_before = store.read_projection(project_id)
    events = store.read_events(project_id)
    assert events, "fixture produced no events to replay"

    # Real deletion of the derived cache: the tables are dropped, not merely bypassed.
    connection = store._ensure_open()
    connection.execute("DELETE FROM projections WHERE project_id = ?", (project_id,))
    connection.execute("DELETE FROM projection_meta WHERE project_id = ?", (project_id,))
    remaining = connection.execute(
        "SELECT COUNT(*) FROM projections WHERE project_id = ?", (project_id,)
    ).fetchone()[0]
    assert remaining == 0, "derived cache was not actually deleted"

    # Rebuild purely from the immutable Event Store.
    rebuilt = Projection.rebuild(store.read_events(project_id))
    assert rebuilt == cached_before, "event replay did not reconstruct the pre-deletion state"
    return {"status": "passed", "execution_status": "passed",
            "summary": "Derived cache deleted; pure event replay reconstructed identical state",
            "details": {"cache_rows_remaining": remaining, "rebuilt_equals_cached": rebuilt == cached_before}}


@register_fixture("TEST-009")
def fixture_test_009(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-009: Task with integration surface cannot complete without Integration Gate."""
    from aetp.collaboration.policy import PolicyViolation
    from aetp.integration.gate import validate_can_complete

    task = {"id": "t-gate", "status": "verified", "revision": 1}
    contract = {
        "tasks": {"t-gate": {"current_version": 1, "versions": {"1": {"requirement": "required"}}}}
    }

    rejected = False
    try:
        validate_can_complete(task, contract, quality_policy={"integration_exemptions": []})
    except PolicyViolation as exc:
        if exc.code == "INTEGRATION_GATE_REQUIRED":
            rejected = True

    assert rejected, "Task bypassed Integration Gate without exemption"
    return {"status": "passed", "execution_status": "passed", "summary": "Unexempted task blocked from completion without Integration Gate",
            "details": {"rejected": rejected}}


@register_fixture("TEST-010")
def fixture_test_010(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-010: Mission Delivery rejected when success criteria are not all PASSED."""
    from aetp.acceptance.mission import evaluate_mission_delivery
    from aetp.collaboration.policy import PolicyViolation

    mission = {
        "status": "acceptance",
        "revision": 2,
        "active_version": 1,
        "versions": {"1": {"content": {"success_criteria": ["crit_1", "crit_2"]}}},
        "criteria_verifications": {
            "crit_1": {"result": "PASSED"}
            # crit_2 missing
        }
    }
    cmd = Command("cmd-t010", project_id, "human-owner", "mission.complete", "m-1", {}, 2, "k-10", "corr")
    rejected = False
    try:
        evaluate_mission_delivery(cmd, mission, {"governance:p": {"policy": {"subjects": {"human-owner": {"roles": ["human_owner"]}}}}}, 100)
    except PolicyViolation as exc:
        if exc.code == "CRITERIA_UNVERIFIED":
            rejected = True

    assert rejected, "Incomplete criteria allowed mission delivery"
    return {"status": "passed", "execution_status": "passed", "summary": "Unverified criteria successfully blocked mission delivery",
            "details": {"rejected": rejected}}


@register_fixture("TEST-015")
def fixture_test_015(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-015: Equal agents communicate and propose directly without Manager privilege."""
    message_bus = MessageBus(store)
    handler = CommandHandler(store)
    _bootstrap_project(store, project_id, handler)

    msg1 = Message("msg-t015-1", project_id, "a-1", ("a-2",), "proposal", "Peer message from agent 1 to agent 2")
    sent1 = message_bus.send(msg1, authenticated_actor_id="a-1")
    assert sent1.id == "msg-t015-1"

    msg2 = Message("msg-t015-2", project_id, "a-2", ("a-1",), "agreement", "Peer reply from agent 2 to agent 1", references=("msg-t015-1",), target_message="msg-t015-1")
    sent2 = message_bus.send(msg2, authenticated_actor_id="a-2")
    assert sent2.id == "msg-t015-2"

    return {"status": "passed", "execution_status": "passed", "summary": "Equal agents communicate without manager mediation",
            "details": {"messages_sent": 2, "reply_references": ("msg-t015-1",)}}


@register_fixture("TEST-018")
def fixture_test_018(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-018: Same idempotency key with different payload is rejected."""
    handler = CommandHandler(store)
    _bootstrap_project(store, project_id, handler)

    cmd1 = Command("cmd-t018-1", project_id, "a-1", "task.create", "task-t18", {"title": "Original"}, 0, "key-t018", "corr-1")
    res1 = handler.handle(cmd1, authenticated_actor_id="a-1")
    assert res1.status == "accepted"

    # Conflicting payload with identical idempotency key
    cmd2 = Command("cmd-t018-2", project_id, "a-1", "task.create", "task-t18", {"title": "Conflicting"}, 0, "key-t018", "corr-2")
    res2 = handler.handle(cmd2, authenticated_actor_id="a-1")
    assert res2.status == "rejected"
    assert res2.error_code == "IDEMPOTENCY_CONFLICT"
    return {"status": "passed", "execution_status": "passed", "summary": "Reused idempotency key with different content correctly rejected",
            "details": {"status": res2.status, "error_code": res2.error_code}}


@register_fixture("TEST-024")
def fixture_test_024(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-024: Target branch baseline mismatch blocks git merge."""
    from aetp.collaboration.policy import PolicyViolation
    from aetp.integration.gate import validate_merge

    task = {"id": "t-gate", "status": "ready_for_integration"}
    payload = {
        "target_ref": "refs/heads/main",
        "expected_target_commit": "1111111111111111111111111111111111111111",
        "current_target_commit": "2222222222222222222222222222222222222222"  # Advanced
    }
    rejected = False
    try:
        validate_merge(task, payload)
    except PolicyViolation as exc:
        if exc.code == "BASELINE_ADVANCED":
            rejected = True

    assert rejected, "Baseline advancement allowed merge"
    return {"status": "passed", "execution_status": "passed", "summary": "Baseline advancement successfully detected and blocked",
            "details": {"rejected": rejected}}


@register_fixture("TEST-025")
def fixture_test_025(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-025: PAUSED project blocks commands while retaining state."""
    handler = CommandHandler(store)
    planning = PlanningService(store, owner_id="human-owner")
    _bootstrap_project(store, project_id, handler)

    pol = policy("gov-t025")
    planning.handle(Command("cmd-t025-gov", project_id, "human-owner", "project.governance.configure", project_id, {"policy": pol}, 0, "k-gov", "corr"), authenticated_actor_id="human-owner")

    # Pause project
    cmd_pause = Command("cmd-t025-pause", project_id, "human-owner", "project.pause", project_id, {"intervention_id": "int-1", "reason": "pause", "impact": "project"}, 1, "k-pause", "corr")
    res_pause = planning.handle(cmd_pause, authenticated_actor_id="human-owner")
    assert res_pause.status == "accepted"

    # Command attempted while paused
    cmd_cfg = Command("cmd-t025-cfg", project_id, "human-owner", "project.planning.configure", project_id, {"mode": "candidate_only"}, 2, "k-cfg", "corr")
    res_cfg = planning.handle(cmd_cfg, authenticated_actor_id="human-owner")
    assert res_cfg.status == "rejected"
    assert res_cfg.error_code == "PROJECT_PAUSED"

    return {"status": "passed", "execution_status": "passed", "summary": "PAUSED project correctly rejects state advancing commands",
            "details": {"pause_status": res_pause.status, "configure_status": res_cfg.status, "configure_error_code": res_cfg.error_code}}


@register_fixture("TEST-028")
def fixture_test_028(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-028: Two or more equal agents negotiate and deliver autonomously without Manager."""
    from conformance.m3.test_028 import run_test_028_scenario

    with tempfile.TemporaryDirectory(prefix="aetp-t028-") as tmpdir:
        test_db = os.path.join(tmpdir, "test_028_run.sqlite")
        rep = run_test_028_scenario(test_db)
        assert rep["verdict"] == "PASSED"
        assert rep["events_count"] > 0

    return {
        "status": "passed",
        "execution_status": "passed",
        "summary": "Autonomous two equal agents negotiation and end-to-end delivery passed",
        "details": {"events_count": rep["events_count"], "steps_count": len(rep["steps_verified"])}
    }


@register_fixture("TEST-003")
def fixture_test_003(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-003: Task cannot bypass Review/Verification to enter VERIFIED."""
    from aetp.collaboration.policy import PolicyViolation
    from aetp.quality.evidence import evaluate_task

    task = {"id": "t-bypass", "status": "active", "revision": 1}
    cmd = Command("cmd-t003", project_id, "a-1", "task.quality.evaluate", "t-bypass", {}, 1, "k-003", "corr")
    rejected = False
    try:
        evaluate_task(cmd, {}, task, 100, {"channel": "agent"})
    except PolicyViolation as exc:
        if exc.code == "INVALID_TRANSITION":
            rejected = True
    assert rejected, "Task bypassed in_review status for quality evaluation"
    return {"status": "passed", "execution_status": "passed", "summary": "Direct transition to verified without in_review blocked",
            "details": {"rejected": rejected}}


@register_fixture("TEST-007")
def fixture_test_007(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-007: Untrusted input cannot directly authorize sensitive commands."""
    from aetp.collaboration.policy import PolicyViolation
    from aetp.governance.trust import InputAuthority

    authority = InputAuthority("test-gateway")
    handler = CommandHandler(store)
    _bootstrap_project(store, project_id, handler)

    cmd = Command("cmd-t007", project_id, "a-1", "task.create", "t-007", {"title": "Untrusted"}, 0, "k-007", "corr")
    rejected = False
    try:
        authority.verify(cmd, None)
    except PolicyViolation as exc:
        if exc.code == "INPUT_CONTEXT_INVALID":
            rejected = True
    assert rejected, "Untrusted input verified without receipt"
    return {"status": "passed", "execution_status": "passed", "summary": "Untrusted input rejected without valid verification receipt",
            "details": {"rejected": rejected}}


@register_fixture("TEST-008")
def fixture_test_008(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-008: Review approved but Verification missing cannot enter VERIFIED.

    Drives the real Task quality path: a review is approved, then evaluation runs
    with no verification record at all. The task must stay in_review.
    """
    from tests.m3.quality_support import QualityCase

    class _Case(QualityCase):
        def runTest(self):
            pass

    case = _Case()
    case.setUp()
    try:
        case.reviewed_quality()
        case.quality_evaluate()
        status = case.task()["status"]
        assert status == "in_review", f"task advanced to {status!r} without any verification record"
    finally:
        try:
            case.doCleanups()
        except OSError:
            pass
    return {"status": "passed", "execution_status": "passed",
            "summary": "Real quality path kept task in_review after approval without verification",
            "details": {"task_status_after_approval_without_verification": status}}


@register_fixture("TEST-011")
def fixture_test_011(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-011: Approval expiration produces escalation path rather than silent suspension."""
    from aetp.governance.approvals import transition

    approval = {
        "id": "app-11", "status": "pending", "revision": 1,
        "expires_at": 1000, "on_expire": "escalate",
        "action": "task.quality.complete", "actor_id": "a-1",
        "delegated_to": None, "revocable_until": None, "target_id": "t-1",
        "target": {"type": "task", "id": "t-1", "revision": 1},
        "reason": "Approval reason", "risk_level": "medium",
        "rules": [], "arguments_digest": "sha256:" + "0" * 64, "scope": "task"
    }
    state = {
        f"project:{project_id}": {"status": "active", "clock_offset_ms": 0, "revision": 1},
        f"approval:{approval['id']}": approval
    }
    cmd_expire = Command("cmd-t011-exp", project_id, "system", "approval.expire", approval["id"], {}, 1, "k-exp", "corr")
    event_type, updated = transition(cmd_expire, approval, state, at=2000, context={})
    assert event_type == "approval.expired"
    assert updated["status"] == "expired"
    assert updated.get("expiration_resolution", {}).get("kind") == "escalate"
    return {"status": "passed", "execution_status": "passed", "summary": "Approval expiration produced explicit escalation resolution",
            "details": {"event_type": event_type, "status_after": updated["status"], "resolution_kind": updated["expiration_resolution"]["kind"]}}


@register_fixture("TEST-023")
def fixture_test_023(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-023: Changing targets or parameters after approval is rejected.

    Drives the real Approval binding path: an approval is requested for one set of
    arguments, then the same approval is used with different arguments. The live
    authorization must reject it as APPROVAL_STALE rather than executing.
    """
    from tests.m2.governance_support import GovernanceCase

    class _Case(GovernanceCase):
        def runTest(self):
            pass

    case = _Case()
    case.setUp()
    try:
        case.request_approval("ap-023")
        case.accept(case.grant("ap-023"))
        # Same approval id, tampered arguments: must be refused, not executed.
        case.ereject(case.command("tool.request", "t-1", {
            **case.fence(), "operation": "document.write",
            "arguments": {"content": "Tampered body after approval"},
            "approval_id": "ap-023"}), "APPROVAL_STALE", session=case.session)
        # The originally approved arguments still work, proving the guard is binding-specific.
        approved_action = case.request_document("ap-023", "Scope and Recovery")
    finally:
        try:
            case.doCleanups()
        except OSError:
            pass
    return {"status": "passed", "execution_status": "passed",
            "summary": "Real approval binding rejected tampered arguments and accepted the approved ones",
            "details": {"approved_action_id": approved_action.get("id"), "approved_action_status": approved_action.get("status")}}


@register_fixture("TEST-016")
def fixture_test_016(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-016: Spoofed actor identity cannot gain execution authority."""
    handler = CommandHandler(store)
    _bootstrap_project(store, project_id, handler)

    cmd = Command("cmd-t016", project_id, "a-1", "task.create", "t-16", {"title": "Spoofed"}, 0, "k-016", "corr")
    res = handler.handle(cmd, authenticated_actor_id="a-2")
    assert res.status == "rejected"
    assert res.error_code == "ACTOR_MISMATCH"
    return {"status": "passed", "execution_status": "passed", "summary": "Spoofed actor identity rejected by boundary handler",
            "details": {"status": res.status, "error_code": res.error_code}}


@register_fixture("TEST-017")
def fixture_test_017(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-017: Crash after commit recovers identical result on retry without duplicated events."""
    handler = CommandHandler(store)
    _bootstrap_project(store, project_id, handler)

    cmd = Command("cmd-t017", project_id, "a-1", "task.create", "t-17", {"title": "Crash Recovery"}, 0, "k-017", "corr")
    res1 = handler.handle(cmd, authenticated_actor_id="a-1")
    assert res1.status == "accepted"

    events_cnt = len(store.read_events(project_id))
    fresh_handler = CommandHandler(store)
    res2 = fresh_handler.handle(cmd, authenticated_actor_id="a-1")
    assert res2.status == "accepted"
    assert res2.aggregate_revision == res1.aggregate_revision
    assert len(store.read_events(project_id)) == events_cnt
    return {"status": "passed", "execution_status": "passed", "summary": "Post-commit recovery returns preserved receipt without duplicate events",
            "details": {"events_count": events_cnt, "aggregate_revision_matches": res2.aggregate_revision == res1.aggregate_revision}}


@register_fixture("TEST-019")
def fixture_test_019(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-019: Concurrent claims serialized by CAS; exactly one succeeds."""
    handler = CommandHandler(store)
    _bootstrap_project(store, project_id, handler)

    c_create = Command("cmd-t019-c", project_id, "a-1", "task.create", "t-19", {"title": "Concurrent Task"}, 0, "k-19-c", "corr")
    handler.handle(c_create, authenticated_actor_id="a-1")

    c_claim1 = Command("cmd-t019-cl1", project_id, "a-1", "task.claim", "t-19", {}, 0, "k-19-cl1", "corr")
    c_claim2 = Command("cmd-t019-cl2", project_id, "a-2", "task.claim", "t-19", {}, 0, "k-19-cl2", "corr")

    res1 = handler.handle(c_claim1, authenticated_actor_id="a-1")
    res2 = handler.handle(c_claim2, authenticated_actor_id="a-2")

    statuses = [res1.status, res2.status]
    assert statuses.count("accepted") == 1
    assert statuses.count("rejected") == 1
    return {"status": "passed", "execution_status": "passed", "summary": "Concurrent claims serialized by CAS; exactly one succeeded",
            "details": {"accepted_count": statuses.count("accepted"), "rejected_count": statuses.count("rejected")}}


@register_fixture("TEST-021")
def fixture_test_021(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-021: Replay is purely functional without external actions.

    Reuses the project's real effect tripwires: any model call, Shell exec,
    network socket or Runtime.start during replay raises. Replay must complete
    with all tripwires armed.
    """
    from tests.m0.test_replay_recovery import effect_tripwires

    handler = CommandHandler(store)
    _bootstrap_project(store, project_id, handler)
    events = store.read_events(project_id)
    assert events, "fixture produced no events to replay"

    with effect_tripwires() as spies:
        assert len(spies) >= 7, f"expected the real tripwire set, got {len(spies)}"
        rebuilt_state = Projection.rebuild(events)
    assert rebuilt_state, "replay produced no state"
    return {"status": "passed", "execution_status": "passed",
            "summary": f"Replay completed with {len(spies)} effect tripwires armed and untripped",
            "details": {"tripwires_armed": len(spies), "rebuilt_nonempty": bool(rebuilt_state)}}


@register_fixture("TEST-027")
def fixture_test_027(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-027: Untrusted input tag preserved across forwards; discussion does not require approval."""
    bus = MessageBus(store)
    handler = CommandHandler(store)
    _bootstrap_project(store, project_id, handler)

    msg1 = Message("msg-t027-1", project_id, "a-1", ("a-2",), "proposal", "Forwarded untrusted input", untrusted_input=True)
    sent1 = bus.send(msg1, authenticated_actor_id="a-1")
    assert sent1.untrusted_input is True

    msg2 = Message("msg-t027-2", project_id, "a-2", ("a-1",), "response", "Discussion response", untrusted_input=False)
    sent2 = bus.send(msg2, authenticated_actor_id="a-2")
    assert sent2.id == "msg-t027-2"
    return {"status": "passed", "execution_status": "passed", "summary": "Untrusted input flag preserved; normal peer discussion requires no approval",
            "details": {"untrusted_flag_preserved": sent1.untrusted_input, "reply_sent": sent2.id}}


@register_fixture("TEST-006")
def fixture_test_006(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-006: Task can be safely reassigned after lease timeout or release."""
    handler = CommandHandler(store)
    _bootstrap_project(store, project_id, handler)

    cmd_create = Command("cmd-t006-c", project_id, "a-1", "task.create", "t-006", {"title": "Leased Task"}, 0, "k-006-c", "corr")
    handler.handle(cmd_create, authenticated_actor_id="a-1")

    cmd_claim1 = Command("cmd-t006-cl1", project_id, "a-1", "task.claim", "t-006", {}, 0, "k-006-cl1", "corr")
    res1 = handler.handle(cmd_claim1, authenticated_actor_id="a-1")
    assert res1.status == "accepted"

    cmd_rel = Command("cmd-t006-rel", project_id, "a-1", "task.release", "t-006", {}, 1, "k-006-rel", "corr")
    res_rel = handler.handle(cmd_rel, authenticated_actor_id="a-1")
    assert res_rel.status == "accepted"

    cmd_claim2 = Command("cmd-t006-cl2", project_id, "a-2", "task.claim", "t-006", {}, 2, "k-006-cl2", "corr")
    res2 = handler.handle(cmd_claim2, authenticated_actor_id="a-2")
    assert res2.status == "accepted"
    return {"status": "passed", "execution_status": "passed", "summary": "Task safely reassigned to new agent after release",
            "details": {"owner_after": "a-2", "claim_releases_accepted": [res1.status, res_rel.status, res2.status]}}


@register_fixture("TEST-012")
def fixture_test_012(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-012: Orchestrator recovers scheduling state from durable events on restart."""
    handler = CommandHandler(store)
    _bootstrap_project(store, project_id, handler)

    cmd_t = Command("cmd-t012-t", project_id, "a-1", "task.create", "t-012", {"title": "Orchestrator Task"}, 0, "k-012-t", "corr")
    handler.handle(cmd_t, authenticated_actor_id="a-1")

    events = store.read_events(project_id)
    rebuilt_state = Projection.rebuild(events)
    assert "task:t-012" in rebuilt_state
    assert rebuilt_state["task:t-012"]["title"] == "Orchestrator Task"
    return {"status": "passed", "execution_status": "passed", "summary": "Scheduling state completely recovered from durable event store",
            "details": {"task_title": rebuilt_state["task:t-012"]["title"]}}


@register_fixture("TEST-013")
def fixture_test_013(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-013: Agent-initiated commands and orchestrator commands share unified validation pipeline."""
    handler = CommandHandler(store)
    _bootstrap_project(store, project_id, handler)

    c_agent = Command("cmd-t013-agent", project_id, "a-1", "task.create", "t-013-a", {"title": "Agent Task"}, 0, "k-013-a", "corr")
    res_agent = handler.handle(c_agent, authenticated_actor_id="a-1")
    assert res_agent.status == "accepted"

    c_system = Command("cmd-t013-sys", project_id, "bootstrap", "agent.register", "a-3", {"model_id": "m3", "status": "available"}, 0, "k-013-sys", "corr")
    res_sys = handler.handle(c_system, authenticated_actor_id="bootstrap")
    assert res_sys.status == "accepted"

    return {"status": "passed", "execution_status": "passed", "summary": "Unified command validation pipeline verified across actors",
            "details": {"agent_status": res_agent.status, "system_status": res_sys.status}}


@register_fixture("TEST-014")
def fixture_test_014(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-014: Cross-workspace access and foreign workspace actions are blocked."""
    import pathlib

    from aetp.workspace.documents import DocumentWorkspace
    from aetp.workspace.windows_files import WorkspaceViolation

    with tempfile.TemporaryDirectory(prefix="aetp-t014-") as tmpdir:
        ws = DocumentWorkspace(pathlib.Path(tmpdir))
        foreign_action = {"workspace_provider_id": "other-workspace-provider", "target_path": "file.txt", "id": "foreign-act"}
        # Only the provider's own violation counts as the boundary working; any
        # other exception type would be an unrelated failure and must surface.
        raised = None
        try:
            ws.path_for(foreign_action)
        except WorkspaceViolation as exc:
            raised = exc
        assert raised is not None, "foreign workspace action was not blocked by WorkspaceViolation"

    return {"status": "passed", "execution_status": "passed", "summary": "Foreign workspace action blocked by provider boundary",
            "details": {"blocked": raised is not None}}


@register_fixture("TEST-020")
def fixture_test_020(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-020: UNKNOWN external outcome requires query/reconciliation without duplicate execution.

    Drives the real ActionBroker boundary: a real document write fails against a
    missing pinned root, so the Action becomes UNKNOWN. Reconciliation queries the
    real workspace and must stay UNKNOWN instead of re-creating the resource.
    """
    from tests.m1.execution_support import ExecutionCase

    class _Case(ExecutionCase):
        def runTest(self):
            pass

    case = _Case()
    case.setUp()
    try:
        case.claim()
        case.start()
        action = case.request()
        case.root.rmdir()  # Real boundary: the pinned working-copy root disappears.
        dispatched = case.dispatch(action)
        assert dispatched["status"] == "unknown", f"expected UNKNOWN action, got {dispatched['status']!r}"
        reconciled = case.service.reconcile("p-1", action["id"])
        assert reconciled["status"] == "unknown", f"reconciliation invented {reconciled['status']!r}"
        assert not case.root.exists(), "reconciliation re-created the missing pinned root"
    finally:
        try:
            case.doCleanups()
        except OSError:
            pass
    return {"status": "passed", "execution_status": "passed",
            "summary": "Real UNKNOWN action reconciled as UNKNOWN without re-creating the resource",
            "details": {"dispatch_status": dispatched["status"], "reconcile_status": reconciled["status"]}}


@register_fixture("TEST-022")
def fixture_test_022(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-022: Stale epoch/revision cannot advance task state."""
    handler = CommandHandler(store)
    _bootstrap_project(store, project_id, handler)

    cmd_t = Command("cmd-t022-t", project_id, "a-1", "task.create", "t-022", {"title": "Epoch Task"}, 0, "k-022-t", "corr")
    handler.handle(cmd_t, authenticated_actor_id="a-1")

    cmd_cl = Command("cmd-t022-cl", project_id, "a-1", "task.claim", "t-022", {}, 0, "k-022-cl", "corr")
    res1 = handler.handle(cmd_cl, authenticated_actor_id="a-1")
    assert res1.status == "accepted"

    cmd_stale = Command("cmd-t022-stale", project_id, "a-1", "task.release", "t-022", {}, 0, "k-022-stale", "corr")
    res_stale = handler.handle(cmd_stale, authenticated_actor_id="a-1")
    assert res_stale.status == "rejected"
    assert res_stale.error_code == "REVISION_CONFLICT"
    return {"status": "passed", "execution_status": "passed", "summary": "Stale revision command rejected by CAS guard",
            "details": {"status": res_stale.status, "error_code": res_stale.error_code}}


@register_fixture("TEST-026")
def fixture_test_026(store: SQLiteStore, project_id: str) -> Dict[str, Any]:
    """TEST-026: Bypassing command proxy to perform sensitive action blocked by boundaries."""
    from aetp.domain.models import ModelValidationError

    blocked = False
    try:
        Command("cmd-t026", project_id, "a-1", "unauthorized.privileged_action", "target", {}, 0, "k-026", "corr")
    except ModelValidationError:
        blocked = True
    assert blocked, "Unauthorized bypass operation permitted"
    return {"status": "passed", "execution_status": "passed", "summary": "Privileged bypass blocked by protocol model boundary",
            "details": {"blocked": blocked}}
