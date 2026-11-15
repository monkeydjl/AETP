"""The qualification gate must not treat an unmeasured isolation claim as met.

Specification source: Docs/AETP-设计方案.md §13.9 ("能力声明不是安全证明",
anti-bypass) and §6.4 (the qualification gate runs before any scoring).

The gap closed here: `RuntimeEnforcement.workspace_isolation` was a free string
and `is_eligible_for_high_risk()` never looked at it, so an adapter could declare
`os_sandbox` - or any word at all - and still pass the gate with no host
boundary behind it.
"""

import unittest

from aetp.runtime.adapters import (
    WORKSPACE_ISOLATION_LEVELS,
    RuntimeCapability,
    RuntimeEnforcement,
    verified_workspace_isolation,
)


def capability(workspace_isolation="working_copy", **kwargs):
    return RuntimeCapability(
        adapter_id="candidate",
        version="1.0",
        enforcement=RuntimeEnforcement(mode="mediated", workspace_isolation=workspace_isolation, **kwargs),
    )


class IsolationQualificationGateTests(unittest.TestCase):
    def test_declared_but_unmeasured_os_sandbox_does_not_pass_the_gate(self):
        cap = capability("os_sandbox")
        self.assertEqual(cap.enforcement.workspace_isolation, "os_sandbox")
        self.assertFalse(verified_workspace_isolation(cap.enforcement))
        self.assertFalse(cap.is_eligible_for_high_risk(),
                         "a declaration alone must not satisfy §13.9 / §6.4")

    def test_free_text_isolation_claim_is_not_honoured(self):
        for claim in ("container", "vm", "os_sandbox_v2", "", "OS_SANDBOX"):
            with self.subTest(claim=claim):
                cap = capability(claim)
                self.assertFalse(verified_workspace_isolation(cap.enforcement))
                self.assertFalse(cap.is_eligible_for_high_risk())

    def test_working_copy_is_the_verified_floor(self):
        self.assertIn("working_copy", WORKSPACE_ISOLATION_LEVELS)
        cap = capability("working_copy")
        self.assertTrue(verified_workspace_isolation(cap.enforcement))
        self.assertTrue(cap.is_eligible_for_high_risk())

    def test_mediated_mode_is_still_required(self):
        cap = capability("working_copy", pre_tool_authorization=False)
        self.assertTrue(verified_workspace_isolation(cap.enforcement))
        self.assertFalse(cap.is_eligible_for_high_risk())
