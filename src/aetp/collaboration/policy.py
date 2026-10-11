"""A fixed document-candidate policy, not a configurable authority engine."""

from __future__ import annotations

import hashlib
import json
from typing import Any


POLICY_VERSION = "m1-document-candidate-v1"
MAX_CONTENT_BYTES = 65536
_COMMON = frozenset({"policy_version", "risk_level", "approval_required"})


class PolicyViolation(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def digest_text(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest_value(value: Any) -> str:
    return digest_text(canonical_json(value))


def text(value: Any, *, identifier: bool = False, limit: int = MAX_CONTENT_BYTES) -> str:
    if not isinstance(value, str) or not value.strip():
        raise PolicyViolation("INVALID_PAYLOAD")
    if identifier and value != value.strip():
        raise PolicyViolation("INVALID_PAYLOAD")
    try:
        if len(value.encode("utf-8")) > limit:
            raise PolicyViolation("INVALID_PAYLOAD")
    except UnicodeError as exc:
        raise PolicyViolation("INVALID_PAYLOAD") from exc
    return value


def strings(value: Any, *, required: bool = False, max_items: int = 32) -> list[str]:
    if not isinstance(value, (list, tuple)) or (required and not value) or len(value) > max_items:
        raise PolicyViolation("INVALID_PAYLOAD")
    result = [text(item, identifier=True, limit=512) for item in value]
    if len(set(result)) != len(result):
        raise PolicyViolation("INVALID_PAYLOAD")
    return result


def validate_payload(payload: dict, allowed: set[str]) -> None:
    approval = payload.get("approval_required", False)
    if not isinstance(approval, bool):
        raise PolicyViolation("INVALID_PAYLOAD")
    risk = payload.get("risk_level", "low")
    if not isinstance(risk, str) or risk not in {"low", "medium", "high", "critical"}:
        raise PolicyViolation("INVALID_PAYLOAD")
    if approval or risk != "low":
        raise PolicyViolation("APPROVAL_REQUIRED")
    if payload.get("policy_version", POLICY_VERSION) != POLICY_VERSION:
        raise PolicyViolation("POLICY_UNAVAILABLE")
    if payload.keys() - allowed - _COMMON:
        raise PolicyViolation("INVALID_PAYLOAD")
