"""Local GitWorktreeProvider: independent worktrees + real merge (no silent rebase).

Specification source: Docs/AETP-设计方案.md §13.9 (Workspace Provider control
surface) + §10.6 (merge must re-check the target tip and return conflicts, never
silently rebase). Local-only: no push, no remote.
"""

import os
import subprocess
import tempfile
import unittest

from aetp.collaboration.policy import PolicyViolation
from aetp.workspace.git_provider import GitWorktreeProvider


def _git(dir_, *args):
    return subprocess.run(
        ["git", "-C", dir_] + list(args),
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def _git_ok(dir_, *args):
    """Run git; return (returncode, stdout, stderr) without raising."""
    proc = subprocess.run(
        ["git", "-C", dir_] + list(args),
        capture_output=True, text=True,
    )
    return proc.returncode, proc.stdout.strip(), proc.stderr.strip()


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


class GitWorktreeProviderTests(unittest.TestCase):
    def _repo(self):
        """A fresh non-bare repo with two divergent branches main and feature."""
        repo = tempfile.mkdtemp(prefix="aetp-gitprov-")
        subprocess.run(["git", "init", "-q", "-b", "main", repo], check=True)
        subprocess.run(["git", "-C", repo, "config", "user.name", "t"], check=True)
        subprocess.run(["git", "-C", repo, "config", "user.email", "t@t"], check=True)
        _write(os.path.join(repo, "base.txt"), "base\n")
        _git(repo, "add", "base.txt")
        _git(repo, "commit", "-q", "-m", "base")
        # feature branch diverges from main
        _git(repo, "checkout", "-q", "-b", "feature")
        _write(os.path.join(repo, "feat.txt"), "feat\n")
        _git(repo, "add", "feat.txt")
        _git(repo, "commit", "-q", "-m", "feature")
        # advance main independently (so target tip is ahead of old baseline)
        _git(repo, "checkout", "-q", "main")
        _write(os.path.join(repo, "main.txt"), "main\n")
        _git(repo, "add", "main.txt")
        _git(repo, "commit", "-q", "-m", "main advance")
        self.base_commit = _git(repo, "rev-parse", "HEAD~1")
        return repo

    def tearDown(self):
        import shutil
        for attr in ("repo", "wt"):
            if hasattr(self, attr):
                shutil.rmtree(getattr(self, attr), ignore_errors=True)

    def test_provider_module_loads(self):
        self.assertTrue(callable(GitWorktreeProvider))

    def test_create_worktree_is_independent_of_main(self):
        """A worktree edit must not appear in the main working directory."""
        repo = self._repo()
        self.repo = repo
        provider = GitWorktreeProvider(repo)
        wt_path = os.path.join(tempfile.mkdtemp(prefix="aetp-wt-"), "wt")
        provider.create_worktree("ws-1", wt_path, "main")
        self.wt = wt_path
        _write(os.path.join(wt_path, "only_in_worktree.txt"), "x\n")
        # main working tree must not see it
        self.assertFalse(os.path.exists(os.path.join(repo, "only_in_worktree.txt")))

    def test_merge_rejected_on_stale_baseline(self):
        """Merge with expected commit behind real target tip -> BASELINE_ADVANCED."""
        repo = self._repo()
        self.repo = repo
        provider = GitWorktreeProvider(repo)
        stale = self.base_commit  # behind current main tip
        with self.assertRaises(PolicyViolation) as ctx:
            provider.merge("feature", "main", stale)
        self.assertEqual(ctx.exception.code, "BASELINE_ADVANCED")

    def test_merge_conflict_returns_conflict_not_silent_rebase(self):
        """Conflicting merge returns conflict paths and leaves target intact."""
        repo = self._repo()
        self.repo = repo
        provider = GitWorktreeProvider(repo)
        # create a second feature that edits base.txt the same place as a main change
        _git(repo, "checkout", "-q", "-b", "conflict-branch", "main")
        _write(os.path.join(repo, "base.txt"), "conflict side\n")
        _git(repo, "add", "base.txt")
        _git(repo, "commit", "-q", "-m", "conflict side")
        # advance main to edit base.txt too
        _git(repo, "checkout", "-q", "main")
        _write(os.path.join(repo, "base.txt"), "main side\n")
        _git(repo, "add", "base.txt")
        _git(repo, "commit", "-q", "-m", "main side")
        target_tip = _git(repo, "rev-parse", "main")
        result = provider.merge("conflict-branch", "main", target_tip)
        self.assertEqual(result["status"], "conflict")
        self.assertIn("base.txt", result.get("conflict_paths", []))
        # target branch tip unchanged (no silent rebase/merge commit)
        self.assertEqual(_git(repo, "rev-parse", "main"), target_tip)

    def test_clean_merge_produces_merge_commit(self):
        """A clean merge writes a real merge commit on the target branch."""
        repo = self._repo()
        self.repo = repo
        provider = GitWorktreeProvider(repo)
        target_tip = _git(repo, "rev-parse", "main")
        result = provider.merge("feature", "main", target_tip)
        self.assertEqual(result["status"], "merged")
        self.assertRegex(result["result_commit"], r"^[0-9a-f]{40}$")
        # feature content is now in main working tree
        self.assertTrue(os.path.exists(os.path.join(repo, "feat.txt")))


if __name__ == "__main__":
    unittest.main()
