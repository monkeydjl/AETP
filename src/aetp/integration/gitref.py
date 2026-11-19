"""True local git ref resolution used by the Integration Gate.

Specification source: Docs/AETP-设计方案.md §10.6. The merge baseline check
must re-read the target branch tip at the real update site (§10.6) instead of
trusting two caller-supplied commit strings. This module only ever reads refs;
it never mutates the repository or resolves anything outside ``repo_dir``.
"""

from __future__ import annotations

import re
import subprocess

from aetp.collaboration.policy import PolicyViolation

_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_REF = re.compile(r"^(?:refs/heads/)?[A-Za-z0-9_][A-Za-z0-9_.\-/]*$")


def resolve_ref(repo_dir: str, ref: str) -> str:
    """Return the current 40-hex tip of *ref*, read from *repo_dir*.

    Raises PolicyViolation("REF_NOT_FOUND") for unknown/ambiguous refs and
    PolicyViolation("INVALID_PAYLOAD") for ref shapes that ``git`` could
    misinterpret. Per spec it is strictly a read: no refs are updated here.
    """
    if not isinstance(ref, str) or _REF.fullmatch(ref) is None:
        raise PolicyViolation("INVALID_PAYLOAD")
    try:
        proc = subprocess.run(
            ["git", "-C", repo_dir, "rev-parse", "--verify", f"{ref}^{{commit}}"],
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.SubprocessError):
        raise PolicyViolation("REF_NOT_FOUND")
    tip = proc.stdout.strip()
    if proc.returncode != 0 or _HEX40.fullmatch(tip) is None:
        raise PolicyViolation("REF_NOT_FOUND")
    return tip
