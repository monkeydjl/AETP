"""Reproduce the M0-04 Unicode oracle gap and verify its bounded correction.

The escaped-mutant mode substitutes only the digest API in this disposable
Python process. It never edits production files or touches a database.
A passing mutant is the old coverage gap, not a product success; a failing
mutant counts as caught only when unittest reports an assertion failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("production", "escaped-mutant"), required=True)
    args = parser.parse_args()

    from aetp.core import idempotency
    from tests.m0.test_idempotency_concurrency import CanonicalDigestTests

    if args.mode == "escaped-mutant":
        def escaped_digest(command):
            canonical = json.dumps(
                command.to_dict(), sort_keys=True, separators=(",", ":"),
                ensure_ascii=True,
            )
            return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        idempotency.canonical_digest = escaped_digest

    suite = unittest.TestSuite([
        CanonicalDigestTests(
            "test_nested_key_order_is_normalized_but_unicode_is_preserved"
        )
    ])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    paths = (
        "tests/m0/test_idempotency_concurrency.py",
        "src/aetp/core/idempotency.py",
        "src/aetp/core/commands.py",
        "src/aetp/domain/models.py",
    )
    print(json.dumps({
        "mode": args.mode,
        "tests_run": result.testsRun,
        "failures": len(result.failures),
        "errors": len(result.errors),
        "source_sha256": {
            path: hashlib.sha256((ROOT / path).read_bytes()).hexdigest()
            for path in paths
        },
        "canonical_files_modified": False,
    }, indent=2))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
