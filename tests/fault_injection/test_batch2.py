"""AETP Fault Injection Test Suite: Batch 2 (FI-09 through FI-15).

Specification source: Docs/AETP-设计方案.md §§18.2, 11.4, 14.1-14.4, 16.
Tests governance binding, pause barriers, gate evasion, baseline conflict and workspace isolation.
"""

from __future__ import annotations

import os
import pathlib
import tempfile
import unittest

from aetp.collaboration.policy import PolicyViolation
from aetp.core.commands import CommandHandler
from aetp.domain.models import Command
from aetp.governance.approvals import transition
from aetp.governance.trust import InputAuthority
from aetp.integration.gate import validate_merge
from aetp.planning.service import PlanningService
from aetp.quality.evidence import evaluate_task
from aetp.storage.sqlite_store import SQLiteStore
from aetp.workspace.documents import DocumentWorkspace
from aetp.workspace.windows_files import WorkspaceViolation
from tests.m2.governance_support import GovernanceCase, policy


class FaultInjectionBatch2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aetp-fi-b2-")
        self.db_path = os.path.join(self.tmp, "fi_batch2.sqlite")
        self.store = SQLiteStore.open(self.db_path)
        self.handler = CommandHandler(self.store)
        self.project_id = "p-fi-b2"
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
        c_proj = Command("cmd-p2", self.project_id, "bootstrap", "project.create", None, {"status": "planning"}, 0, "k-p2", "corr")
        self.handler.handle(c_proj, authenticated_actor_id="bootstrap")
        c_a1 = Command("cmd-a1-2", self.project_id, "bootstrap", "agent.register", "a-1", {"model_id": "m1", "status": "available"}, 0, "k-a1-2", "corr")
        self.handler.handle(c_a1, authenticated_actor_id="bootstrap")
        c_a2 = Command("cmd-a2-2", self.project_id, "bootstrap", "agent.register", "a-2", {"model_id": "m2", "status": "available"}, 0, "k-a2-2", "corr")
        self.handler.handle(c_a2, authenticated_actor_id="bootstrap")

    def test_fi_09_approval_arguments_tampered_rejected(self):
        """FI-09: Tampering with approved arguments is rejected by live approval binding."""
        class _Case(GovernanceCase):
            def runTest(self):
                pass

        case = _Case()
        case.setUp()
        try:
            case.request_approval("ap-fi09")
            case.accept(case.grant("ap-fi09"))

            # Tampered arguments submitted using original approval_id
            case.ereject(
                case.command("tool.request", "t-1", {
                    **case.fence(),
                    "operation": "document.write",
                    "arguments": {"content": "Tampered payload after approval"},
                    "approval_id": "ap-fi09",
                }),
                "APPROVAL_STALE",
                session=case.session,
            )

            # Untampered original arguments succeed
            case.request_document("ap-fi09", "Scope and Recovery")
        finally:
            try:
                case.doCleanups()
            except OSError:
                pass

    def test_fi_10_approval_expiration_escalation(self):
        """FI-10: Approval expiration creates explicit escalation resolution instead of silent hang."""
        approval = {
            "id": "app-fi10",
            "status": "pending",
            "revision": 1,
            "expires_at": 1000,
            "on_expire": "escalate",
            "action": "task.quality.complete",
            "actor_id": "a-1",
            "delegated_to": None,
            "revocable_until": None,
            "target_id": "t-1",
            "target": {"type": "task", "id": "t-1", "revision": 1},
            "reason": "Test approval",
            "risk_level": "medium",
            "rules": [],
            "arguments_digest": "sha256:" + "0" * 64,
            "scope": "task",
        }
        state = {
            f"project:{self.project_id}": {"status": "active", "clock_offset_ms": 0, "revision": 1},
            f"approval:{approval['id']}": approval,
        }
        cmd_expire = Command("cmd-fi10-exp", self.project_id, "system", "approval.expire", approval["id"], {}, 1, "k-fi10", "corr")
        event_type, updated = transition(cmd_expire, approval, state, at=2000, context={})
        self.assertEqual(event_type, "approval.expired")
        self.assertEqual(updated["status"], "expired")
        self.assertEqual(updated.get("expiration_resolution", {}).get("kind"), "escalate")

    def test_fi_11_paused_project_rejects_advancement(self):
        """FI-11: PAUSED project blocks commands advancing state while freezing governance clock."""
        planning = PlanningService(self.store, owner_id="human-owner")
        pol = policy("gov-fi11")
        c_gov = Command("cmd-fi11-gov", self.project_id, "human-owner", "project.governance.configure", self.project_id, {"policy": pol}, 0, "k-fi11-g", "corr")
        planning.handle(c_gov, authenticated_actor_id="human-owner")

        # Pause project
        c_pause = Command("cmd-fi11-p", self.project_id, "human-owner", "project.pause", self.project_id, {
            "intervention_id": "int-fi11", "reason": "Emergency audit pause", "impact": "project"
        }, 1, "k-fi11-p", "corr")
        r_p = planning.handle(c_pause, authenticated_actor_id="human-owner")
        self.assertEqual(r_p.status, "accepted")

        # Attempt to configure planning while paused
        c_cfg = Command("cmd-fi11-cfg", self.project_id, "human-owner", "project.planning.configure", self.project_id, {"mode": "candidate_only"}, 2, "k-fi11-cfg", "corr")
        r_cfg = planning.handle(c_cfg, authenticated_actor_id="human-owner")
        self.assertEqual(r_cfg.status, "rejected")
        self.assertEqual(r_cfg.error_code, "PROJECT_PAUSED")

    def test_fi_12_quality_gate_evasion_blocked(self):
        """FI-12: Task cannot bypass in_review status or verification to enter verified/completed."""
        task = {"id": "t-evasion", "status": "active", "revision": 1}
        cmd = Command("cmd-fi12", self.project_id, "a-1", "task.quality.evaluate", "t-evasion", {}, 1, "k-fi12", "corr")
        with self.assertRaises(PolicyViolation) as ctx:
            evaluate_task(cmd, {}, task, 100, {"channel": "agent"})
        self.assertEqual(ctx.exception.code, "INVALID_TRANSITION")

    def test_fi_13_target_baseline_advanced_merge_blocked(self):
        """FI-13: Advanced target branch baseline triggers merge conflict guard."""
        task = {"id": "t-merge", "status": "ready_for_integration"}
        payload = {
            "target_ref": "refs/heads/main",
            "expected_target_commit": "1111111111111111111111111111111111111111",
            "current_target_commit": "2222222222222222222222222222222222222222",  # advanced by peer
        }
        with self.assertRaises(PolicyViolation) as ctx:
            validate_merge(task, payload)
        self.assertEqual(ctx.exception.code, "BASELINE_ADVANCED")

    def test_fi_14_cross_workspace_provider_boundary_blocked(self):
        """FI-14: Accessing paths across workspace boundaries without valid identity is blocked."""
        with tempfile.TemporaryDirectory(prefix="aetp-fi14-") as tmpdir:
            ws = DocumentWorkspace(pathlib.Path(tmpdir))
            foreign_action = {
                "workspace_provider_id": "untrusted-external-workspace",
                "target_path": "secret.txt",
                "id": "foreign-act",
            }
            with self.assertRaises(WorkspaceViolation):
                ws.path_for(foreign_action)

    def test_fi_15_untrusted_input_blocked_without_receipt(self):
        """FI-15: Untrusted input without authentic cryptographic receipt is blocked."""
        authority = InputAuthority("fi-gateway")
        cmd = Command("cmd-fi15", self.project_id, "a-1", "task.create", "t-fi15", {"title": "Untrusted"}, 0, "k-fi15", "corr")
        with self.assertRaises(PolicyViolation) as ctx:
            authority.verify(cmd, None)
        self.assertEqual(ctx.exception.code, "INPUT_CONTEXT_INVALID")
