"""Local Git Worktree Provider: independent working copies + real merge.

Specification source: Docs/AETP-设计方案.md §§13.9, 10.6, 17.2.

This is a LOCAL-ONLY provider. It never pushes, never talks to a remote, and
never silently rebases over a peer's changes. Two hard requirements are
honoured directly:

1. ``create_worktree`` makes an independent working copy (a real git worktree),
   so one agent's uncommitted edits never appear in another agent's copy.
2. ``merge`` re-checks the target branch tip at the actual protected-ref update
   site and returns a conflict instead of auto-resolving it.
"""

from __future__ import annotations

import os
import subprocess
from typing import Dict

from aetp.collaboration.policy import PolicyViolation
from aetp.integration.gitref import resolve_ref


def _run(repo_dir: str, args, *, check=False):
    proc = subprocess.run(
        ["git", "-C", repo_dir] + args,
        capture_output=True,
        text=True,
    )
    if check and proc.returncode != 0:
        raise PolicyViolation("GIT_OPERATION_FAILED", proc.stderr.strip())
    return proc


class GitWorktreeProvider:
    """Minimal local worktree provider with real merge and baseline re-check."""

    def __init__(self, repo_dir: str):
        self.repo_dir = os.path.abspath(repo_dir)

    def create_worktree(self, workspace_id: str, path: str, base_ref: str) -> Dict:
        """Create an independent working copy at *path* checked out to *base_ref*."""
        if os.path.exists(path):
            raise PolicyViolation("WORKSPACE_EXISTS")
        proc = _run(self.repo_dir, ["worktree", "add", "--detach", os.path.abspath(path), base_ref])
        if proc.returncode != 0:
            raise PolicyViolation("WORKSPACE_CREATE_FAILED", proc.stderr.strip())
        head = _run(os.path.abspath(path), ["rev-parse", "HEAD"], check=True).stdout.strip()
        return {
            "workspace_id": workspace_id,
            "path": os.path.abspath(path),
            "base_ref": base_ref,
            "head": head,
            "status": "ready",
        }

    def merge(self, source_ref: str, target_ref: str, expected_target_commit: str) -> Dict:
        """Merge ``source_ref`` into ``target_ref``, re-checking the target tip.

        Returns ``{"status": "merged", "result_commit": ...}`` on a clean merge,
        or ``{"status": "conflict", "conflict_paths": [...]}`` on conflict. A
        stale ``expected_target_commit`` raises ``BASELINE_ADVANCED`` without
        touching the repository.
        """
        actual_tip = resolve_ref(self.repo_dir, target_ref)
        if actual_tip != expected_target_commit:
            raise PolicyViolation("BASELINE_ADVANCED")

        # Checkout target so merge operates at the protected-ref update site.
        _run(self.repo_dir, ["checkout", "-q", target_ref], check=True)

        merge = _run(self.repo_dir, ["merge", "--no-ff", "--no-commit", source_ref])
        if merge.returncode != 0:
            # Conflict: capture unmerged paths BEFORE aborting, then abort,
            # never silently rebase.
            conflicts = self._conflict_paths()
            _run(self.repo_dir, ["merge", "--abort"])
            return {"status": "conflict", "conflict_paths": conflicts}

        commit = _run(
            self.repo_dir,
            ["commit", "--no-edit", "--no-gpg-sign"],
        )
        if commit.returncode != 0:
            _run(self.repo_dir, ["merge", "--abort"])
            raise PolicyViolation("MERGE_COMMIT_FAILED", commit.stderr.strip())

        result_commit = _run(self.repo_dir, ["rev-parse", "HEAD"], check=True).stdout.strip()
        return {"status": "merged", "result_commit": result_commit}

    def _conflict_paths(self):
        proc = _run(self.repo_dir, ["diff", "--name-only", "--diff-filter=U"])
        return [line for line in proc.stdout.splitlines() if line.strip()]