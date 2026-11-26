"""Immutable snapshots for the implemented Artifact and Review contracts."""

from __future__ import annotations

from dataclasses import dataclass

from aetp.collaboration.policy import (
    POLICY_VERSION,
    PolicyViolation,
    digest_text,
    digest_value,
    strings,
    text,
)
from aetp.domain.models import (
    ModelValidationError,
    VersionedModel,
    _json_value,
    _non_empty_string,
    _non_negative_int,
)


def _identifiers(record, names) -> None:
    for name in names:
        _non_empty_string(name, getattr(record, name))


@dataclass(frozen=True, slots=True)
class Artifact(VersionedModel):
    id: str
    project_id: str
    task_id: str
    created_by: str
    type: str
    content: str
    content_digest: str
    task_revision: int
    criteria: tuple[str, ...]
    criteria_digest: str
    policy_version: str
    source: dict
    derived_from: tuple[str, ...] = ()
    supersedes: str | None = None
    data_classification: str = "internal"
    revision: int = 0

    def __post_init__(self) -> None:
        _identifiers(self, ("id", "project_id", "task_id", "created_by"))
        _non_negative_int("task_revision", self.task_revision)
        _non_negative_int("revision", self.revision)
        if self.revision != 0 or self.policy_version != POLICY_VERSION:
            raise ModelValidationError("Artifact identity and policy are immutable")
        if self.type not in {"document", "report"} or self.data_classification not in {"public", "internal"}:
            raise ModelValidationError("unsupported candidate Artifact scope")
        try:
            text(self.content)
            object.__setattr__(self, "criteria", tuple(strings(self.criteria, required=True)))
            object.__setattr__(self, "derived_from", tuple(strings(self.derived_from)))
        except PolicyViolation as exc:
            raise ModelValidationError(str(exc)) from exc
        if self.supersedes is not None:
            _non_empty_string("supersedes", self.supersedes)
        if self.content_digest != digest_text(self.content) or self.criteria_digest != digest_value(self.criteria):
            raise ModelValidationError("Artifact content or criteria digest mismatch")
        if not isinstance(self.source, dict):
            raise ModelValidationError("Artifact source must be an object")
        object.__setattr__(self, "source", _json_value(self.source))


@dataclass(frozen=True, slots=True)
class Review(VersionedModel):
    id: str
    project_id: str
    task_id: str
    artifact_id: str
    artifact_digest: str
    task_revision: int
    criteria_digest: str
    policy_version: str
    requested_by: str
    reviewer_id: str
    status: str = "pending"
    feedback: str | None = None
    revision: int = 0

    def __post_init__(self) -> None:
        _identifiers(self, ("id", "project_id", "task_id", "artifact_id", "artifact_digest",
                            "criteria_digest", "requested_by", "reviewer_id"))
        _non_negative_int("task_revision", self.task_revision)
        _non_negative_int("revision", self.revision)
        if self.policy_version != POLICY_VERSION:
            raise ModelValidationError("unsupported Review policy")
        if self.status not in {"pending", "approved", "changes_requested", "rejected"}:
            raise ModelValidationError("invalid Review status")
        if self.status == "pending":
            if self.revision != 0 or self.feedback is not None:
                raise ModelValidationError("new Review must be pending at revision zero")
        elif self.revision != 1 or not isinstance(self.feedback, str) or not self.feedback.strip():
            raise ModelValidationError("terminal Review requires revision one and recorded feedback")


@dataclass(frozen=True, slots=True)
class Verification(VersionedModel):
    id: str
    project_id: str
    task_id: str
    artifact_id: str
    artifact_digest: str
    task_revision: int
    criteria_digest: str
    policy_version: str
    verifier_id: str
    evidence_id: str
    evidence_digest: str
    inputs: dict
    method: dict
    execution: dict
    result: str = "INCONCLUSIVE"
    reason: str = "ENFORCEMENT_UNAVAILABLE"
    revision: int = 0

    def __post_init__(self) -> None:
        _identifiers(self, ("id", "project_id", "task_id", "artifact_id", "artifact_digest",
                            "criteria_digest", "verifier_id", "evidence_id", "evidence_digest"))
        _non_negative_int("task_revision", self.task_revision)
        _non_negative_int("revision", self.revision)
        if self.revision != 0 or self.policy_version != POLICY_VERSION:
            raise ModelValidationError("Verification must preserve an immutable policy snapshot")
        if self.result != "INCONCLUSIVE" or self.reason != "ENFORCEMENT_UNAVAILABLE":
            raise ModelValidationError("M1-01 prechecks cannot certify an authorized Verification")
        for name in ("inputs", "method", "execution"):
            if not isinstance(getattr(self, name), dict):
                raise ModelValidationError(f"Verification {name} must be an object")
            object.__setattr__(self, name, _json_value(getattr(self, name)))
        if self.method != {"type": "runtime_check", "name": "literal_text_contains_all"}:
            raise ModelValidationError("unsupported Verification method")
        if self.execution.get("authorization") != "unavailable" or any(
            self.execution.get(field) is not None for field in ("action_id", "binding_id")
        ):
            raise ModelValidationError("precheck record cannot invent Runner action authorization")
