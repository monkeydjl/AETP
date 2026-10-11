"""Exercise real Project pause/resume facts through the existing M1 service."""

from pathlib import Path
import json
import tempfile
from unittest.mock import patch

from aetp.runtime.document import DocumentRuntime
from aetp.core.projection import Projection
from aetp.domain.models import Event
from aetp.runtime.service import ExecutionService
from aetp.workspace.documents import DocumentWorkspace
from tests.m2.support import MeetingCase
from tests.m2.governance_support import GovernanceCase, GovernanceService, policy


class GovernanceTests(MeetingCase):
    def test_resume_without_runtime_rejects_receipt_only_history(self):
        self.service = GovernanceService(self.store, owner_id="human-owner", meter=self.meter,
                                         clock=lambda: self.clock_value)
        self.accept(self.command("project.governance.configure", "p-1", {"policy": policy()}, actor="human-owner"))
        self.accept(self.command("project.pause", "p-1", {"intervention_id": "human-pause",
            "reason": "Inspect unfinished work", "impact": "project"}, actor="human-owner"))
        pending = self.command("project.resume", "p-1", {"intervention_id": "interrupted-resume",
            "reason": "Continue planning", "impact": "project"}, actor="human-owner")
        with self.store.transaction():
            self.store.append_command(pending)
            self.store.append_events([Event(id=f"{pending.id}:received", project_id="p-1",
                sequence=self.store.next_sequence("p-1"), type="command.received", aggregate_type="project",
                aggregate_id="p-1", aggregate_revision=pending.expected_revision,
                causation_id=pending.id, correlation_id=pending.correlation_id,
                payload={"command_type": pending.type, "request_digest": pending.digest()})])
        before = self.state()
        self.assertNotIn("execution_policy_version", before["project:p-1"])
        self.assertEqual(Projection.pending_command_ids(self.store.read_events("p-1"), self.commands()), [pending.id])
        self.reject(self.command("project.resume", "p-1", {"intervention_id": "later-resume",
            "reason": "Try continuing planning", "impact": "project"}, actor="human-owner"), "RECOVERY_REQUIRED")
        self.assertEqual(self.state(), before)
        self.assertEqual(self.state()["project:p-1"]["status"], "paused")
        self.assertEqual(self.state()["project:p-1"]["dispatch_barrier"], "closed")
        self.assertNotIn("intervention:later-resume", self.state())
        self.assertNotIn("project.resumed", [event.type for event in self.store.read_events("p-1")])
        self.assertEqual(Projection.pending_command_ids(self.store.read_events("p-1"), self.commands()), [pending.id])

    def test_execution_configured_after_governance_pause_preserves_excluded_time(self):
        self.service = GovernanceService(self.store, owner_id="human-owner", meter=self.meter,
                                         clock=lambda: self.clock_value)
        self.accept(self.command("project.governance.configure", "p-1", {"policy": policy()}, actor="human-owner"))
        self.clock_value = 1004
        self.accept(self.command("project.pause", "p-1", {"intervention_id": "pre-execution-pause",
            "reason": "Human planning pause", "impact": "project"}, actor="human-owner"))
        self.clock_value = 10000
        self.accept(self.command("project.resume", "p-1", {"intervention_id": "pre-execution-resume",
            "reason": "Continue planning", "impact": "project"}, actor="human-owner"))
        before = self.state()["project:p-1"]["collaboration_clock"]
        self.assertEqual(before, {"excluded_ms": 8996, "paused_at_ms": None})
        self.configure_execution()
        self.assertEqual(self.state()["project:p-1"]["collaboration_clock"], before)
        self.open_discussion(time_budget_ms=10)
        self.assertEqual(self.state()["discussion:d"]["started_at_ms"], 1004)

    def test_prior_m1_cache_without_pause_metadata_rebuilds_before_m2_append(self):
        self.configure_execution()
        self.clock_value = 1005
        self.control("project.pause")
        self.clock_value = 9000
        self.control("project.resume")
        expected = Projection.rebuild(self.store.read_events("p-1"))
        legacy = self.state()
        legacy["project:p-1"].pop("collaboration_clock", None)
        sequence = self.store.read_events("p-1")[-1].sequence
        connection = self.store._ensure_open()
        connection.execute("UPDATE projections SET state_json=? WHERE project_id='p-1'", (json.dumps(legacy),))
        connection.execute("UPDATE projection_meta SET projection_digest=? WHERE project_id='p-1'",
                           (self.store._projection_digest("p-1", legacy, sequence),))
        self.assertEqual(self.state(), expected)
        self.open_discussion(time_budget_ms=10)
        self.assertEqual(self.state()["discussion:d"]["started_at_ms"], 1005)

    def configure_execution(self):
        root = Path(__file__).resolve().parents[2] / ".tmp"
        root.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="m2-governance-", dir=root)
        self.addCleanup(temporary.cleanup)
        self.execution = ExecutionService(self.store, DocumentRuntime(
            DocumentWorkspace(Path(temporary.name) / "workspace")), clock=lambda: self.clock_value)
        self.control("project.execution.configure")

    def control(self, kind):
        command = self.command(kind, "p-1", actor="bootstrap")
        result = self.execution.handle(command, authenticated_actor_id="bootstrap")
        self.assertEqual(result.status, "accepted", result.to_dict())

    def test_paused_project_accepts_existing_messages_and_freezes_time(self):
        self.open_discussion(time_budget_ms=10)
        self.configure_execution()
        self.clock_value = 1004
        self.control("project.pause")
        self.clock_value = 10000
        self.post("d", actor="a-2", category="disagreement", content="Existing objection while paused")
        self.assertEqual(self.state()["discussion:d"]["status"], "open")
        self.assertEqual(self.transcript("d")[0]["content"], "Existing objection while paused")
        self.control("project.resume")
        self.clock_value = 10005
        self.post("d")
        self.clock_value = 10006
        with self.assertRaisesRegex(Exception, "TIME_BUDGET_EXCEEDED|TIME_BUDGET_EXHAUSTED"):
            self.post("d")
        self.assertEqual(self.state()["discussion:d"]["termination_reason"], "time_budget")

    def test_paused_analysis_preserves_blindness_and_blocks_normal_advance(self):
        self.begin_meeting()
        self.configure_execution()
        self.control("project.pause")
        self.post("m", category="analysis", content="private paused answer")
        self.assertEqual(self.transcript("m", actor="a-2"), [])
        self.post("m", actor="a-2", category="analysis")
        self.reject(self.command("meeting.advance", "m"), "PROJECT_PAUSED")
        self.control("project.resume")
        self.accept(self.command("meeting.advance", "m"))
        self.assertEqual(len(self.transcript("m")), 2)

    def test_paused_budget_exhaustion_still_converges(self):
        self.open_discussion(token_budget=2)
        self.configure_execution()
        self.control("project.pause")
        self.post("d", tokens=2)
        self.assertEqual(self.state()["discussion:d"]["status"], "synthesizing")

    def test_later_execution_clock_configuration_does_not_reset_deadline(self):
        self.open_discussion(time_budget_ms=10)
        self.clock_value = 1008
        self.configure_execution()
        self.clock_value = 1010
        with self.assertRaisesRegex(Exception, "TIME_BUDGET_EXHAUSTED"):
            self.post("d")
        self.assertEqual(self.state()["discussion:d"]["termination_reason"], "time_budget")


class GovernanceControlTests(GovernanceCase):
    def test_pause_has_an_intervention_and_never_claims_full_execution_quiescence(self):
        command = self.control("pause", identifier="human-pause")
        self.accept(command)
        project = self.state()["project:p-1"]
        self.assertEqual(project["status"], "paused")
        self.assertEqual(project["dispatch_barrier"], "closed")
        self.assertEqual(project["execution_quiescence"], "unconfirmed")
        self.assertEqual(project["binding_pause_status"][self.session.binding_id]["pause_status"], "unsupported")
        intervention = self.state()["intervention:human-pause"]
        self.assertEqual(intervention["command"], command.id)
        self.assertEqual(intervention["actor"], {"type": "human", "id": "human-owner"})
        self.assertEqual(intervention["reason"], "Human changes scheduling")

    def test_pause_requires_human_and_legacy_execution_control_cannot_bypass_governance(self):
        self.reject(self.command("project.pause", "p-1", {"intervention_id": "x", "reason": "I claim human", "impact": "project"}), "PERMISSION_DENIED")
        self.ereject(self.command("project.pause", "p-1", actor="bootstrap"), "GOVERNANCE_REQUIRED")
        self.accept(self.control("pause"))
        self.ereject(self.command("project.resume", "p-1", actor="bootstrap"), "GOVERNANCE_REQUIRED")
        self.assertEqual(self.state()["project:p-1"]["status"], "paused")

    def test_paused_runtime_report_is_retained_without_quality_progress(self):
        self.accept(self.control("pause"))
        before = self.task()["status"]
        self.eaccept(self.command("execution.report", "t-1", {**self.fence(), "summary": "Work observed before pause"}), session=self.session)
        after = self.task()
        self.assertEqual(after["status"], before)
        self.assertTrue(after["last_execution_report"]["while_paused"])
        self.assertEqual(after["last_execution_report"]["authority"], "observation_only")

    def test_paused_messages_continue_but_tool_admission_and_grants_stop(self):
        self.open_discussion()
        self.request_approval()
        self.accept(self.control("pause"))
        self.post("d", actor="a-2", content="Keep discussing the constraint")
        self.assertEqual(self.transcript("d")[0]["author_id"], "a-2")
        self.reject(self.grant(), "PROJECT_PAUSED")
        self.ereject(self.command("tool.request", "t-1", {**self.fence(), "operation": "document.write",
            "arguments": {"content": "Scope and Recovery"}, "approval_id": "ap-1"}), "PROJECT_PAUSED", session=self.session)

    def test_governance_deadline_freezes_through_pause_and_resume(self):
        self.request_approval()
        self.clock_value = 1004
        self.accept(self.control("pause"))
        self.clock_value = 10000
        self.service.tick("p-1")
        self.assertEqual(self.approval()["status"], "pending")
        self.accept(self.control("resume"))
        self.assertEqual(self.approval()["expires_at"], 2000)
        self.clock_value = 10995
        self.service.tick("p-1")
        self.assertEqual(self.approval()["status"], "pending")
        self.clock_value = 10996
        self.service.tick("p-1")
        self.assertEqual(self.approval()["status"], "expired")

    def test_long_pause_does_not_extend_session_and_failed_resume_leaves_no_success_fact(self):
        self.accept(self.control("pause"))
        self.clock_value = self.session.expires_at_wall_ms
        self.reject(self.control("resume"), "RECOVERY_REQUIRED")
        self.assertEqual(self.state()["project:p-1"]["status"], "paused")
        self.assertNotIn("project.resumed", self.event_types())

    def test_restart_retains_pause_and_missing_session_cannot_resume(self):
        self.accept(self.control("pause"))
        from aetp.core.runtime import RuntimeRecovery
        recovery = RuntimeRecovery.open(self.fixture.db_path)
        try:
            self.assertEqual(recovery.rebuild_project("p-1")["project:p-1"]["status"], "paused")
            self.assertEqual(recovery.reconcile_pending("p-1"), [])
        finally:
            recovery.close()
        execution = ExecutionService(self.store, DocumentRuntime(self.workspace), clock=lambda: self.clock_value)
        service = GovernanceService(self.store, execution=execution, clock=lambda: self.clock_value)
        result = service.handle(self.control("resume"), authenticated_actor_id="human-owner")
        self.assertEqual(result.error_code, "RECOVERY_REQUIRED")
        self.assertEqual(self.state()["project:p-1"]["status"], "paused")

    def test_pause_and_resume_retries_do_not_duplicate_interventions(self):
        pause = self.control("pause")
        result = self.accept(pause)
        self.assertEqual(self.accept(pause), result)
        resume = self.control("resume")
        result = self.accept(resume)
        count = len(self.store.read_events("p-1"))
        self.assertEqual(self.accept(resume), result)
        self.assertEqual(len(self.store.read_events("p-1")), count)
        self.assertEqual(sum(key.startswith("intervention:") for key in self.state()), 2)

    def test_human_stop_cancels_task_and_revokes_binding_without_losing_in_flight_facts(self):
        self.request_approval()
        self.accept(self.grant())
        action = self.request_document()
        with patch.object(self.workspace, "write", side_effect=SystemExit("in-flight crash")):
            with self.assertRaises(SystemExit):
                self.execution.dispatch("p-1", action["id"], session=self.session)
        self.assertEqual(self.state()[f"action:{action['id']}"]["status"], "in_flight")
        self.accept(self.command("intervention.apply", "human-stop", {"action": "stop",
            "target": {"type": "task", "id": "t-1", "revision": self.task()["revision"]},
            "reason": "Stop this execution", "impact": "task"}, actor="human-owner"))
        self.assertEqual(self.task()["status"], "cancelled")
        self.assertTrue(self.task()["lease"]["revoked"])
        self.assertEqual(self.state()["intervention:human-stop"]["actor"]["id"], "human-owner")
        recovered = self.execution.recover("p-1")
        self.assertEqual(recovered["unknown_actions"], [action["id"]])
        self.assertEqual(recovered["barrier"], "closed")
        self.assertEqual(self.state()[f"action:{action['id']}"]["dispatch_count"], 1)
        self.assertEqual(self.task()["status"], "cancelled")

    def test_pause_after_effect_before_report_preserves_queryable_result_without_dispatch(self):
        self.request_approval()
        self.accept(self.grant())
        action = self.request_document()
        write = self.workspace.write
        def lost_report(record, authorize):
            write(record, authorize)
            raise SystemExit("lost report after actual write")
        with patch.object(self.workspace, "write", side_effect=lost_report):
            with self.assertRaises(SystemExit):
                self.execution.dispatch("p-1", action["id"], session=self.session)
        self.accept(self.control("pause"))
        with patch.object(self.workspace, "write", side_effect=AssertionError("recovery must only query")):
            status = self.execution.recover("p-1")
        self.assertEqual(status["barrier"], "closed")
        recovered = self.state()[f"action:{action['id']}"]
        self.assertEqual((recovered["status"], recovered["dispatch_count"]), ("completed", 1))
        self.assertEqual(self.state()["project:p-1"]["status"], "paused")
        self.assertEqual(self.task()["status"], "in_progress")

    def test_override_cannot_bypass_missing_quality_or_execution_enforcement(self):
        self.reject(self.command("intervention.apply", "bad-override", {"action": "override",
            "target": {"type": "task", "id": "t-1", "revision": self.task()["revision"]},
            "reason": "Mark complete anyway", "impact": "task"}, actor="human-owner"), "ENFORCEMENT_UNAVAILABLE")
        self.assertEqual(self.task()["status"], "in_progress")
