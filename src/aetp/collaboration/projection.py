"""Pure M1 reductions; validation never invokes a checker or an external tool."""

from __future__ import annotations

import json

from aetp.collaboration.policy import (
    POLICY_VERSION,
    PolicyViolation,
    digest_value,
    strings,
)
from aetp.collaboration.records import Artifact, Review, Verification
from aetp.domain.models import Event, ModelValidationError


def task_metadata(payload: dict) -> dict:
    try:
        criteria = strings(payload.get("acceptance_criteria"), required=True)
    except PolicyViolation as exc:
        raise ModelValidationError("invalid candidate Task criteria") from exc
    if payload.get("policy_version") != POLICY_VERSION or payload.get("criteria_digest") != digest_value(criteria):
        raise ModelValidationError("invalid candidate Task policy or criteria digest")
    return {"policy_version": POLICY_VERSION, "acceptance_criteria": criteria,
            "criteria_digest": payload["criteria_digest"]}


def _task_matches(record, state: dict) -> None:
    task = state.get(f"task:{record.task_id}")
    if task is None or any(task.get(key) != expected for key, expected in (
        ("revision", record.task_revision), ("criteria_digest", record.criteria_digest),
        ("policy_version", record.policy_version),
    )):
        raise ModelValidationError("candidate evidence does not match the Task snapshot")


def _review_target(record: Review, state: dict) -> None:
    artifact = state.get(f"artifact:{record.artifact_id}")
    if artifact is None or artifact["type"] != "document" or any(
        artifact.get(key) != expected for key, expected in (
            ("task_id", record.task_id), ("content_digest", record.artifact_digest),
            ("task_revision", record.task_revision), ("criteria_digest", record.criteria_digest),
            ("policy_version", record.policy_version),
        )
    ):
        raise ModelValidationError("Review does not match its immutable target")
    if artifact["created_by"] == record.reviewer_id:
        raise ModelValidationError("Artifact author cannot independently review it")
    _task_matches(record, state)


def reduce_record(event: Event, previous: dict | None, state: dict) -> dict:
    if event.type == "artifact.created":
        if previous is not None or event.aggregate_revision != 0:
            raise ModelValidationError("Artifact creation requires an absent immutable identity")
        record = Artifact.from_dict(event.payload)
        _task_matches(record, state)
        if record.source.get("command_id") != event.causation_id:
            raise ModelValidationError("Artifact source must identify its producing Command")
        parents = set(record.derived_from)
        if record.supersedes is not None:
            parents.add(record.supersedes)
        for identifier in parents:
            parent = state.get(f"artifact:{identifier}")
            if not parent or parent["task_id"] != record.task_id:
                raise ModelValidationError("Artifact provenance target is invalid")
        for snapshot in record.source.get("messages", []):
            if not isinstance(snapshot, dict) or snapshot.get("content_digest") != digest_value(snapshot.get("message")):
                raise ModelValidationError("pinned Message digest mismatch")
    elif event.type == "review.requested":
        if previous is not None or event.aggregate_revision != 0:
            raise ModelValidationError("Review request requires an absent identity")
        record = Review.from_dict(event.payload)
        if record.status != "pending":
            raise ModelValidationError("Review request cannot supply its own result")
        _review_target(record, state)
    elif event.type == "verification.completed":
        if previous is not None or event.aggregate_revision != 0:
            raise ModelValidationError("Verification creation requires an absent identity")
        record = Verification.from_dict(event.payload)
        _task_matches(record, state)
        artifact = state.get(f"artifact:{record.artifact_id}")
        evidence = state.get(f"artifact:{record.evidence_id}")
        if not artifact or artifact["type"] != "document" or any(
            artifact.get(key) != expected for key, expected in (
                ("content_digest", record.artifact_digest), ("task_id", record.task_id),
                ("task_revision", record.task_revision), ("criteria_digest", record.criteria_digest),
            )
        ):
            raise ModelValidationError("Verification target snapshot mismatch")
        if not evidence or evidence["type"] != "report" or evidence["content_digest"] != record.evidence_digest:
            raise ModelValidationError("Verification requires immutable report evidence")
        if (evidence["source"].get("kind"), evidence["source"].get("command_id"),
            evidence["source"].get("artifact_id"), record.execution.get("request_command_id")) != (
                "trusted_precheck", event.causation_id, record.artifact_id, event.causation_id
        ):
            raise ModelValidationError("Verification evidence has no matching trusted precheck source")
        report = json.loads(evidence["content"])
        expected_inputs = {key: report.get(key) for key in (
            "artifact_digest", "test_suite_digest", "environment_digest", "command", "criteria_ref")}
        if record.inputs != expected_inputs or report.get("artifact_id") != record.artifact_id:
            raise ModelValidationError("Verification inputs differ from recorded evidence")
        if (report.get("artifact_digest") != record.artifact_digest or
            report.get("environment_digest") != digest_value(report.get("environment")) or
            report.get("criteria_ref") != {"task_id": record.task_id, "revision": record.task_revision,
                                           "content_digest": record.criteria_digest}):
            raise ModelValidationError("Verification report inputs are inconsistent")
    elif event.type in {"review.approved", "review.rejected"}:
        if previous is None or previous["status"] != "pending" or event.aggregate_revision != 1:
            raise ModelValidationError("Review is absent or already terminal")
        if set(event.payload) != {"status", "feedback", "reviewer_id"}:
            raise ModelValidationError("Review result has unexpected fields")
        if event.payload["reviewer_id"] != previous["reviewer_id"]:
            raise ModelValidationError("Review result has a different reviewer")
        record = Review.from_dict({**previous, **event.payload, "revision": event.aggregate_revision})
        expected_type = "review.approved" if record.status == "approved" else "review.rejected"
        if record.status == "pending" or event.type != expected_type:
            raise ModelValidationError("Review Event type contradicts its result")
        _review_target(record, state)
    else:
        raise ModelValidationError("unsupported M1 record Event")
    if (record.id, record.project_id, record.revision) != (
        event.aggregate_id, event.project_id, event.aggregate_revision
    ):
        raise ModelValidationError("record identity does not match its Event")
    return json.loads(record.to_json())
