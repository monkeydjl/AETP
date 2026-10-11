"""M1 candidate operations using the existing atomic Command write boundary."""

from __future__ import annotations

from dataclasses import replace

from aetp.core.commands import CommandHandler, CommandResult
from aetp.core.projection import Projection
from aetp.domain.models import Command, Event, ModelValidationError
from aetp.storage.sqlite_store import SQLiteStore
from aetp.collaboration.contracts import COMMAND_AGGREGATES
from aetp.collaboration.messages import MessageBus, MessageError, participant
from aetp.collaboration.policy import (
    POLICY_VERSION, PolicyViolation, canonical_json, digest_text, digest_value, strings, text, validate_payload,
)
from aetp.collaboration.records import Artifact, Review, Verification


class CollaborationService(CommandHandler):
    """Trusted in-process entry, not a Runtime/Workspace enforcement adapter.

    The inherited handle method owns actor authentication, idempotency lookup,
    the SQLite writer transaction, Event append and result persistence.
    Candidate operations never obtain another Agent's Task or run tools.
    """

    def __init__(self, store: SQLiteStore, messages: MessageBus | None = None):
        super().__init__(store)
        if messages is not None and (not isinstance(messages, MessageBus) or messages.store is not store):
            raise ValueError("messages must use the same trusted store")
        self.messages = messages or MessageBus(store)

    @staticmethod
    def _aggregate_address(command: Command) -> tuple[str, str]:
        if command.type in COMMAND_AGGREGATES:
            return COMMAND_AGGREGATES[command.type], command.target_id or ""
        return CommandHandler._aggregate_address(command)

    def _evaluate(self, command: Command, authenticated_actor_id: str):
        if command.type not in COMMAND_AGGREGATES and command.type not in {
            "task.create", "task.claim", "task.release",
        }:
            return super()._evaluate(command, authenticated_actor_id)
        state = Projection.rebuild(self.store.read_events(command.project_id))
        try:
            project = state.get(f"project:{command.project_id}")
            if project is None:
                raise PolicyViolation("INVALID_TARGET")
            if not participant(state, authenticated_actor_id):
                raise PolicyViolation("PERMISSION_DENIED")
            if project.get("status") == "paused":
                raise PolicyViolation("PROJECT_PAUSED")
            if project.get("status") not in {"planning", "active"}:
                raise PolicyViolation("PROJECT_INACTIVE")
            if command.target_id is None:
                raise PolicyViolation("INVALID_TARGET")
            if command.type == "task.create":
                return self._create_task(command, authenticated_actor_id)
            if command.type in {"task.claim", "task.release"}:
                validate_payload(command.payload, set())
                self._task(state, command.target_id)
                return super()._evaluate(command, authenticated_actor_id)
            if command.type == "verification.submit":
                raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
            dispatch = {
                "artifact.submit": self._artifact,
                "review.request": self._request_review,
                "review.submit": self._submit_review,
                "verification.run": self._verify,
                "task.verify": self._quality_gate,
                "task.complete": self._quality_gate,
            }
            return dispatch[command.type](command, state)
        except (PolicyViolation, MessageError) as exc:
            return self._rejected(command, exc.code), []
        except ModelValidationError:
            return self._rejected(command, "INVALID_PAYLOAD"), []

    def _create_task(self, command: Command, actor: str):
        validate_payload(command.payload, {"title", "acceptance_criteria"})
        text(command.payload.get("title"), limit=512)
        criteria = strings(command.payload.get("acceptance_criteria"), required=True)
        result, events = super()._evaluate(command, actor)
        if result.status == "accepted":
            events[-1] = replace(events[-1], payload={**events[-1].payload,
                "policy_version": POLICY_VERSION, "acceptance_criteria": criteria,
                "criteria_digest": digest_value(criteria)})
        return result, events

    @staticmethod
    def _new(command: Command, state: dict, aggregate: str) -> None:
        if f"{aggregate}:{command.target_id}" in state or command.expected_revision not in (None, 0):
            raise PolicyViolation("REVISION_CONFLICT")

    @staticmethod
    def _task(state: dict, identifier: str) -> dict:
        task = state.get(f"task:{identifier}")
        if task is None:
            raise PolicyViolation("INVALID_TARGET")
        if task.get("policy_version") != POLICY_VERSION or not task.get("acceptance_criteria"):
            raise PolicyViolation("POLICY_UNAVAILABLE")
        if task.get("status") in {"completed", "cancelled", "failed"}:
            raise PolicyViolation("TASK_NOT_ASSIGNABLE")
        return task

    def _artifact(self, command: Command, state: dict):
        validate_payload(command.payload, {"task_id", "type", "content", "derived_from", "supersedes",
                                           "data_classification", "message_ids"})
        self._new(command, state, "artifact")
        task_id = text(command.payload.get("task_id"), identifier=True)
        task = self._task(state, task_id)
        if command.payload.get("type") != "document":
            raise PolicyViolation("POLICY_DENIED")
        classification = command.payload.get("data_classification", "internal")
        if not isinstance(classification, str) or classification not in {"public", "internal"}:
            raise PolicyViolation("POLICY_DENIED")
        content = text(command.payload.get("content"))
        parents = strings(command.payload.get("derived_from", []))
        supersedes = command.payload.get("supersedes")
        if supersedes is not None:
            text(supersedes, identifier=True)
        for identifier in {*parents, *([supersedes] if supersedes else [])}:
            parent = state.get(f"artifact:{identifier}")
            if parent is None or parent["task_id"] != task_id or parent["type"] != "document":
                raise PolicyViolation("INVALID_REFERENCE")
        message_ids = strings(command.payload.get("message_ids", []))
        snapshots = self.messages.snapshots(command.project_id, tuple(message_ids),
                                             authenticated_actor_id=command.actor_id)
        source = {"kind": "inline_candidate", "command_id": command.id, "messages": snapshots,
                  # The sender is authenticated, but no Runtime currently
                  # proves where the submitted body obtained its inputs.
                  "untrusted_input": True, "external_input_exposure": "unknown",
                  "input_origin": "authenticated_agent_claim",
                  "execution_authority": "candidate_only"}
        artifact = Artifact(command.target_id, command.project_id, task_id, command.actor_id,
                            "document", content, digest_text(content), task["revision"],
                            tuple(task["acceptance_criteria"]), task["criteria_digest"],
                            POLICY_VERSION, source, tuple(parents), supersedes, classification)
        return self._batch(command, state, [("artifact.created", "artifact", artifact.id, 0, artifact.to_dict())])

    def _target(self, command: Command, state: dict) -> dict:
        identifier = text(command.payload.get("artifact_id"), identifier=True)
        artifact = state.get(f"artifact:{identifier}")
        if artifact is None or artifact["type"] != "document":
            raise PolicyViolation("INVALID_TARGET")
        task = self._task(state, artifact["task_id"])
        if command.payload.get("artifact_digest") != artifact["content_digest"] or any(
            task.get(key) != artifact.get(source) for key, source in (
                ("revision", "task_revision"), ("criteria_digest", "criteria_digest"),
                ("policy_version", "policy_version"),
            )
        ):
            raise PolicyViolation("EVIDENCE_STALE")
        return artifact

    def _request_review(self, command: Command, state: dict):
        validate_payload(command.payload, {"artifact_id", "artifact_digest", "reviewer_id"})
        self._new(command, state, "review")
        artifact = self._target(command, state)
        reviewer = text(command.payload.get("reviewer_id"), identifier=True)
        if not participant(state, reviewer):
            raise PolicyViolation("PERMISSION_DENIED")
        if reviewer == artifact["created_by"]:
            raise PolicyViolation("SELF_REVIEW")
        review = Review(command.target_id, command.project_id, artifact["task_id"], artifact["id"],
                        artifact["content_digest"], artifact["task_revision"], artifact["criteria_digest"],
                        POLICY_VERSION, command.actor_id, reviewer)
        return self._batch(command, state, [("review.requested", "review", review.id, 0, review.to_dict())])

    def _submit_review(self, command: Command, state: dict):
        validate_payload(command.payload, {"status", "feedback", "artifact_digest"})
        review = state.get(f"review:{command.target_id}")
        if review is None:
            raise PolicyViolation("INVALID_TARGET")
        if review["reviewer_id"] != command.actor_id:
            raise PolicyViolation("PERMISSION_DENIED")
        if command.expected_revision != review["revision"]:
            raise PolicyViolation("REVISION_CONFLICT")
        if review["status"] != "pending":
            raise PolicyViolation("REVIEW_FINAL")
        target_command = replace(command, payload={"artifact_id": review["artifact_id"],
                                                    "artifact_digest": command.payload.get("artifact_digest")})
        self._target(target_command, state)
        status = command.payload.get("status")
        if not isinstance(status, str) or status not in {"approved", "changes_requested", "rejected"}:
            raise PolicyViolation("INVALID_PAYLOAD")
        feedback = text(command.payload.get("feedback"))
        event_type = "review.approved" if status == "approved" else "review.rejected"
        return self._batch(command, state, [(event_type, "review", review["id"], review["revision"] + 1,
                                           {"status": status, "feedback": feedback, "reviewer_id": command.actor_id})])

    def _batch(self, command: Command, state: dict, effects: list[tuple]):
        aggregate_type, aggregate_id = self._aggregate_address(command)
        current = state.get(f"{aggregate_type}:{aggregate_id}")
        revision = current["revision"] if current else 0
        sequence = self.store.next_sequence(command.project_id)
        events = [Event(id=f"{command.id}:received", project_id=command.project_id, sequence=sequence,
                        type="command.received", aggregate_type=aggregate_type, aggregate_id=aggregate_id,
                        aggregate_revision=revision, causation_id=command.id, correlation_id=command.correlation_id,
                        payload={"command_type": command.type, "request_digest": command.digest()})]
        for index, (kind, entity, identifier, next_revision, payload) in enumerate(effects, 1):
            events.append(Event(id=f"{command.id}:effect:{index}", project_id=command.project_id,
                                sequence=sequence + index, type=kind, aggregate_type=entity,
                                aggregate_id=identifier, aggregate_revision=next_revision,
                                causation_id=command.id, correlation_id=command.correlation_id, payload=payload))
        result = CommandResult(status="accepted", command_id=command.id,
                               event_ids=tuple(event.id for event in events),
                               aggregate_revision=effects[-1][3], error_code=None)
        return result, events

    def _verify(self, command: Command, state: dict):
        validate_payload(command.payload, {"artifact_id", "artifact_digest"})
        self._new(command, state, "verification")
        artifact = self._target(command, state)
        evidence_id = f"{command.target_id}:evidence"
        if f"artifact:{evidence_id}" in state:
            raise PolicyViolation("REVISION_CONFLICT")
        # Only this pure, fixed checker runs inside the transaction. A real
        # external Runner would require a separate authorized Action lifecycle.
        from aetp.collaboration import checks
        report = checks.run_precheck(artifact)
        content = canonical_json(report)
        source = {"kind": "trusted_precheck", "command_id": command.id, "artifact_id": artifact["id"],
                  "untrusted_input": artifact["source"].get("untrusted_input", True),
                  "execution_authority": "unavailable"}
        evidence = Artifact(evidence_id, command.project_id, artifact["task_id"], "system:document-precheck",
                            "report", content, digest_text(content), artifact["task_revision"],
                            tuple(artifact["criteria"]), artifact["criteria_digest"], POLICY_VERSION,
                            source, (artifact["id"],), data_classification=artifact["data_classification"])
        inputs = {key: report[key] for key in (
            "artifact_digest", "test_suite_digest", "environment_digest", "command", "criteria_ref")}
        verification = Verification(command.target_id, command.project_id, artifact["task_id"],
                                    artifact["id"], artifact["content_digest"], artifact["task_revision"],
                                    artifact["criteria_digest"], POLICY_VERSION, command.actor_id,
                                    evidence.id, evidence.content_digest, inputs,
                                    {"type": "runtime_check", "name": "literal_text_contains_all"},
                                    {"kind": "internal_precheck", "runner_id": "aetp.document.precheck/v1",
                                     "authorization": "unavailable", "action_id": None, "binding_id": None,
                                     "request_command_id": command.id})
        return self._batch(command, state, [
            ("artifact.created", "artifact", evidence.id, 0, evidence.to_dict()),
            ("verification.completed", "verification", verification.id, 0, verification.to_dict()),
        ])

    def _quality_gate(self, command: Command, state: dict):
        validate_payload(command.payload, {"artifact_id", "review_id", "verification_id"})
        task = self._task(state, command.target_id)
        if command.expected_revision != task["revision"]:
            raise PolicyViolation("REVISION_CONFLICT")
        for field in ("artifact_id", "review_id", "verification_id"):
            if field in command.payload:
                text(command.payload[field], identifier=True)
        artifact = state.get(f'artifact:{command.payload.get("artifact_id")}')
        review = state.get(f'review:{command.payload.get("review_id")}')
        verification = state.get(f'verification:{command.payload.get("verification_id")}')
        if not artifact or artifact["task_id"] != task["id"] or not review or not verification:
            raise PolicyViolation("QUALITY_GATE_NOT_MET")
        if (review["artifact_id"] != artifact["id"] or review["status"] != "approved" or
            verification["artifact_id"] != artifact["id"] or verification["result"] != "PASSED" or
            artifact["task_revision"] != task["revision"]):
            raise PolicyViolation("QUALITY_GATE_NOT_MET")
        # This legacy gate has no formal submission round or final-use proof.
        # AcceptanceService supplies the fixed Runner; TaskQualityService owns
        # explicit quality transitions and Task-scoped integration exemptions.
        # Old Artifact/Review/Verification records cannot open this entry.
        raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
