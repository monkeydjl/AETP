"""Wiring for the trusted git provider into the git.merge dispatch path.

Specification source: Docs/AETP-设计方案.md §10.6 — when a trusted git
Workspace Provider is present, git.merge must perform a real merge (re-cheeking
the target tip and returning conflicts), never trusting caller-supplied
``current_target_commit``/``has_conflict``/``result_commit`` strings.
"""

import unittest

from aetp.collaboration.policy import PolicyViolation
from aetp.integration.gate import dispatch_merge


class _FakeProvider:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def merge(self, source_ref, target_ref, expected_target_commit):
        self.calls.append((source_ref, target_ref, expected_target_commit))
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class DispatchMergeTests(unittest.TestCase):
    def _task(self):
        return {"id": "t-1", "status": "ready_for_integration"}

    def test_no_provider_falls_back_to_simulated_validate(self):
        """Without a provider, the simulated validate path still applies."""
        task = self._task()
        payload = {
            "expected_target_commit": "2" * 40,
            "current_target_commit": "2" * 40,
            "result_commit": "3" * 40,
        }
        result = dispatch_merge(None, task, payload)
        self.assertEqual(result, {"conflict": False, "conflict_paths": [], "result_commit": "3" * 40})

    def test_with_provider_and_real_fields_runs_real_merge(self):
        """A trusted provider with real merge fields performs the real merge."""
        provider = _FakeProvider({"status": "merged", "result_commit": "a" * 40})
        task = self._task()
        payload = {
            "source_ref": "refs/heads/feature",
            "target_ref": "refs/heads/main",
            "expected_target_commit": "b" * 40,
            # forged values that a real path must ignore
            "current_target_commit": "0" * 40,
            "has_conflict": True,
            "conflict_paths": ["fake.txt"],
            "result_commit": "deadbeef",
        }
        result = dispatch_merge(provider, task, payload)
        self.assertEqual(result, {"conflict": False, "conflict_paths": [], "result_commit": "a" * 40})
        self.assertEqual(provider.calls, [("refs/heads/feature", "refs/heads/main", "b" * 40)])

    def test_with_provider_conflict_returns_conflict_paths(self):
        provider = _FakeProvider({"status": "conflict", "conflict_paths": ["src/a.py"]})
        task = self._task()
        payload = {
            "source_ref": "refs/heads/feature",
            "target_ref": "refs/heads/main",
            "expected_target_commit": "c" * 40,
            "has_conflict": False,
            "result_commit": "deadbeef",
        }
        result = dispatch_merge(provider, task, payload)
        self.assertEqual(result, {"conflict": True, "conflict_paths": ["src/a.py"], "result_commit": None})

    def test_with_provider_stale_baseline_propagates_policy_violation(self):
        provider = _FakeProvider(PolicyViolation("BASELINE_ADVANCED"))
        task = self._task()
        payload = {
            "source_ref": "refs/heads/feature",
            "target_ref": "refs/heads/main",
            "expected_target_commit": "d" * 40,
        }
        with self.assertRaises(PolicyViolation) as ctx:
            dispatch_merge(provider, task, payload)
        self.assertEqual(ctx.exception.code, "BASELINE_ADVANCED")

    def test_no_provider_no_real_fields_still_validates_status(self):
        """Even fallback path checks task status via validate_merge."""
        task = {"id": "t-1", "status": "verified"}
        payload = {"expected_target_commit": "2" * 40, "current_target_commit": "2" * 40}
        with self.assertRaises(PolicyViolation) as ctx:
            dispatch_merge(None, task, payload)
        self.assertEqual(ctx.exception.code, "INVALID_TASK_STATUS")

    def test_with_provider_also_rejects_non_ready_task(self):
        """The real merge path must not run on a non-ready Task either."""
        provider = _FakeProvider({"status": "merged", "result_commit": "a" * 40})
        task = {"id": "t-1", "status": "verified"}
        payload = {
            "source_ref": "refs/heads/feature",
            "target_ref": "refs/heads/main",
            "expected_target_commit": "e" * 40,
        }
        with self.assertRaises(PolicyViolation) as ctx:
            dispatch_merge(provider, task, payload)
        self.assertEqual(ctx.exception.code, "INVALID_TASK_STATUS")
        self.assertEqual(provider.calls, [])


if __name__ == "__main__":
    unittest.main()
