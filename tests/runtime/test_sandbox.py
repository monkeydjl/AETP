"""Unit tests for SandboxRuntimeAdapter and pre-tool authorization boundaries."""

import hashlib
import json
import os
import tempfile
import unittest

from aetp.runtime.adapters import AdapterSecurityError
from aetp.runtime.sandbox import PreToolAuthorizer, SandboxRuntimeAdapter


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

    def test_shell_executes_real_command_and_captures_output(self):
        """shell is a real subprocess, not an echo; stdout is captured."""
        res = self.adapter.execute_tool(
            self.session_id, "shell",
            {"command": "python -c \"print('sandbox_real')\""},
            authorization_context=self._shell_auth(),
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["exit_code"], 0)
        self.assertIn("sandbox_real", res["stdout"])

    def test_shell_cwd_is_locked_to_workspace(self):
        """shell subprocess working directory is pinned to the workspace root."""
        res = self.adapter.execute_tool(
            self.session_id, "shell",
            {"command": "python -c \"import os; print(os.getcwd())\""},
            authorization_context=self._shell_auth(),
        )
        self.assertEqual(res["status"], "success")
        printed = res["stdout"].strip().splitlines()[-1]
        self.assertEqual(printed, str(self.adapter.workspace_root))

    def test_shell_nonzero_exit_is_reported_not_masked(self):
        """A failing command returns status failed with the real exit code."""
        res = self.adapter.execute_tool(
            self.session_id, "shell",
            {"command": "python -c \"import sys; sys.exit(7)\""},
            authorization_context=self._shell_auth(),
        )
        self.assertEqual(res["status"], "failed")
        self.assertEqual(res["exit_code"], 7)

    def test_shell_timeout_is_reported(self):
        """A long-running command is bounded by timeout and reported."""
        adapter = SandboxRuntimeAdapter(self.adapter.workspace_root, shell_timeout=1)
        adapter.start_session(self.session_id, self.session_context)
        res = adapter.execute_tool(
            self.session_id, "shell",
            {"command": "python -c \"import time; time.sleep(60)\""},
            authorization_context=self._shell_auth(),
        )
        self.assertEqual(res["status"], "timeout")

    def test_shell_timeout_actually_terminates_within_bound(self):
        """Timeout must really kill the process tree, not wait for it to finish."""
        import time
        adapter = SandboxRuntimeAdapter(self.adapter.workspace_root, shell_timeout=1)
        adapter.start_session(self.session_id, self.session_context)
        t0 = time.monotonic()
        res = adapter.execute_tool(
            self.session_id, "shell",
            {"command": "python -c \"import time; time.sleep(30)\""},
            authorization_context=self._shell_auth(),
        )
        elapsed = time.monotonic() - t0
        self.assertEqual(res["status"], "timeout")
        # Timeout must return promptly (within a generous bound), not after the
        # spawned grandchild finishes naturally.
        self.assertLess(elapsed, 5.0, f"timeout took {elapsed:.1f}s; child was not killed")
