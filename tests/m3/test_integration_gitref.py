"""True local git ref resolution for the Integration Gate baseline check.

Specification source: Docs/AETP-设计方案.md §10.6 (merge must re-check the
target branch tip at the real update site, not trust caller-supplied strings).
"""

import os
import subprocess
import tempfile
import unittest

from aetp.collaboration.policy import PolicyViolation
from aetp.integration.gitref import resolve_ref
from aetp.integration.gate import validate_merge_against_repo


def _git(repo, *args):
    return subprocess.run(
        ["git", "-C", repo] + list(args),
        capture_output=True, text=True, check=True,
    ).stdout.strip()


class IntegrationGitRefTests(unittest.TestCase):
    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="aetp-gitref-")
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        subprocess.run(["git", "-C", self.repo, "config", "user.name", "t"], check=True)
        subprocess.run(["git", "-C", self.repo, "config", "user.email", "t@t"], check=True)
        with open(os.path.join(self.repo, "f.txt"), "w") as f:
            f.write("v1\n")
        _git(self.repo, "add", "f.txt")
        _git(self.repo, "commit", "-q", "-m", "first")
        self.tip = _git(self.repo, "rev-parse", "main")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.repo, ignore_errors=True)

    def test_resolve_ref_returns_real_tip(self):
        """resolve_ref reads the actual 40-hex tip via git rev-parse."""
        self.assertEqual(resolve_ref(self.repo, "main"), self.tip)
        self.assertRegex(self.tip, r"^[0-9a-f]{40}$")

    def test_resolve_ref_rejects_unknown_ref(self):
        """Unknown ref raises a policy violation, not a silent empty string."""
        with self.assertRaises(PolicyViolation) as ctx:
            resolve_ref(self.repo, "does-not-exist")
        self.assertEqual(ctx.exception.code, "REF_NOT_FOUND")

    def test_validate_merge_matches_current_tip_accepted(self):
        """A merge whose expected target commit equals the real tip passes."""
        task = {"id": "t", "status": "ready_for_integration"}
        payload = {"expected_target_commit": self.tip, "target_ref": "main"}
        # Should not raise.
        validate_merge_against_repo(task, payload, self.repo)

    def test_validate_merge_baseline_advanced_rejected(self):
        """A merge whose expected target commit is behind the real tip is rejected."""
        task = {"id": "t", "status": "ready_for_integration"}
        stale = "0" * 40
        payload = {"expected_target_commit": stale, "target_ref": "main"}
        with self.assertRaises(PolicyViolation) as ctx:
            validate_merge_against_repo(task, payload, self.repo)
        self.assertEqual(ctx.exception.code, "BASELINE_ADVANCED")


if __name__ == "__main__":
    unittest.main()