"""A real, effect-free text precheck, not an authorized Runtime tool runner.

The module hashes its own implementation for evidence. Replay never imports
or calls this function to reproduce an action; it consumes recorded output.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys

from aetp.collaboration.policy import digest_value


_SUITE_DIGEST = "sha256:" + hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
_ENVIRONMENT = {"python": sys.version, "implementation": sys.implementation.name,
                "platform": sys.platform, "scope": "in_process_text_precheck"}


def run_precheck(artifact: dict) -> dict:
    """Observe literal criteria matches; never execute the submitted content."""
    checks = [{"criterion": criterion, "matched": criterion in artifact["content"]}
              for criterion in artifact["criteria"]]
    return {
        "schema_version": "0.1", "method": "literal_text_contains_all",
        "command": "aetp.document.contains_all/v1", "artifact_id": artifact["id"],
        "artifact_digest": artifact["content_digest"],
        "criteria_ref": {"task_id": artifact["task_id"], "revision": artifact["task_revision"],
                         "content_digest": artifact["criteria_digest"]},
        "test_suite_digest": _SUITE_DIGEST, "environment": dict(_ENVIRONMENT),
        "environment_digest": digest_value(_ENVIRONMENT), "checks": checks,
        "observed_result": "PASSED" if all(check["matched"] for check in checks) else "FAILED",
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "limitation": "Internal precheck only; Runner action authorization is unavailable.",
    }
