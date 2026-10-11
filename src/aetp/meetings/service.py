"""Bounded local collaboration through the existing atomic Command boundary."""

import copy
import time

from aetp.collaboration.policy import PolicyViolation, digest_value, text
from aetp.collaboration.service import CollaborationService
from aetp.core.projection import Projection
from aetp.domain.models import Command, ModelValidationError
from aetp.meetings.contracts import COMMAND_AGGREGATES
from aetp.meetings.metering import MeteringAuthority
from aetp.meetings.policy import evidence_refs, governance_time, natural, termination
from aetp.meetings.process import ProcessLog
from aetp.meetings.records import Contribution, create_conversation, event_type, require_member, step_conversation


class MeetingService(CollaborationService):
    """Host API. Agents receive data, never Python store or meter capabilities."""

    def __init__(self, store, *, meter=None, clock=None):
        super().__init__(store)
        if meter is not None and not isinstance(meter, MeteringAuthority):
            raise TypeError("a trusted MeteringAuthority is required")
        self.meter = meter
        self.clock = clock or (lambda: time.time_ns() // 1_000_000)
        self.process = ProcessLog(store)

    def _now(self, events, state, metadata=None):
        at = natural(self.clock())
        latest = max((record.get("observed_at_ms", 0) for record in state.values()), default=0)
        if at < max(latest, (metadata or {}).get("last_observed_at_ms", 0)):
            raise PolicyViolation("CLOCK_REGRESSION")
        return at, governance_time(events, at)

    def _record_effect(self, command, state, kind, record):
        return self._batch(command, state, [(kind, COMMAND_AGGREGATES[command.type], command.target_id,
            record["revision"], {"record": record, "command_type": command.type, "command_payload": command.payload})])

    def _evaluate(self, command, authenticated_actor_id):
        if command.type not in COMMAND_AGGREGATES:
            return super()._evaluate(command, authenticated_actor_id)
        events = self.store.read_events(command.project_id)
        state = Projection.rebuild(events)
        try:
            require_member(state, command.project_id, authenticated_actor_id)
            if command.target_id is None:
                raise PolicyViolation("INVALID_TARGET")
            if command.type in {"decision.approve", "decision.activate"}:
                raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
            if command.type == "decision.propose":
                from aetp.decisions.service import propose
                return propose(self, command, state)
            kind = COMMAND_AGGREGATES[command.type]
            if command.type in {"discussion.open", "meeting.create"}:
                at, elapsed = self._now(events, state)
                record = create_conversation(command, state, self.meter.source_id if self.meter else None, at, elapsed)
                # Creation marker and authority facts share handle's transaction.
                self.process.create(record)
            else:
                previous = self._conversation(state, kind, command.target_id, authenticated_actor_id)
                # Revisions take precedence over phase/accounting checks.
                if command.expected_revision != previous["revision"]:
                    raise PolicyViolation("REVISION_CONFLICT")
                _, meta = self.process.read(previous)
                at, elapsed = self._now(events, state, meta)
                stats = self.process.snapshot(previous)
                record = step_conversation(command, previous, stats, state, at, elapsed)
            return self._record_effect(command, state, event_type(command, record), record)
        except PolicyViolation as exc:
            return self._rejected(command, exc.code), []
        except (ModelValidationError, TypeError, KeyError, ValueError):
            return self._rejected(command, "INVALID_PAYLOAD"), []

    @staticmethod
    def _conversation(state, kind, identifier, actor):
        if kind not in {"discussion", "meeting"}:
            raise PolicyViolation("INVALID_TARGET")
        record = state.get(f"{kind}:{identifier}")
        if record is None:
            raise PolicyViolation("INVALID_TARGET")
        if actor not in record["participants"]:
            raise PolicyViolation("PERMISSION_DENIED")
        return record

    def _context(self, project_id, kind, identifier, actor):
        actor = self._authenticated_actor(actor)
        events = self.store.read_events(project_id)
        state = Projection.rebuild(events)
        require_member(state, project_id, actor)
        return events, state, self._conversation(state, kind, identifier, actor)

    def transcript(self, project_id, kind, identifier, *, authenticated_actor_id):
        with self.store.transaction():
            _, _, record = self._context(project_id, kind, identifier, authenticated_actor_id)
            rows, _ = self.process.read(record)
            if record["status"] == "individual_analysis":
                rows = [row for row in rows if row["author_id"] == authenticated_actor_id]
            return copy.deepcopy(rows)

    def usage(self, project_id, kind, identifier, *, authenticated_actor_id):
        with self.store.transaction():
            _, _, record = self._context(project_id, kind, identifier, authenticated_actor_id)
            _, meta = self.process.read(record)
            # No context, positions, authors, references or receipt subjects leak
            # through this accounting view during the independent round.
            return {key: meta[key] for key in ("messages", "tokens", "compacted")}

    def compact(self, project_id, kind, identifier, *, authenticated_actor_id):
        with self.store.transaction():
            _, state, record = self._context(project_id, kind, identifier, authenticated_actor_id)
            self._settled_source(state, record)
            return self.process.compact(record)

    @staticmethod
    def _settled_source(state, record):
        decision = state.get(f"decision:{record['decision_id']}") if record["decision_id"] else None
        source = decision.get("source") if decision else None
        if (record["status"] != "closed" or not source or decision["status"] not in {
                "proposed", "reviewing", "pending_approval", "approved", "active", "rejected"}
                or decision["project_id"] != record["project_id"] or source["kind"] != record["kind"]
                or source["id"] != record["id"] or source["checkpoint"] != record["checkpoint"]):
            raise PolicyViolation("PROCESS_NOT_SETTLED")
        return source

    def _tick(self, record, actor):
        stats = self.process.snapshot(record)
        identity = "m2-auto:" + digest_value([record["project_id"], record["kind"], record["id"],
                                            record["revision"], stats["digest"]]).split(":")[1]
        command = Command(identity, record["project_id"], actor, f"{record['kind']}.tick", record["id"],
                          {}, record["revision"], identity, record["origin_command_id"])
        result = self.handle(command, authenticated_actor_id=actor)
        if result.status != "accepted":
            raise PolicyViolation(result.error_code)

    def post(self, contribution, *, authenticated_actor_id, receipt):
        if not isinstance(contribution, Contribution):
            raise TypeError("Contribution required")
        actor = self._authenticated_actor(authenticated_actor_id)
        if actor != contribution.author_id:
            raise PolicyViolation("ACTOR_MISMATCH")
        expired = False
        with self.store.transaction():
            events, state, record = self._context(contribution.project_id, contribution.conversation_type,
                                                  contribution.conversation_id, actor)
            rows, meta = self.process.read(record)
            if meta["compacted"]:
                # Authentication, participation and durable accounting were
                # checked first. A settled retry reads its fixed confirmation;
                # it never recreates process rows or consumes a new receipt.
                rows = self._settled_source(state, record)["records"]
            old = next((row for row in rows if row["id"] == contribution.id), None)
            if old:
                if old["semantic_digest"] != contribution.digest():
                    raise PolicyViolation("MESSAGE_ID_CONFLICT")
                return copy.deepcopy(old)
            if record["status"] not in {"open", "individual_analysis", "debate"}:
                raise PolicyViolation("PROCESS_NOT_OPEN")
            if record["kind"] == "meeting" and record["status"] == "open":
                raise PolicyViolation("INVALID_PHASE")
            at, elapsed = self._now(events, state, meta)
            if elapsed >= record["deadline_ms"]:
                self._tick(record, actor)
                expired = True
            else:
                if self.meter is None or receipt is None:
                    raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
                if self.meter.source_id != record["meter_source"]:
                    raise PolicyViolation("INVALID_USAGE_RECEIPT")
                verified = self.meter.verify(contribution, receipt)
                visible = {row["id"] for row in rows if record["status"] != "individual_analysis" or row["author_id"] == actor}
                if any(ref not in visible for ref in contribution.references):
                    raise PolicyViolation("REFERENCE_NOT_VISIBLE")
                if record["status"] == "individual_analysis":
                    if contribution.category != "analysis":
                        raise PolicyViolation("INVALID_PHASE")
                    if any(row["author_id"] == actor for row in rows):
                        raise PolicyViolation("ANALYSIS_ALREADY_SUBMITTED")
                evidence_refs(contribution.evidence, state)
                if meta["tokens"] + verified["tokens"] > record["policy"]["token_budget"]:
                    raise PolicyViolation("BUDGET_EXCEEDED")
                accepted = self.process.append(record, contribution, verified, at)
                stats = self.process.snapshot(record)
                if termination(record, stats, elapsed):
                    self._tick(record, actor)
        # Do not roll back the just-committed expiration Event with the input error.
        if expired:
            raise PolicyViolation("TIME_BUDGET_EXHAUSTED")
        return copy.deepcopy(accepted)
