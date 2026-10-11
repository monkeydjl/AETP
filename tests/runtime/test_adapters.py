"""Unit tests for RuntimeAdapter contract and capability declarations."""

import unittest
from aetp.runtime.adapters import (
    AdapterSecurityError,
    RuntimeAdapter,
    RuntimeCapability,
    RuntimeEnforcement,
)


class DummyTestAdapter(RuntimeAdapter):
    def start_session(self, session_id, context):
        return {"session_id": session_id, "status": "started"}

    def stop_session(self, session_id, reason):
        return {"session_id": session_id, "status": "stopped", "reason": reason}

    def execute_tool(self, session_id, tool_name, arguments, *, authorization_context=None):
        if self.is_paused:
            raise AdapterSecurityError("PROJECT_PAUSED", "Runtime execution is paused")
        if authorization_context is None:
            raise AdapterSecurityError("PRE_TOOL_UNAUTHORIZED", "Missing pre-tool authorization")
        return {"tool": tool_name, "result": "executed"}


class RuntimeAdapterContractTests(unittest.TestCase):
    def test_mediated_capability_eligible_for_high_risk(self):
        cap = RuntimeCapability(
            adapter_id="codeg-mediated",
            version="1.0",
            enforcement=RuntimeEnforcement(mode="mediated", pre_tool_authorization=True, authenticated_actor=True),
        )
        self.assertTrue(cap.is_eligible_for_high_risk())
        d = cap.to_dict()
        self.assertEqual(d["adapter_id"], "codeg-mediated")
        self.assertEqual(d["enforcement"]["mode"], "mediated")

    def test_enforcement_declares_network_egress_boundary(self):
        """Spec 13.9 enforcement yaml requires a network_egress field."""
        enforcement = RuntimeEnforcement(mode="mediated", network_egress="allowlist")
        self.assertEqual(enforcement.network_egress, "allowlist")
        # Default is the most conservative boundary (disabled) when unspecified.
        default = RuntimeEnforcement(mode="mediated")
        self.assertEqual(default.network_egress, "disabled")
        # Capability serialization carries the network_egress declaration.
        cap = RuntimeCapability(adapter_id="a", version="1.0", enforcement=enforcement)
        self.assertEqual(cap.to_dict()["enforcement"]["network_egress"], "allowlist")

    def test_observation_only_capability_ineligible_for_high_risk(self):
        cap = RuntimeCapability(
            adapter_id="basic-cli",
            version="0.1",
            enforcement=RuntimeEnforcement(mode="observation_only", pre_tool_authorization=False),
        )
        self.assertFalse(cap.is_eligible_for_high_risk())

    def test_adapter_pause_and_resume_lifecycle(self):
        cap = RuntimeCapability(adapter_id="test-adapter", version="1.0")
        adapter = DummyTestAdapter(cap)
        self.assertFalse(adapter.is_paused)

        adapter.pause()
        self.assertTrue(adapter.is_paused)
        with self.assertRaises(AdapterSecurityError) as ctx:
            adapter.execute_tool("s-1", "shell", {"cmd": "ls"}, authorization_context={"token": "t"})
        self.assertEqual(ctx.exception.code, "PROJECT_PAUSED")

        adapter.resume()
        self.assertFalse(adapter.is_paused)
        res = adapter.execute_tool("s-1", "shell", {"cmd": "ls"}, authorization_context={"token": "t"})
        self.assertEqual(res["result"], "executed")
