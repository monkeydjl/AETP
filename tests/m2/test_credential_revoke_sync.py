"""A revoked credential must stop working at the Broker, not just in the Projection.

Spec 14.3 / INV-012. The Projection record and the Broker are two halves of one
fact: `credential.revoke` marks the record revoked, and the Broker must stop
honouring the ref. If only the record changes, a consuming Action still passes
`assert_permission_by_ref` and the revocation is cosmetic.
"""

import unittest
from unittest.mock import patch

from aetp.collaboration.policy import PolicyViolation
from aetp.governance.credential_broker import CredentialBroker, CredentialBrokerError
from tests.m2.governance_support import GovernanceCase


class CredentialRevokeSyncTests(GovernanceCase):
    def setUp(self):
        super().setUp()
        self.broker = CredentialBroker()
        self.service.credential_broker = self.broker

    def _issue(self, identifier="cred-1", *, actor="a-1"):
        self.accept(self.command("credential.request", identifier,
                                 {"permissions": ["github.repo.read"], "ttl_ms": 30000}, actor=actor))
        return self.state()[f"credential:{identifier}"]

    def test_human_revoke_stops_the_broker_from_granting(self):
        """The revocation that matters is the one the Broker honours."""
        record = self._issue()
        self.broker.assert_permission_by_ref(record["token_ref"], "github.repo.read", 2000)

        self.accept(self.command("credential.revoke", "cred-1", {}, actor="human-owner"))
        self.assertTrue(self.state()["credential:cred-1"]["revoked"])

        with self.assertRaises(CredentialBrokerError) as ctx:
            self.broker.assert_permission_by_ref(record["token_ref"], "github.repo.read", 2000)
        self.assertEqual(ctx.exception.code, "CREDENTIAL_REVOKED")

    def test_owning_agent_revoke_stops_the_broker_from_granting(self):
        record = self._issue()
        self.accept(self.command("credential.revoke", "cred-1", {}, actor="a-1"))
        with self.assertRaises(CredentialBrokerError) as ctx:
            self.broker.assert_permission_by_ref(record["token_ref"], "github.repo.read", 2000)
        self.assertEqual(ctx.exception.code, "CREDENTIAL_REVOKED")

    def test_revoking_without_a_broker_still_rejects_the_command(self):
        """No broker means the revoke cannot take full effect: refuse it."""
        self._issue()
        self.service.credential_broker = None
        result = self.service.handle(
            self.command("credential.revoke", "cred-1", {}, actor="human-owner"),
            authenticated_actor_id="human-owner")
        self.assertEqual((result.status, result.error_code), ("rejected", "CREDENTIAL_UNAVAILABLE"))


    def test_minted_token_does_not_outlive_a_failed_commit(self):
        """A token whose Event never committed can never be revoked: un-mint it.

        Revocation travels through a Projection record. If the Broker mints a
        credential and the commit then fails, the token stays usable while no
        record exists to revoke it, so it would live until expiry no matter
        what the humans decide.
        """
        broker = self.broker
        original = self.service._batch

        def failing_batch(*args, **kwargs):
            raise RuntimeError("simulated commit failure")

        self.service._batch = failing_batch
        try:
            with self.assertRaises(RuntimeError):
                self.service.handle(
                    self.command("credential.request", "cred-1",
                                 {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1"),
                    authenticated_actor_id="a-1")
        finally:
            self.service._batch = original

        self.assertEqual(broker._credentials, {}, "a minted token survived a failed commit")
        self.assertEqual(broker._ref_to_token, {})
        self.assertNotIn("credential:cred-1", self.state())

    def test_commit_failure_does_not_strand_a_usable_token(self):
        """The judgement must happen after COMMIT, not inside the transaction.

        Inside the writer transaction read_events already shows the uncommitted
        credential.issued, so a later failed COMMIT would leave a token nobody
        can revoke: the record it would travel through never landed.
        """
        broker = self.broker
        store = self.store
        store._ensure_open()
        real = store._connection

        class _CommitFails:
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def commit(self):
                raise RuntimeError("simulated COMMIT failure")

        store._connection = _CommitFails(real)
        try:
            with self.assertRaises(RuntimeError):
                self.service.handle(
                    self.command("credential.request", "cred-1",
                                 {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1"),
                    authenticated_actor_id="a-1")
        finally:
            store._connection = real

        self.assertEqual(broker._credentials, {}, "a token survived a rolled back COMMIT")
        self.assertEqual(broker._ref_to_token, {})
        self.assertNotIn("credential:cred-1", self.state())

    def test_discarding_a_committed_credential_is_refused(self):
        """_discard is bookkeeping for unlanded mints, not a back door.

        Once the Event committed, the Projection is the authority on whether a
        credential is live. Dropping it from the Broker would leave a record
        saying "not revoked" while the token silently stopped resolving.
        """
        self._issue()
        token = next(iter(self.broker._credentials))

        with self.assertRaises(CredentialBrokerError):
            self.broker._discard(token)

        self.assertIn(token, self.broker._credentials, "a committed credential was dropped")

    def test_a_committed_issue_leaves_no_pending_token(self):
        """After a successful issue the Broker must consider it committed.

        Otherwise the token stays discardable and _discard would refuse it
        later, or a stale entry would linger for the process lifetime.
        """
        self._issue()

        self.assertEqual(self.broker._pending, set())

    def test_cleanup_failure_does_not_mask_the_commit_error(self):
        """Un-minting is best effort; it must never hide why the Command failed.

        If the Broker is swapped between mint and commit, cleanup no longer
        recognises the token. Raising there would replace the real failure
        with a credential error and send the caller after the wrong problem.
        """
        store = self.store
        store._ensure_open()
        real = store._connection

        class _CommitFails:
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def commit(self):
                raise RuntimeError("simulated COMMIT failure")

        original_batch = self.service._batch

        def failing_after_mint(*args, **kwargs):
            # Swap the Broker after the token was minted but before the commit.
            self.service._credential_broker = CredentialBroker()
            raise RuntimeError("simulated COMMIT failure")

        store._connection = _CommitFails(real)
        self.service._batch = failing_after_mint
        try:
            with self.assertRaises(RuntimeError):
                self.service.handle(
                    self.command("credential.request", "cred-1",
                                 {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1"),
                    authenticated_actor_id="a-1")
        finally:
            store._connection = real
            self.service._batch = original_batch

    def test_a_broker_that_raises_during_cleanup_never_replaces_the_real_failure(self):
        """Cleanup runs on the way out of a failed Command, and it never raises.

        The neighbouring test shows a *commit* failure reaching the caller. This
        one shows the narrower claim the code actually makes: a Broker whose
        _confirm or _discard raises cannot turn the Command's own failure into a
        credential error. That swallowing was only asserted in a comment - an
        earlier guard narrowed the except and every test still passed.
        """
        broker = self.broker
        token = broker.issue("a-1", permissions=["github.repo.read"],
                             issued_at=self.clock_value, expires_in_ms=30_000, pending=True)["token"]
        request = self.command("credential.request", "cred-1",
                               {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1")

        for method, committed in (("_confirm", True), ("_discard", False)):
            with self.subTest(method=method):
                error = CredentialBrokerError("CREDENTIAL_COMMITTED")

                def raising(*args, **kwargs):
                    raise error

                # No assertRaises: if the exception escaped, the test fails here.
                with patch.object(broker, method, side_effect=raising):
                    self.service._discard_minted_if_orphaned(
                        request, {"minted_tokens": [(broker, token)]}, committed=committed)

    def test_a_cleanup_that_cannot_finish_still_empties_the_minted_list(self):
        """The list is per-Command scratch state; a raising Broker must not leave it queued.

        If minted.clear() were skipped on the exception path, the next reader of
        that context would try the same dead Broker again.
        """
        broker = self.broker
        token = broker.issue("a-1", permissions=["github.repo.read"],
                             issued_at=self.clock_value, expires_in_ms=30_000, pending=True)["token"]
        request = self.command("credential.request", "cred-1",
                               {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1")
        context = {"minted_tokens": [(broker, token)]}

        def raising(*args, **kwargs):
            raise RuntimeError("broker went away")

        with patch.object(broker, "_confirm", side_effect=raising):
            self.service._discard_minted_if_orphaned(request, context, committed=True)
        self.assertEqual(context["minted_tokens"], [])

    def test_an_unknown_minted_entry_is_left_alone_rather_than_guessed_at(self):
        """A malformed entry cannot be attributed to a Broker, so cleanup skips it."""
        request = self.command("credential.request", "cred-1",
                               {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1")
        for entry in (("only-one",), (None, "body", "extra"), "not-a-tuple"):
            with self.subTest(entry=entry):
                self.service._discard_minted_if_orphaned(
                    request, {"minted_tokens": [entry]}, committed=False)

    def test_cleanup_never_discards_a_committed_credential(self):
        """Committed is decided by the caller, and it always wins.

        A committed Command's credential belongs to the Projection. Cleanup is
        told so by the caller rather than guessing from the event stream, so no
        store failure can turn a committed credential into a discardable one.
        """
        minted = self.broker.issue("a-1", permissions=["github.repo.read"],
                                   issued_at=self.clock_value, expires_in_ms=30_000, pending=True)
        token = minted["token"]
        self.assertIn(token, self.broker._pending, "precondition: a fresh mint is pending")
        request = self.command("credential.request", "cred-1",
                               {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1")

        self.service._discard_minted_if_orphaned(request, {"minted_tokens": [(self.broker, token)]},
                                                 committed=True)

        self.assertIn(token, self.broker._credentials, "a committed credential was dropped")
        with self.assertRaises(CredentialBrokerError):
            self.broker._discard(token)

    def test_cleanup_reaches_the_broker_that_minted_the_token(self):
        """A swapped Broker must not leave the original token stranded.

        Cleanup used to read whatever was mounted when the Command ended. If a
        host swapped the instance in between, the old token stayed live with no
        Event behind it, which is the orphan this cleanup exists to prevent.
        """
        old = self.broker
        minted = old.issue("a-1", permissions=["github.repo.read"],
                           issued_at=self.clock_value, expires_in_ms=30_000, pending=True)
        token = minted["token"]
        request = self.command("credential.request", "cred-1",
                               {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1")

        # A different Broker is mounted by the time cleanup runs.
        self.service._credential_broker = CredentialBroker()
        self.service._discard_minted_if_orphaned(request, {"minted_tokens": [(old, token)]},
                                                 committed=False)

        self.assertNotIn(token, old._credentials, "the minting Broker kept an orphaned token")

    def test_failed_commit_is_itself_proof_of_an_orphan(self):
        """A failed COMMIT settles the question; cleanup must not re-read to decide.

        The failure path already knows the credential.issued never landed. If
        cleanup instead asks read_events and that read also fails, the old code
        guessed "committed" and confirmed the token: a usable credential with no
        Event behind it, no Projection record, and nobody able to revoke it
        until it expired.
        """
        store = self.store
        store._ensure_open()
        real = store._connection

        class _CommitFails:
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def commit(self):
                raise RuntimeError("simulated COMMIT failure")

        def failing_read(project_id):
            raise RuntimeError("simulated read failure")

        # Arm the read failure only after the token exists: handle() itself
        # reads events to rebuild state, so failing earlier would skip the mint
        # and the test would pass without proving anything.
        read_failing = []

        original_evaluate = self.service._evaluate

        def evaluate_then_arm(*args, **kwargs):
            outcome = original_evaluate(*args, **kwargs)
            read_failing.append(True)
            return outcome

        def guarded_read(project_id):
            if read_failing:
                raise RuntimeError("simulated read failure")
            return original_read(project_id)

        original_read = store.read_events
        store._connection = _CommitFails(real)
        store.read_events = guarded_read
        self.service._evaluate = evaluate_then_arm
        try:
            with self.assertRaises(RuntimeError):
                self.service.handle(
                    self.command("credential.request", "cred-1",
                                 {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1"),
                    authenticated_actor_id="a-1")
        finally:
            store._connection = real
            store.read_events = original_read
            self.service._evaluate = original_evaluate

        self.assertEqual(self.broker._credentials, {}, "a token survived a failed COMMIT")
        self.assertEqual(self.broker._pending, set())

    def test_a_rejected_revoke_leaves_the_broker_alone(self):
        """A rejected Command must have no effects, and the Broker is an effect.

        Revoking the Broker before the batch is built means a Command that is
        then rejected has already stopped the credential working, while the
        Projection still says it is live. Replay could never reconstruct that.
        """
        record = self._issue()
        original = self.service._batch

        def failing_batch(*args, **kwargs):
            raise PolicyViolation("SIMULATED_LATE_FAILURE")

        self.service._batch = failing_batch
        try:
            result = self.service.handle(
                self.command("credential.revoke", "cred-1", {}, actor="human-owner"),
                authenticated_actor_id="human-owner")
        finally:
            self.service._batch = original

        self.assertEqual(result.status, "rejected")
        self.assertFalse(self.state()["credential:cred-1"]["revoked"])
        # The credential must still work: the rejected Command changed nothing.
        self.broker.assert_permission_by_ref(record["token_ref"], "github.repo.read", 2000)

    def test_a_failed_commit_leaves_the_broker_failing_closed(self):
        """A documented asymmetry, deliberately kept: the Broker fails closed.

        The revoke reaches the Broker inside the writer transaction. If COMMIT
        then fails, the Projection keeps saying the credential is live while the
        Broker already refuses the ref. That divergence is fail-closed on
        purpose: the credential stops being usable, and no Event claims a
        revocation that never happened. Moving the revoke after COMMIT would
        invert it - a revoke that then failed would leave a revoked record whose
        ref the Broker still honours, which is fail-open. Retrying converges
        because _revoke_in_broker treats CREDENTIAL_UNKNOWN as success.

        An independent review re-raised this as a defect; the reasoning above is
        why it is kept. This test pins the intended direction so a later change
        cannot quietly flip it to fail-open. See
        Docs/development/evidence/2026-10-23-credential-broker-single-mount.json
        (F4_revoke_side_effect_inside_the_transaction).
        """
        record = self._issue()
        store = self.store
        store._ensure_open()
        real = store._connection

        class _CommitFails:
            def __init__(self, inner):
                self._inner = inner

            def __getattr__(self, name):
                return getattr(self._inner, name)

            def commit(self):
                raise RuntimeError("simulated COMMIT failure")

        store._connection = _CommitFails(real)
        try:
            with self.assertRaises(RuntimeError):
                self.service.handle(
                    self.command("credential.revoke", "cred-1", {}, actor="human-owner"),
                    authenticated_actor_id="human-owner")
        finally:
            store._connection = real

        self.assertFalse(self.state()["credential:cred-1"]["revoked"],
                         "the rolled back COMMIT must leave no revoked Projection record")
        with self.assertRaises(CredentialBrokerError) as ctx:
            self.broker.assert_permission_by_ref(record["token_ref"], "github.repo.read", 2000)
        self.assertEqual(ctx.exception.code, "CREDENTIAL_REVOKED",
                         "the Broker must fail closed when the Event never landed")

    def test_a_broker_owner_that_disagrees_with_the_record_is_unavailable(self):
        """A Broker denial here is a lost-sync signal, not an authorization failure.

        Command-side authority already passed inside evaluate(), so the Broker is
        not rejecting the caller: its own record of who owns the ref disagrees
        with the Projection record. The two halves of one fact cannot be
        reconciled, which is exactly what CREDENTIAL_UNAVAILABLE means. Reporting
        PERMISSION_DENIED would blame the caller for an internal inconsistency and
        send them after the wrong problem.

        The mismatch is not reachable through the protocol: issue() derives both
        the record's owner_id and the Broker credential's agent from the same
        command.actor_id. It takes a host mounting a Broker that already holds the
        ref for someone else, which is why the refusal stays in place rather than
        being relaxed.
        """
        from aetp.governance.credential_broker import _Credential

        self._issue()
        record = self.state()["credential:cred-1"]
        token = self.broker._ref_to_token[record["token_ref"]]
        held = self.broker._credentials[token]
        self.broker._credentials[token] = _Credential(
            agent="someone-else", permissions=held.permissions,
            issued_at_ms=held.issued_at_ms, expires_at_ms=held.expires_at_ms,
            revoked=held.revoked)

        result = self.service.handle(
            self.command("credential.revoke", "cred-1", {}, actor="human-owner"),
            authenticated_actor_id="human-owner")

        self.assertEqual((result.status, result.error_code), ("rejected", "CREDENTIAL_UNAVAILABLE"))
        self.assertFalse(self.state()["credential:cred-1"]["revoked"])
        # The refusal must not have half-revoked anything.
        self.broker.assert_permission_by_ref(record["token_ref"], "github.repo.read", 2000)

    def test_a_second_request_for_the_same_credential_is_refused(self):
        """Two tokens for one target leaves one nobody can revoke.

        The Projection keeps a single record per target, so a second issue
        overwrites the ref. The first token then stays usable until it expires
        with no record left to revoke it through: an orphan created by the
        Command path rather than by a failed commit.
        """
        self._issue()

        result = self.service.handle(
            self.command("credential.request", "cred-1",
                         {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1"),
            authenticated_actor_id="a-1")

        self.assertEqual((result.status, result.error_code), ("rejected", "CREDENTIAL_STILL_LIVE"))
        self.assertEqual(len(self.broker._credentials), 1, "a second token was minted for one record")

    def test_rotation_after_revocation_is_allowed(self):
        """The guard protects a live token, not the target identifier.

        Refusing every re-issue would make a revoked credential unreplaceable:
        the Agent could never get a working token for that target again. Once
        the old token is revoked there is nothing left to strand.
        """
        self._issue()
        self.accept(self.command("credential.revoke", "cred-1", {}, actor="human-owner"))

        result = self.service.handle(
            self.command("credential.request", "cred-1",
                         {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1"),
            authenticated_actor_id="a-1")

        self.assertEqual((result.status, result.error_code), ("accepted", None))
        record = self.state()["credential:cred-1"]
        self.assertFalse(record["revoked"])
        # The new token works; the old one is still dead.
        self.broker.assert_permission_by_ref(record["token_ref"], "github.repo.read", 2000)

    def test_rotation_after_expiry_is_allowed(self):
        """An expired credential holds nothing live, so a new one may replace it."""
        self._issue()
        self.clock_value += 60_000

        result = self.service.handle(
            self.command("credential.request", "cred-1",
                         {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1"),
            authenticated_actor_id="a-1")

        self.assertEqual((result.status, result.error_code), ("accepted", None))
        self.assertGreater(self.state()["credential:cred-1"]["expires_at_ms"], self.clock_value)

    def test_rotation_keeps_the_aggregate_revision_monotonic(self):
        """A re-issue continues the record, it does not restart it.

        Hard-coding revision 1 on every issue makes the revision go backwards
        once the credential has been revoked (which moved it to 2). Optimistic
        concurrency then accepts a stale expected_revision, and the stored
        revoked=True fact is silently overwritten with revoked=False.
        """
        self._issue()
        self.accept(self.command("credential.revoke", "cred-1", {}, actor="human-owner"))
        self.assertEqual(self.state()["credential:cred-1"]["revision"], 2)

        self.accept(self.command(
            "credential.request", "cred-1",
            {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1",
            revision=2))

        record = self.state()["credential:cred-1"]
        self.assertEqual(record["revision"], 3, "revision went backwards or did not advance")
        self.assertTrue(record["revised"], "a re-issue must mark the record as revised")

    def test_a_stale_expected_revision_cannot_revoke(self):
        """The revision must actually guard the aggregate, not just look right."""
        self._issue()
        self.accept(self.command("credential.revoke", "cred-1", {}, actor="human-owner"))
        self.accept(self.command(
            "credential.request", "cred-1",
            {"permissions": ["github.repo.read"], "ttl_ms": 30_000}, actor="a-1",
            revision=2))

        result = self.service.handle(
            self.command("credential.revoke", "cred-1", {}, actor="human-owner", revision=2),
            authenticated_actor_id="human-owner")

        self.assertEqual((result.status, result.error_code), ("rejected", "REVISION_CONFLICT"))

if __name__ == "__main__":
    unittest.main()
