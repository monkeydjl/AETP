"""AETP Fault Injection Test Suite: Batch 1 (FI-01 through FI-08).

Specification source: Docs/AETP-设计方案.md §§18.2, 11.4, 14.1-14.4, 16.
Tests anti-fragility and deterministic recovery under synthetic and environment failures.
"""

from __future__ import annotations

import os
import tempfile
import unittest

from aetp.core.commands import CommandHandler
from aetp.core.projection import Projection
from aetp.domain.models import Command
from aetp.planning.service import PlanningService
from aetp.storage.sqlite_store import SQLiteStore
from tests.m1.execution_support import ExecutionCase
from tests.m2.governance_support import policy


class FaultInjectionBatch1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aetp-fi-b1-")
        self.db_path = os.path.join(self.tmp, "fi_batch1.sqlite")
        self.store = SQLiteStore.open(self.db_path)
        self.handler = CommandHandler(self.store)
        self.project_id = "p-fi-b1"
        self._bootstrap_project()

    def tearDown(self):
        try:
            self.store.close()
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            if os.path.exists(self.tmp):
                os.rmdir(self.tmp)
        except OSError:
            pass

    def _bootstrap_project(self):
        c_proj = Command("cmd-p", self.project_id, "bootstrap", "project.create", None, {"status": "planning"}, 0, "k-p", "corr")
        self.handler.handle(c_proj, authenticated_actor_id="bootstrap")
        c_a1 = Command("cmd-a1", self.project_id, "bootstrap", "agent.register", "a-1", {"model_id": "m1", "status": "available"}, 0, "k-a1", "corr")
        self.handler.handle(c_a1, authenticated_actor_id="bootstrap")
        c_a2 = Command("cmd-a2", self.project_id, "bootstrap", "agent.register", "a-2", {"model_id": "m2", "status": "available"}, 0, "k-a2", "corr")
        self.handler.handle(c_a2, authenticated_actor_id="bootstrap")

    def test_fi_01_agent_crash_and_lease_reassignment(self):
        """FI-01: Agent crash simulation - task lease released and safely reassigned."""
        c_task = Command("cmd-fi01-t", self.project_id, "a-1", "task.create", "task-fi-01", {"title": "Crash task"}, 0, "k-fi01-t", "corr")
        r_t = self.handler.handle(c_task, authenticated_actor_id="a-1")
        self.assertEqual(r_t.status, "accepted")

        # a-1 claims task
        c_cl1 = Command("cmd-fi01-cl1", self.project_id, "a-1", "task.claim", "task-fi-01", {}, 0, "k-fi01-cl1", "corr")
        r_cl1 = self.handler.handle(c_cl1, authenticated_actor_id="a-1")
        self.assertEqual(r_cl1.status, "accepted")

        # a-1 crashes -> lease released
        c_rel = Command("cmd-fi01-rel", self.project_id, "a-1", "task.release", "task-fi-01", {}, 1, "k-fi01-rel", "corr")
        r_rel = self.handler.handle(c_rel, authenticated_actor_id="a-1")
        self.assertEqual(r_rel.status, "accepted")

        # a-2 reclaims task
        c_cl2 = Command("cmd-fi01-cl2", self.project_id, "a-2", "task.claim", "task-fi-01", {}, 2, "k-fi01-cl2", "corr")
        r_cl2 = self.handler.handle(c_cl2, authenticated_actor_id="a-2")
        self.assertEqual(r_cl2.status, "accepted")

        # State check
        state = Projection.rebuild(self.store.read_events(self.project_id))
        task = state["task:task-fi-01"]
        self.assertEqual(task["status"], "assigned")
        self.assertEqual(task["owner_id"], "a-2")

    def test_fi_02_post_commit_response_loss_idempotent_retry(self):
        """FI-02: Client re-submits identical command after lost response without duplicating events."""
        cmd = Command("cmd-fi02", self.project_id, "a-1", "task.create", "task-fi-02", {"title": "Retry task"}, 0, "k-fi02", "corr")
        res1 = self.handler.handle(cmd, authenticated_actor_id="a-1")
        self.assertEqual(res1.status, "accepted")

        events_before = len(self.store.read_events(self.project_id))
        # Simulated retry after network disconnect
        fresh_handler = CommandHandler(self.store)
        res2 = fresh_handler.handle(cmd, authenticated_actor_id="a-1")
        self.assertEqual(res2.status, "accepted")
        self.assertEqual(res2.aggregate_revision, res1.aggregate_revision)

        events_after = len(self.store.read_events(self.project_id))
        self.assertEqual(events_before, events_after, "Duplicate events appended on idempotent retry")

    def test_fi_03_idempotency_key_reused_with_conflicting_payload(self):
        """FI-03: Reusing an idempotency key with conflicting payload is strictly rejected."""
        cmd1 = Command("cmd-fi03-1", self.project_id, "a-1", "task.create", "task-fi-03", {"title": "Original payload"}, 0, "k-fi03", "corr")
        res1 = self.handler.handle(cmd1, authenticated_actor_id="a-1")
        self.assertEqual(res1.status, "accepted")

        # Conflicting payload with identical key
        cmd2 = Command("cmd-fi03-2", self.project_id, "a-1", "task.create", "task-fi-03", {"title": "Conflicting payload"}, 0, "k-fi03", "corr")
        res2 = self.handler.handle(cmd2, authenticated_actor_id="a-1")
        self.assertEqual(res2.status, "rejected")
        self.assertEqual(res2.error_code, "IDEMPOTENCY_CONFLICT")

    def test_fi_04_concurrent_cas_claim_race(self):
        """FI-04: Concurrent claims based on identical revision serialize via CAS; exactly one succeeds."""
        c_task = Command("cmd-fi04-t", self.project_id, "a-1", "task.create", "task-fi-04", {"title": "CAS task"}, 0, "k-fi04-t", "corr")
        self.handler.handle(c_task, authenticated_actor_id="a-1")

        # Both agents attempt to claim using expected_revision=0
        c_cl1 = Command("cmd-fi04-cl1", self.project_id, "a-1", "task.claim", "task-fi-04", {}, 0, "k-fi04-cl1", "corr")
        c_cl2 = Command("cmd-fi04-cl2", self.project_id, "a-2", "task.claim", "task-fi-04", {}, 0, "k-fi04-cl2", "corr")

        res1 = self.handler.handle(c_cl1, authenticated_actor_id="a-1")
        res2 = self.handler.handle(c_cl2, authenticated_actor_id="a-2")

        statuses = [res1.status, res2.status]
        self.assertEqual(statuses.count("accepted"), 1)
        self.assertEqual(statuses.count("rejected"), 1)
        rejected_res = res1 if res1.status == "rejected" else res2
        self.assertEqual(rejected_res.error_code, "REVISION_CONFLICT")

    def test_fi_05_projection_cache_loss_and_pure_rebuild(self):
        """FI-05: Deletion of state projection cache recovers identically from event store alone."""
        # Create a task and verify cached projection
        c_task = Command("cmd-fi05-t", self.project_id, "a-1", "task.create", "task-fi-05", {"title": "Projection test"}, 0, "k-fi05-t", "corr")
        self.handler.handle(c_task, authenticated_actor_id="a-1")

        state_before = self.store.read_projection(self.project_id)
        self.assertIn("task:task-fi-05", state_before)

        # Drop the cache tables
        conn = self.store._ensure_open()
        conn.execute("DELETE FROM projections WHERE project_id = ?", (self.project_id,))
        conn.execute("DELETE FROM projection_meta WHERE project_id = ?", (self.project_id,))

        # Pure event rebuild
        events = self.store.read_events(self.project_id)
        state_after = Projection.rebuild(events)
        self.assertEqual(state_before, state_after)

    def test_fi_06_external_action_unknown_and_reconciliation(self):
        """FI-06: Unknown external outcome triggers reconciliation guard and avoids duplicate execution."""
        class _Case(ExecutionCase):
            def runTest(self):
                pass

        case = _Case()
        case.setUp()
        try:
            case.claim()
            case.start()
            action = case.request()
            # Simulate environment failure: pinned workspace directory disappears
            case.root.rmdir()
            dispatched = case.dispatch(action)
            self.assertEqual(dispatched["status"], "unknown")

            # Reconcile queries workspace; must remain unknown and not re-create root
            reconciled = case.service.reconcile("p-1", action["id"])
            self.assertEqual(reconciled["status"], "unknown")
            self.assertFalse(case.root.exists(), "Reconciliation unexpectedly re-created deleted workspace")
        finally:
            try:
                case.doCleanups()
            except OSError:
                pass

    def test_fi_07_actor_identity_spoofing_rejected(self):
        """FI-07: Declared actor mismatched from authenticated channel actor is rejected."""
        cmd = Command("cmd-fi07", self.project_id, "a-1", "task.create", "task-fi-07", {"title": "Spoofed"}, 0, "k-fi07", "corr")
        # authenticated as a-2 while claiming to be a-1
        res = self.handler.handle(cmd, authenticated_actor_id="a-2")
        self.assertEqual(res.status, "rejected")
        self.assertEqual(res.error_code, "ACTOR_MISMATCH")

    def test_fi_08_unapproved_high_risk_call_rejected(self):
        """FI-08: Attempting high-risk action without governance policy approval is rejected."""
        planning = PlanningService(self.store, owner_id="human-owner")
        pol = policy("gov-fi08")
        c_gov = Command("cmd-fi08-gov", self.project_id, "human-owner", "project.governance.configure", self.project_id, {"policy": pol}, 0, "k-fi08-g", "corr")
        res_gov = planning.handle(c_gov, authenticated_actor_id="human-owner")
        self.assertEqual(res_gov.status, "accepted")

        c_cfg = Command("cmd-fi08-cfg", self.project_id, "human-owner", "project.planning.configure", self.project_id, {"mode": "candidate_only"}, 1, "k-fi08-c", "corr")
        res_cfg = planning.handle(c_cfg, authenticated_actor_id="human-owner")
        self.assertEqual(res_cfg.status, "accepted")

        c_m = Command("cmd-fi08-m", self.project_id, "a-1", "mission.propose", "m-fi08", {
            "content": {"title": "M", "objective": "O", "constraints": ["c"], "success_criteria": ["s1"]}
        }, 0, "k-fi08-m", "corr")
        res_m = planning.handle(c_m, authenticated_actor_id="a-1")
        self.assertEqual(res_m.status, "accepted")

        # a-1 tries to activate without human_owner role
        c_act = Command("cmd-fi08-act", self.project_id, "a-1", "mission.activate", "m-fi08", {}, 0, "k-fi08-act", "corr")
        res = planning.handle(c_act, authenticated_actor_id="a-1")
        self.assertEqual(res.status, "rejected")
        self.assertEqual(res.error_code, "ENFORCEMENT_UNAVAILABLE")
