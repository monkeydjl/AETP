"""Unit tests for SandboxRuntimeAdapter and pre-tool authorization boundaries."""

import hashlib
import json
import os
import tempfile
import unittest

from aetp.runtime.adapters import AdapterSecurityError
from aetp.runtime.sandbox import SandboxRuntimeAdapter


class SandboxRuntimeAdapterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aetp-sandbox-test-")
        self.adapter = SandboxRuntimeAdapter(self.tmp)
        self.session_id = "sess-01"
        self.session_context = {
            "task_id": "t-1",
            "actor_id": "agent-worker",
            "lease_epoch": 1,
        }
        self.adapter.start_session(self.session_id, self.session_context)

    def tearDown(self):
        try:
            if os.path.exists(self.tmp):
                import shutil
                shutil.rmtree(self.tmp, ignore_errors=True)
        except OSError:
            pass

    def test_low_risk_tool_executes_without_approval(self):
        """Low risk tools (echo, query) can execute without an approval_id."""
        res = self.adapter.execute_tool(self.session_id, "echo", {"message": "hello world"})
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["output"], "hello world")

    def test_high_risk_tool_unauthorized_blocked(self):
        """High risk tool without approval_id is blocked by pre-tool check."""
        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.execute_tool(self.session_id, "fs_write", {"path": "file.txt", "content": "data"})
        self.assertEqual(ctx.exception.code, "PRE_TOOL_UNAUTHORIZED")

    def test_high_risk_tool_authorized_success(self):
        """High risk tool with approval_id executes successfully inside workspace."""
        auth_ctx = {
            "authenticated_actor_id": "agent-worker",
            "lease_epoch": 1,
            "approval_id": "app-001",
        }
        res = self.adapter.execute_tool(
            self.session_id,
            "fs_write",
            {"path": "file.txt", "content": "safe content"},
            authorization_context=auth_ctx,
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["bytes_written"], len("safe content"))

        # Verify read
        read_res = self.adapter.execute_tool(self.session_id, "fs_read", {"path": "file.txt"})
        self.assertEqual(read_res["status"], "success")
        self.assertEqual(read_res["content"], "safe content")

    def test_actor_mismatch_blocked(self):
        """Tool call with mismatched actor is rejected."""
        auth_ctx = {
            "authenticated_actor_id": "intruder-agent",
            "lease_epoch": 1,
            "approval_id": "app-001",
        }
        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.execute_tool(
                self.session_id,
                "fs_write",
                {"path": "file.txt", "content": "hack"},
                authorization_context=auth_ctx,
            )
        self.assertEqual(ctx.exception.code, "ACTOR_MISMATCH")

    def test_lease_expired_blocked(self):
        """Tool call with stale lease epoch is rejected."""
        auth_ctx = {
            "authenticated_actor_id": "agent-worker",
            "lease_epoch": 0,  # Stale epoch
            "approval_id": "app-001",
        }
        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.execute_tool(
                self.session_id,
                "fs_write",
                {"path": "file.txt", "content": "stale"},
                authorization_context=auth_ctx,
            )
        self.assertEqual(ctx.exception.code, "LEASE_EXPIRED")

    def test_tampered_arguments_blocked(self):
        """Tampering with arguments after approval is rejected."""
        args = {"path": "file.txt", "content": "original"}
        args_digest = "sha256:" + hashlib.sha256(
            json.dumps(args, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        auth_ctx = {
            "authenticated_actor_id": "agent-worker",
            "lease_epoch": 1,
            "approval_id": "app-001",
            "expected_arguments_digest": args_digest,
        }

        # Submit tampered arguments
        tampered_args = {"path": "file.txt", "content": "tampered"}
        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.execute_tool(
                self.session_id,
                "fs_write",
                tampered_args,
                authorization_context=auth_ctx,
            )
        self.assertEqual(ctx.exception.code, "APPROVAL_STALE")

    def test_workspace_boundary_escape_blocked(self):
        """Directory traversal attempt escaping workspace boundary is blocked."""
        auth_ctx = {
            "authenticated_actor_id": "agent-worker",
            "lease_epoch": 1,
            "approval_id": "app-001",
        }
        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.execute_tool(
                self.session_id,
                "fs_write",
                {"path": "../../etc/passwd", "content": "root"},
                authorization_context=auth_ctx,
            )
        self.assertEqual(ctx.exception.code, "WORKSPACE_VIOLATION")

    def test_paused_runtime_blocks_all_tools(self):
        """Paused runtime strictly blocks tool calls."""
        self.adapter.pause()
        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.execute_tool(self.session_id, "echo", {"message": "hello"})
        self.assertEqual(ctx.exception.code, "PROJECT_PAUSED")

    def _shell_auth(self):
        return {
            "authenticated_actor_id": "agent-worker",
            "lease_epoch": 1,
            "approval_id": "app-shell",
        }

    def test_shell_is_fail_closed(self):
        """Arbitrary shell was withdrawn (A1): a shell call is refused, never
        executed, because a pure-Python adapter cannot reliably stop a spawned
        subprocess from escaping the workspace via absolute paths."""
        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.execute_tool(
                self.session_id, "shell",
                {"command": "python -c \"open(r'escaped.txt','w').write('x')\""},
                authorization_context=self._shell_auth(),
            )
        self.assertEqual(ctx.exception.code, "ENFORCEMENT_UNAVAILABLE")

    def test_fs_write_still_enforces_workspace_boundary(self):
        """File access remains possible only through the path-prefix-checked
        fs_write tool, which still blocks traversal."""
        auth_ctx = {
            "authenticated_actor_id": "agent-worker",
            "lease_epoch": 1,
            "approval_id": "app-001",
        }
        with self.assertRaises(AdapterSecurityError) as ctx:
            self.adapter.execute_tool(
                self.session_id,
                "fs_write",
                {"path": "../../escaped.txt", "content": "x"},
                authorization_context=auth_ctx,
            )
        self.assertEqual(ctx.exception.code, "WORKSPACE_VIOLATION")

    def test_declared_capability_does_not_claim_isolation_it_cannot_prove(self):
        """§13.9: a capability must describe what the boundary actually enforces.

        The local adapter enforces a working-copy path prefix plus pre-tool
        checks. It does not run under an OS or container boundary and holds no
        separate credential store, so declaring anything stronger here would be
        the one failure §13.9 names explicitly: claiming a control that a raw
        shell can walk around.
        """
        enforcement = self.adapter.capability.enforcement
        self.assertEqual(enforcement.workspace_isolation, "working_copy")
        self.assertFalse(enforcement.credential_isolation)
        self.assertEqual(enforcement.network_egress, "disabled")

    def test_an_adapter_that_upgrades_its_isolation_claim_must_say_so_here(self):
        """Pins the other half: the declaration is a constant, not a guess.

        If someone later does bring a real OS/container boundary, this test is
        the deliberate place to change, so the upgrade cannot ship silently.
        """
        self.assertEqual(self.adapter.capability.adapter_id, "aetp-local-sandbox")
        self.assertEqual(self.adapter.capability.enforcement.mode, "mediated")
        self.assertTrue(self.adapter.capability.is_eligible_for_high_risk())
