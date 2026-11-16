"""Trusted governance host. Compounds commit atomically; Replay never invokes it."""

from contextvars import ContextVar
import copy

from aetp.collaboration.policy import PolicyViolation
from aetp.core.idempotency import IdempotencyConflict
from aetp.core.projection import Projection
from aetp.domain.models import Command, ModelValidationError
from aetp.governance.contracts import COMMAND_AGGREGATES, SCHEMA, system_actor
from aetp.governance.causality import command_id, continuations, expiry_id
from aetp.governance.credential_broker import CredentialBrokerError
from aetp.governance.policy import current
from aetp.governance.projection import evaluate
from aetp.governance.snapshots import snapshot
from aetp.governance.trust import InputAuthority
from aetp.meetings.service import MeetingService
from aetp.meetings.policy import projected_time
from aetp.runtime.contracts import child_id
from aetp.runtime.policy import observed_time
from aetp.workspace.gate import ResourceGate


class GovernanceService(MeetingService):
    """Only the host receives this object, Runtime, store and input issuer.

    Agent requests are data plus a trusted connection identity. Human identity
    is rooted explicitly on first configuration and subsequently in Events.
    """

    def __init__(self, store, *, owner_id=None, execution=None, input_authority=None, meter=None, clock=None, credential_broker=None):
        super().__init__(store, meter=meter, clock=clock)
        if input_authority is not None and not isinstance(input_authority, InputAuthority):
            raise TypeError("a trusted InputAuthority is required")
        if execution is not None and execution.store is not store:
            raise ValueError("execution and governance must use the same store")
        self.owner_id = owner_id
        self.input_authority = input_authority
        # Trusted-only: the broker holds secrets; it is never supplied by an
        # Agent Command. None means fail-closed (credential.request is refused).
        self._credential_broker = credential_broker
        self._execution = None
        # Assigning through the setter pins the broker onto the consuming side,
        # so construction and late attachment follow one path.
        self.execution = execution
        self.gate = ResourceGate(store.database_path)
        self._governance_context = ContextVar(f"governance_{id(self)}", default=None)

    @property
    def execution(self):
        return self._execution

    @execution.setter
    def execution(self, value):
        """Attaching execution must also reach the consuming side.

        A host that constructs governance first and attaches execution later
        would otherwise leave the Broker mounted on this side only, and every
        revocation would be recorded and then ignored at the call boundary.
        """
        self._execution = value
        self._sync_consuming_broker(getattr(self, "_credential_broker", None))

    @property
    def credential_broker(self):
        return self._credential_broker

    @credential_broker.setter
    def credential_broker(self, broker):
        self._sync_consuming_broker(broker)
        self._credential_broker = broker

    def _sync_consuming_broker(self, broker):
        """Keep both mount points on one Broker, or refuse the wiring.

        Revocation happens here (governance) while authorisation happens at the
        call boundary (`runtime/actions.py` reads `DocumentRuntime.credential_broker`).
        Two instances would record a revocation and then ignore it, so the
        consuming side is pinned to the same object. Detaching on this side
        (None) deliberately leaves the consuming side's check in place.
        """
        if broker is None:
            return
        runtime = getattr(self.execution, "runtime", None)
        if runtime is None:
            return
        current = getattr(runtime, "credential_broker", None)
        if current is not None and current is not broker:
            raise ValueError("governance and execution must share one Credential Broker")
        runtime.credential_broker = broker

    def snapshot(self, project_id, target_type, target_id):
        return snapshot(Projection.rebuild(self.store.read_events(project_id)), target_type, target_id)

    def handle(self, command, *, authenticated_actor_id, input_receipt=None):
        if not isinstance(command, Command):
            raise TypeError("Command required")
        if command.type not in COMMAND_AGGREGATES:
            return super().handle(command, authenticated_actor_id=authenticated_actor_id)
        if self.store.in_transaction:
            raise RuntimeError("governance entry requires gate before writer transaction")
        with self.gate.hold():
            actor = self._authenticated_actor(authenticated_actor_id)
            if command.actor_id == actor:
                try:
                    prior = self._idempotency.lookup((command.project_id, actor, command.idempotency_key), command.digest())
                except IdempotencyConflict:
                    return self._rejected(command, "IDEMPOTENCY_CONFLICT")
                if prior is not None:
                    return prior
            context = {"input_receipt": input_receipt}
            if command.type == "project.resume" and command.actor_id == actor:
                from aetp.governance.controls import project_control_input
                try:
                    state = Projection.rebuild(self.store.read_events(command.project_id))
                    project = project_control_input(command, state)
                    if project.get("execution_policy_version"):
                        if self.execution is None:
                            raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
                        # Reconciliation can query external documents. It runs
                        # before the writer transaction, with the gate held.
                        self.execution.recover(command.project_id)
                except PolicyViolation as exc:
                    context["forced_error"] = exc.code
            try:
                with self.store.transaction():
                    result = self._submit(command, actor, context)
            except BaseException:
                # The COMMIT failed, so a token minted for this Command has no
                # Event behind it and nothing could ever revoke it. The failure
                # itself is the proof: cleanup does not need to ask the store.
                self._discard_minted_if_orphaned(command, context, committed=False)
                raise
            # The transaction committed, so the result now says whether a
            # credential.issued landed with it.
            self._discard_minted_if_orphaned(command, context, committed=result.status == "accepted")
            if result.status == "accepted" and command.type == "project.pause" and self.execution is not None:
                self.execution._barriers[command.project_id] = False
            return result

    def _submit(self, command, actor, context):
        # Authentication and existing result take precedence over new clocks,
        # ingress capabilities or continuation work.
        actor = self._authenticated_actor(actor)
        if command.actor_id != actor:
            return super().handle(command, authenticated_actor_id=actor)
        try:
            prior = self._idempotency.lookup((command.project_id, actor, command.idempotency_key), command.digest())
        except IdempotencyConflict:
            return self._rejected(command, "IDEMPOTENCY_CONFLICT")
        if prior is not None:
            return prior
        token = self._governance_context.set(context)
        try:
            try:
                with self.store.transaction():
                    result = super().handle(command, authenticated_actor_id=actor)
                    if result.status == "accepted":
                        self._followups(command, context)
                    return result
            except PolicyViolation as exc:
                # Normal child rejections return a result; _child converts them
                # to this exception. The savepoint removes every partial child
                # and parent result before auditing the rejected parent intent.
                if context.get("parent_command_id") is not None:
                    raise
                context["forced_error"] = exc.code
                return super().handle(command, authenticated_actor_id=actor)
        finally:
            self._governance_context.reset(token)

    def _discard_minted_if_orphaned(self, command, context, *, committed):
        """Settle every token minted for a Command that did not land.

        The caller states the outcome instead of letting cleanup probe for it:
        a failed COMMIT proves the credential.issued never landed, and a
        committed Command's result says whether one did. Reading the event
        stream here would add a failure mode of its own, and a probe failure
        during a failed COMMIT would leave a usable credential that nobody can
        revoke.

        Cleanup never raises. It runs on the way out of a failed Command, so an
        exception here would replace the real failure with a credential error
        and send the caller after the wrong problem.
        """
        if command.type != "credential.request":
            return
        minted = context.get("minted_tokens") or []
        if not minted:
            return
        for entry in minted:
            # Each entry records the Broker that minted it: a host can swap or
            # clear the mounted instance mid-Command, and cleanup must reach the
            # one actually holding the token.
            if not isinstance(entry, tuple) or len(entry) != 2:
                # Unknown shape: which Broker holds it is unknowable, so leave
                # it alone rather than guess at the owner.
                continue
            owner, body = entry
            if owner is None:
                continue
            try:
                if committed:
                    # The Event landed, so the Projection now owns this
                    # credential and the Broker must refuse to drop it later.
                    owner._confirm(body)
                else:
                    owner._discard(body)
            except Exception:
                # Best effort, and that includes a Broker that is not the one
                # this entry names: raising here would replace the real failure
                # with a credential error and send the caller after the wrong
                # problem.
                pass
        minted.clear()

    def _rejection_events(self, command, result):
        # A rejected child cannot coexist with its parent's accepted fact.
        # Propagate before appending it so the outer savepoint can roll back
        # the compound and persist a typed rejection of the original intent.
        context = self._governance_context.get() or {}
        if context.get("internal") is True and context.get("parent_command_id") is not None:
            raise PolicyViolation(result.error_code)
        return super()._rejection_events(command, result)

    def _evaluate(self, command, authenticated_actor_id):
        if command.type not in COMMAND_AGGREGATES:
            return super()._evaluate(command, authenticated_actor_id)
        context = self._governance_context.get() or {}
        if context.get("forced_error"):
            return self._rejected(command, context["forced_error"]), []
        events = self.store.read_events(command.project_id)
        state = Projection.rebuild(events)
        try:
            at = context.get("at")
            if at is None:
                at = observed_time(state, self.clock())
                context["at"] = at
            data = {"idempotency_key": command.idempotency_key}
            data.update({key: copy.deepcopy(context[key]) for key in ("internal", "parent_command_id", "trigger") if key in context})
            if command.type == "project.governance.configure":
                data.update(bootstrap_owner=self.owner_id,
                            input_authority_id=self.input_authority.source_id if self.input_authority else None)
            if command.type == "approval.request" and context.get("input_receipt") is not None:
                if self.input_authority is None:
                    raise PolicyViolation("INPUT_CONTEXT_INVALID")
                data["input_proof"] = self.input_authority.verify(command, context["input_receipt"])
            if command.type == "project.resume":
                if state[f"project:{command.project_id}"].get("execution_policy_version"):
                    if self.execution is None:
                        raise PolicyViolation("ENFORCEMENT_UNAVAILABLE")
                    data["recovery_observations"] = self.execution.recovery_status(
                        command.project_id, exclude_command_id=command.id, at=at)["observations"]
                else:
                    from aetp.core.runtime import RuntimeRecovery
                    # The writer transaction already fixes both reads to one
                    # snapshot. Only this newly persisted resume has no receipt
                    # yet; every older incomplete Command still blocks resume.
                    commands = [saved for saved in RuntimeRecovery(self.store)._read_commands(command.project_id)
                                if saved.id != command.id]
                    data["recovery_observations"] = {
                        "live_sessions": {}, "pending_commands": Projection.pending_command_ids(events, commands),
                        "workspace_provider_id": None}
            if command.type == "credential.request":
                # A token minted into a Broker the call boundary ignores would
                # be reported as granted and then answer CREDENTIAL_UNKNOWN.
                broker = self._require_reachable_broker()
                # The broker mints the token; the Agent payload can never carry
                # a token_ref, only the requested permissions + TTL.
                if "token_ref" in command.payload or "broker_token_ref" in command.payload:
                    raise PolicyViolation("INVALID_PAYLOAD")
                issued = broker.issue(
                    command.actor_id,
                    permissions=command.payload.get("permissions"),
                    issued_at=at,
                    expires_in_ms=command.payload.get("ttl_ms"),
                    # Pending until the Event commits: this token may still be
                    # discarded if the Command fails.
                    pending=True,
                )
                # Persist only the non-invertible ref; the token body stays in
                # the broker's memory and must never reach the Event Store.
                data["broker_token_ref"] = issued["token_ref"]
                # Revocation travels through a Projection record, so a token
                # minted for a Command that never commits could not be revoked
                # by anyone until it expired. _submit discards it instead.
                # The minting Broker is recorded with the token: cleanup must
                # un-mint from the instance that holds it, not from whatever is
                # mounted by the time the Command ends.
                context.setdefault("minted_tokens", []).append((broker, issued["token"]))
            kind, record = evaluate(command, state, at, data)
            payload = {"governance_schema": SCHEMA, "actor_id": command.actor_id, "command_type": command.type,
                       "command_payload": command.payload, "expected_revision": command.expected_revision,
                       "observed_at_ms": at, "context": data, "record": record,
                       "continuations": continuations(command, record, state)}
            outcome = self._batch(command, state, [(kind, COMMAND_AGGREGATES[command.type], command.target_id,
                                                    record["revision"], payload)])
            if command.type == "credential.revoke":
                # The Projection record and the Broker are two halves of one
                # fact: marking the record revoked is cosmetic unless the
                # Broker stops honouring the ref. The Command-side authority
                # check already ran inside evaluate(), so the Broker is asked
                # on behalf of the credential's owner.
                #
                # This runs after the batch is built, so a Command that turns
                # out to be rejected (a later stage raising) never leaves a
                # Broker-side revocation behind: a rejected Command must have
                # no effects at all.
                self._revoke_in_broker(record)
            return outcome
        except PolicyViolation as exc:
            return self._rejected(command, exc.code), []
        except (ModelValidationError, TypeError, KeyError, ValueError):
            return self._rejected(command, "INVALID_PAYLOAD"), []

    def _require_reachable_broker(self):
        """Return the Broker only if the call boundary would honour it.

        Assignment pins the broker onto the consuming side, but a host can swap
        that side afterwards or attach execution later. Checking here, at the
        moment the fact is recorded, keeps the guarantee independent of wiring
        order. Both directions need it: a revoke the boundary would ignore is
        cosmetic, and a token minted into an unreachable Broker is a credential
        the Command reports as granted but nobody can use.
        """
        if self.credential_broker is None:
            raise PolicyViolation("CREDENTIAL_UNAVAILABLE")
        runtime = getattr(self.execution, "runtime", None)
        if runtime is not None and getattr(runtime, "credential_broker", None) is not self.credential_broker:
            raise PolicyViolation("CREDENTIAL_UNAVAILABLE")
        return self.credential_broker

    def _revoke_in_broker(self, record):
        """Make the Broker stop honouring a credential the Projection revoked.

        Called only after ``evaluate()`` has established the Command's
        authority, so the Broker is asked on behalf of the record's owner: the
        Broker itself has no human concept and checks ownership by agent id.
        """
        broker = self._require_reachable_broker()
        token_ref = record.get("token_ref")
        owner = record.get("owner_id")
        if not isinstance(token_ref, str) or not token_ref:
            raise PolicyViolation("CREDENTIAL_UNAVAILABLE")
        if not isinstance(owner, str) or not owner:
            # A record predating ownership persistence cannot be matched to a
            # Broker identity. Refusing keeps the Projection from claiming a
            # revocation the Broker would go on honouring.
            raise PolicyViolation("CREDENTIAL_UNAVAILABLE")
        try:
            self.credential_broker.revoke_by_ref(token_ref, actor=owner)
        except PolicyViolation as exc:
            code = getattr(exc, "code", None)
            if code == "CREDENTIAL_UNKNOWN":
                # A ref the Broker no longer knows cannot be granted either, so
                # the intended effect already holds.
                return
            # The Command-side authority check already passed, so the Broker is
            # not rejecting the caller: its own idea of who owns this ref
            # disagrees with the Projection record. The two halves of one fact
            # cannot be reconciled, which is what CREDENTIAL_UNAVAILABLE means.
            # Passing the Broker's own code through (PERMISSION_DENIED) would
            # blame the caller for an internal inconsistency and send them after
            # the wrong problem. Not reachable through the protocol - issue()
            # derives both sides from one command.actor_id - but a host can mount
            # a Broker that already holds the ref for someone else.
            raise PolicyViolation("CREDENTIAL_UNAVAILABLE")

    def _child(self, parent, kind, target, payload, context, *, actor=None):
        state = Projection.rebuild(self.store.read_events(parent.project_id))
        previous = state.get(f"{COMMAND_AGGREGATES[kind]}:{target}")
        key = command_id(parent.project_id, parent.id, kind, target)
        actor = actor or system_actor(parent.project_id)
        command = Command(key, parent.project_id, actor, kind, target, payload,
                          previous["revision"] if previous else 0, key, parent.correlation_id)
        child_context = {"internal": True, "parent_command_id": parent.id, "at": context["at"]}
        result = self._submit(command, actor, child_context)
        if result.status != "accepted":
            raise PolicyViolation(result.error_code)
        return result

    def _followups(self, command, context):
        fact = next(event for event in self.store.read_events(command.project_id)
                    if event.causation_id == command.id and event.payload.get("governance_schema") == SCHEMA)
        for child in fact.payload["continuations"]:
            self._child(command, child["type"], child["target_id"], child["payload"], context, actor=child["actor_id"])

    def tick(self, project_id):
        """Trusted host scan; no background task or external notification sender."""
        if self.store.in_transaction:
            raise RuntimeError("governance tick requires gate before writer transaction")
        with self.gate.hold(), self.store.transaction():
            state = Projection.rebuild(self.store.read_events(project_id))
            current(state, project_id)
            at = observed_time(state, self.clock())
            elapsed = projected_time(state[f"project:{project_id}"], at)
            expired = []
            for key, approval in state.items():
                if not key.startswith("approval:") or approval["status"] not in {"pending", "approved"} or elapsed < approval["expires_at"]:
                    continue
                key = expiry_id(project_id, approval["id"], approval["revision"])
                command = Command(key, project_id, system_actor(project_id), "approval.expire", approval["id"], {},
                                  approval["revision"], key, approval["origin_command_id"])
                result = self._submit(command, command.actor_id, {"internal": True, "trigger": "host_tick", "at": at})
                if result.status != "accepted":
                    raise PolicyViolation(result.error_code)
                expired.append(approval["id"])
            return {"expired_approval_ids": expired}
