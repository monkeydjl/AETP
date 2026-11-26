"""Pure syntax validation. A valid intent is never an execution authorization."""

import re

from aetp.collaboration.policy import PolicyViolation, text
from aetp.governance.policy import fields
from aetp.integration.contracts import (
    MAX_IDENTIFIER_CHARS,
    MAX_REASON_CHARS,
    MAX_REF_CHARS,
    MAX_VERSIONS,
    OID_LENGTHS,
)
from aetp.meetings.policy import natural

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
_REF = re.compile(r"refs/heads/[A-Za-z0-9_][A-Za-z0-9_-]*(?:/[A-Za-z0-9_][A-Za-z0-9_-]*)*")
_HEX = re.compile(r"[0-9a-f]+")
_CONTENT_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")


def _bounded_match(value, pattern, limit):
    if not isinstance(value, str) or len(value) > limit or pattern.fullmatch(value) is None:
        raise PolicyViolation("INVALID_PAYLOAD")
    return value


def _oid(value, width):
    value = _bounded_match(value, _HEX, width)
    if len(value) != width or value == "0" * width:
        raise PolicyViolation("INVALID_PAYLOAD")
    return value


def validate_target(value: object) -> dict:
    """Return detached opaque intent data; never resolve refs or repositories."""
    names = {"provider_id", "repository_id", "object_format", "source", "target"}
    fields(value, names, names)
    provider = _bounded_match(value["provider_id"], _IDENTIFIER, MAX_IDENTIFIER_CHARS)
    repository = _bounded_match(value["repository_id"], _IDENTIFIER, MAX_IDENTIFIER_CHARS)
    fmt = value["object_format"]
    if not isinstance(fmt, str) or fmt not in OID_LENGTHS:
        raise PolicyViolation("INVALID_PAYLOAD")
    source, target = value["source"], value["target"]
    fields(source, {"ref", "commit"}, {"ref", "commit"})
    fields(target, {"ref", "expected_commit"}, {"ref", "expected_commit"})
    source_ref = _bounded_match(source["ref"], _REF, MAX_REF_CHARS)
    target_ref = _bounded_match(target["ref"], _REF, MAX_REF_CHARS)
    if source_ref == target_ref:
        raise PolicyViolation("INVALID_PAYLOAD")
    width = OID_LENGTHS[fmt]
    return {
        "provider_id": provider,
        "repository_id": repository,
        "object_format": fmt,
        "source": {"ref": source_ref, "commit": _oid(source["commit"], width)},
        "target": {"ref": target_ref, "expected_commit": _oid(target["expected_commit"], width)},
    }


def validate_declaration_payload(value: object) -> dict:
    """Check local shape only; current authority/history/revisions require a transaction."""
    names = {"task_id", "expected_task_revision", "version", "supersedes_version",
             "requirement", "target", "reason"}
    fields(value, names, names)
    task_id = text(value["task_id"], identifier=True, limit=512)
    task_revision = natural(value["expected_task_revision"])
    version = natural(value["version"], MAX_VERSIONS, positive=True)
    previous = value["supersedes_version"]
    if version == 1:
        if previous is not None:
            raise PolicyViolation("INVALID_PAYLOAD")
    else:
        natural(previous, MAX_VERSIONS - 1, positive=True)
        if previous != version - 1:
            raise PolicyViolation("INVALID_PAYLOAD")
    if value["requirement"] != "required":
        raise PolicyViolation("INVALID_PAYLOAD")
    # text checks valid UTF-8/nonblank without trimming. Four bytes per scalar
    # allows exactly the character limit even for supplementary characters.
    reason = text(value["reason"], limit=4 * MAX_REASON_CHARS)
    if len(reason) > MAX_REASON_CHARS:
        raise PolicyViolation("INVALID_PAYLOAD")
    return {"task_id": task_id, "expected_task_revision": task_revision,
            "version": version, "supersedes_version": previous, "requirement": "required",
            "target": validate_target(value["target"]), "reason": reason}


def validate_merge_payload(value: object) -> dict:
    """Validate a declaration reference only; this does not enable git.merge."""
    names = {"declaration_version", "declaration_digest"}
    fields(value, names, names)
    return {
        "declaration_version": natural(value["declaration_version"], MAX_VERSIONS, positive=True),
        "declaration_digest": _bounded_match(value["declaration_digest"], _CONTENT_DIGEST, 71),
    }
