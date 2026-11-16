"""Quality usage is historical applicability, not a new Runner dispatch."""

import copy
from unittest.mock import patch

from aetp.collaboration.policy import PolicyViolation
from aetp.domain.models import COMMAND_TYPES
from tests.m3.quality_support import QualityCase, quality_governance


class QualityEvidenceTests(QualityCase):
    def setUp(self):
        super().setUp()
        self.assertIn("task.quality.evaluate", COMMAND_TYPES, "Evidence-driven Task evaluation is not implemented")

    def run_verification(self, identifier="v-1", **changes):
        self.request_verification(identifier, **changes)
        return self.service.dispatch("p-1", identifier, session=self.qa_session)

    def test_real_passed_evidence_and_independent_review_verify(self):
        self.reviewed_quality()
        self.assertEqual(self.run_verification()["result"], "PASSED")
        self.quality_evaluate()
        task = self.task()
        self.assertEqual(task["status"], "verified")
        use = task["quality_cycle"]["uses"][-1]
        self.assertEqual(use["result"], "PASSED")
        self.assertEqual(use["verification_ids"], ["v-1"])
        self.assertEqual(use["quality_cycle_id"], task["quality_cycle"]["id"])
        self.assertEqual(use["current_task_revision"], task["revision"] - 1)
        self.assertLess(use["original_task_revision"], use["current_task_revision"])

    def test_valid_failed_evidence_rejects(self):
        self.reviewed_quality(content='{"scope":"remote","recovery":true}')
        self.assertEqual(self.run_verification()["result"], "FAILED")
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "rejected")

    def test_a_pending_review_never_verifies_a_passing_verification(self):
        """A PASSED verification is not enough while the review is still pending.

        `all_passed` ANDs each review's status with "approved". Drop that term and
        a review nobody has approved yet stops blocking, so a passing verification
        alone would move the Task to `verified`. The negative-review test does not
        cover this: a pending review is not negative, so nothing else rejects it.
        """
        self.ready_quality()
        self.quality_review()  # requested, never submitted: the review stays pending
        self.assertEqual(self.run_verification()["result"], "PASSED")
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "in_review",
                         "a pending review let a passing verification verify the task")

    def test_negative_review_rejects_even_without_verification(self):
        self.reviewed_quality(status="changes_requested")
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "rejected")

    def test_missing_and_pending_evidence_stay_in_review(self):
        self.reviewed_quality()
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "in_review")
        self.request_verification()
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "in_review")
        self.assertEqual(self.task()["quality_cycle"]["uses"][-1]["verification_ids"], ["v-1"])
        self.assertEqual(self.service.dispatch("p-1", "v-1", session=self.qa_session)["result"], "PASSED")
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "verified")

    def test_runner_error_is_inconclusive_and_does_not_reject_task(self):
        self.reviewed_quality()
        self.request_verification()
        with patch.object(self.service._runner, "run", side_effect=ValueError("fixture runner error")):
            result = self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.assertEqual(result["result"], "INCONCLUSIVE")
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "in_review")

    def test_dispatch_ttl_does_not_expire_historical_passed_evidence(self):
        self.reviewed_quality()
        self.run_verification()
        self.clock_value += 1100
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "verified")
        self.assertEqual(self.verification()["result"], "PASSED")

    def test_wall_clock_maximum_age_rejects_use_without_rewriting_passed(self):
        self.configure_task_quality(version="short-age", age=500)
        self.reviewed_quality()
        self.run_verification()
        self.clock_value += 501
        result = self.qcall("task.quality.evaluate", actor="a-2")
        self.assertEqual(result.error_code, "EVIDENCE_EXPIRED")
        self.assertEqual(self.verification()["result"], "PASSED")
        self.assertEqual(self.task()["status"], "in_review")

    def test_current_qa_task_revision_and_session_are_not_dispatch_requirements_for_use(self):
        self.reviewed_quality()
        self.run_verification()
        self.eaccept(self.command("lease.revoke", "qa-task", {"reason": "handoff", **self.qa_fence()}, actor="a-2"))
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "verified")

    def test_all_cycle_records_are_collected_before_validity_filtering(self):
        self.reviewed_quality()
        self.run_verification()
        self.request_verification("v-revoked")
        self.accept(self.command("verification.revoke", "v-revoked", {"reason": "Invalid execution"}, actor="a-2"))
        self.service.dispatch("p-1", "v-revoked", session=self.qa_session)
        result = self.qcall("task.quality.evaluate", actor="a-2")
        self.assertEqual(result.error_code, "GRANT_REVOKED")
        self.assertEqual(self.task()["status"], "in_review")

    def test_valid_failed_record_is_not_hidden_by_another_passed_record(self):
        self.reviewed_quality()
        self.run_verification()
        self.run_verification("v-failed", cases=[
            {"criterion": "Scope", "path": ["scope"], "equals": "remote"},
            {"criterion": "Recovery", "path": ["recovery"], "equals": True}])
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "rejected")
        self.assertEqual(self.task()["quality_cycle"]["uses"][-1]["verification_ids"], ["v-1", "v-failed"])

    def test_multiple_artifacts_each_need_evidence(self):
        self.enroll_quality()
        self.capture(identifier="doc-1")
        self.capture(identifier="doc-2")
        self.quality_submit(["doc-1", "doc-2"])
        self.quality_review()
        self.approve_quality_review(artifact_id="doc-1")
        self.approve_quality_review(artifact_id="doc-2")
        self.run_verification()
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "in_review")
        self.run_verification("v-2", artifact_id="doc-2")
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "verified")

    def test_legacy_pass_is_not_promoted_into_new_round(self):
        self.capture(identifier="legacy-doc")
        self.run_verification("legacy-v", artifact_id="legacy-doc")
        self.reviewed_quality()
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "in_review")
        self.assertEqual(self.task()["quality_cycle"]["uses"][-1]["verification_ids"], [])

    def test_changed_governance_version_rejects_current_use(self):
        self.reviewed_quality()
        self.run_verification()
        self.configure(quality_governance("new-governance"))
        result = self.qcall("task.quality.evaluate", actor="a-2")
        self.assertEqual(result.error_code, "GOVERNANCE_CHANGED")

    def test_changed_verification_policy_rejects_old_evidence(self):
        self.reviewed_quality()
        self.run_verification()
        self.accept(self.command("project.quality.configure", "p-1", {"grant_ttl_ms": 2000}, actor="human-owner"))
        result = self.qcall("task.quality.evaluate", actor="a-2")
        self.assertEqual(result.error_code, "QUALITY_POLICY_CHANGED")

    def test_changed_task_quality_policy_requires_explicit_new_work(self):
        self.reviewed_quality()
        self.run_verification()
        self.configure_task_quality(version="new-task-quality")
        result = self.qcall("task.quality.evaluate", actor="a-2")
        self.assertEqual(result.error_code, "TASK_QUALITY_POLICY_CHANGED")

    def test_changed_runner_descriptor_rejects_evidence_use(self):
        self.reviewed_quality()
        self.run_verification()
        descriptor = copy.deepcopy(self.service._runner.descriptor)
        descriptor["environment"]["python_version"] = "different-fixture-version"
        from unittest.mock import PropertyMock
        with patch.object(type(self.service._runner), "descriptor", new_callable=PropertyMock, return_value=descriptor):
            result = self.qcall("task.quality.evaluate", actor="a-2")
        self.assertEqual(result.error_code, "RUNNER_CHANGED")

    def test_target_session_expiry_prevents_quality_advancement(self):
        self.reviewed_quality()
        self.run_verification()
        self.clock_value = self.session.expires_at_wall_ms
        result = self.qcall("task.quality.evaluate", actor="a-2")
        self.assertEqual(result.error_code, "SESSION_EXPIRED")

    def test_unknown_target_revision_growth_cannot_silently_reuse_cycle(self):
        self.reviewed_quality()
        self.run_verification()
        self.eaccept(self.command("execution.report", "t-1", {"summary": "Unexpected report", **self.fence()}),
                     session=self.session)
        result = self.qcall("task.quality.evaluate", actor="a-2")
        self.assertEqual(result.error_code, "QUALITY_CONTEXT_STALE")

    def test_callers_cannot_choose_evaluation_outcome(self):
        self.reviewed_quality()
        result = self.qcall("task.quality.evaluate", payload={"result": "PASSED"}, actor="a-2")
        self.assertEqual(result.error_code, "INVALID_PAYLOAD")

    def test_pure_assessment_never_calls_dispatch_authorizer_or_runner(self):
        self.reviewed_quality()
        self.run_verification()
        from aetp.quality.evidence import assess
        state = self.state()
        context = {"target_live": self.execution.validation_context("p-1", self.session),
                   "runner": self.service._runner.descriptor}
        with patch("aetp.acceptance.records.authorization_error", side_effect=AssertionError("dispatch authorizer")), \
                patch.object(self.service._runner, "run", side_effect=AssertionError("Runner invocation")):
            value = assess(state, state["task:t-1"], self.clock_value, context)
        self.assertEqual(value["result"], "PASSED")

    def test_changed_source_cannot_consume_original_pass(self):
        self.reviewed_quality()
        self.run_verification()
        from aetp.quality.evidence import assess
        state = self.state()
        state["artifact:doc-1"]["source"]["untrusted_input"] = True
        context = {"target_live": self.execution.validation_context("p-1", self.session),
                   "runner": self.service._runner.descriptor}
        with self.assertRaises(PolicyViolation) as error:
            assess(state, state["task:t-1"], self.clock_value, context)
        self.assertEqual(error.exception.code, "EVIDENCE_STALE")

    def test_a_cycle_with_no_review_yet_is_inconclusive_not_passed(self):
        """Reached on the real path: submit, then assess before any review lands.

        Submission leaves `cycle["reviews"]` empty, so the loop records a missing
        review and clears `all_passed`. Drop that line and a cycle no reviewer has
        touched yet reads as a full pass. No State is tampered with here.
        """
        self.ready_quality()
        from aetp.quality.evidence import assess
        state = self.state()
        self.assertEqual(state["task:t-1"]["quality_cycle"]["reviews"], {})
        context = {"target_live": self.execution.validation_context("p-1", self.session),
                   "runner": self.service._runner.descriptor}
        use = assess(state, state["task:t-1"], self.clock_value, context)
        self.assertEqual(use["result"], "INCONCLUSIVE")
        self.assertEqual([row["kind"] for row in use["missing"]], ["review"])

    def test_assessment_rederives_reviewer_independence(self):
        """Defence in depth: independence is re-derived, not trusted from the record.

        A Review is created by an independent reviewer, and `assess` re-runs
        `independent_reviewer` against the live State instead of believing the
        stored reviewer_id. The guard is not reachable through a Command -- a role
        change bumps the governance digest and `durable_cycle` refuses first with
        GOVERNANCE_CHANGED -- so the State is edited directly to exercise it.
        """
        self.reviewed_quality()
        self.run_verification()
        from aetp.quality.evidence import assess
        state = self.state()
        review_id = state["task:t-1"]["quality_cycle"]["reviews"]["doc-1"]
        state[f"review:{review_id}"]["reviewer_id"] = state["task:t-1"]["owner_id"]
        context = {"target_live": self.execution.validation_context("p-1", self.session),
                   "runner": self.service._runner.descriptor}
        with self.assertRaises(PolicyViolation) as error:
            assess(state, state["task:t-1"], self.clock_value, context)
        self.assertEqual(error.exception.code, "INDEPENDENCE_REQUIRED")

    def test_a_settled_review_must_carry_its_response_authorization(self):
        """Defence in depth: a settled review must name the authorization behind it.

        The guard admits a pending Review, which has no verdict yet, but requires
        every settled status to carry the response authorization. `submit_review`
        always writes one, so the State is edited directly to exercise the branch.
        """
        self.reviewed_quality()
        self.run_verification()
        from aetp.quality.evidence import assess
        state = self.state()
        review_id = state["task:t-1"]["quality_cycle"]["reviews"]["doc-1"]
        self.assertIsNotNone(state[f"review:{review_id}"]["response_authorization"])
        state[f"review:{review_id}"]["response_authorization"] = None
        context = {"target_live": self.execution.validation_context("p-1", self.session),
                   "runner": self.service._runner.descriptor}
        with self.assertRaises(PolicyViolation) as error:
            assess(state, state["task:t-1"], self.clock_value, context)
        self.assertEqual(error.exception.code, "EVIDENCE_STALE")

    def _first_verification_use(self, state):
        """Run verification_use directly on the first stored Verification record.

        Calling it directly exercises the identity guards on their own contract,
        with the assessment-time re-derivations out of the way -- those refuse
        some of these States earlier, which is exactly what keeps the guards
        below off the real path.
        """
        from aetp.quality.evidence_checks import verification_use
        task = state["task:t-1"]
        record = sorted((row for key, row in state.items() if key.startswith("verification:")),
                        key=lambda row: row["id"])[0]
        context = {"target_live": self.execution.validation_context("p-1", self.session),
                   "runner": self.service._runner.descriptor}
        return verification_use(record, state, task, task["quality_cycle"], self.clock_value, context)

    def _finished_evidence(self, identifier="v-1"):
        """Finish a real run and hand back the State together with both keys.

        _historical_report is only reached by finished records, so the pins below
        start from a genuinely committed report rather than a hand-built dict.
        """
        self.reviewed_quality()
        self.run_verification(identifier)
        state = self.state()
        record_key = sorted(key for key in state if key.startswith("verification:"))[0]
        return state, record_key, "artifact:" + state[record_key]["evidence_id"]

    def _rewrite_committed_report(self, state, record_key, report_key, changes):
        """Apply changes to the committed report and move the whole digest chain with it.

        _historical_report:75-76 requires
        evidence.content_digest == record.evidence_digest == digest_text(evidence.content).
        An edit that does not re-seal all three stops at that clause instead of reaching
        the clause under test -- which is how a State-edit pin silently ends up measuring
        the wrong guard. Every clause in :86 is derived from the record, so re-sealing is
        what lets an edit aim at a specific clause further down.
        """
        import json

        from aetp.collaboration.policy import canonical_json, digest_text

        record, evidence = state[record_key], state[report_key]
        report = json.loads(evidence["content"])
        report.update(changes)
        evidence["content"] = canonical_json(report)
        evidence["content_digest"] = digest_text(evidence["content"])
        record["evidence_digest"] = evidence["content_digest"]
        return report

    def test_verification_use_binds_the_stored_verifier_to_the_reviewer(self):
        """Defence in depth: the agent that ran the check must be the named reviewer.

        acceptance/records.py:223 writes verifier_id from the requesting actor and
        nothing rewrites it, and the request already ran verification_allowed,
        which requires that same actor to be the reviewer. So no Command produces a
        record where the two disagree; the State is edited directly to exercise the
        guard. It stops a stored verification whose runner identity drifted away
        from the review it answers to.
        """
        self.reviewed_quality()
        self.run_verification()
        state = self.state()
        record_key = sorted(key for key in state if key.startswith("verification:"))[0]
        state[record_key]["verifier_id"] = "a-3"
        with self.assertRaises(PolicyViolation) as error:
            self._first_verification_use(state)
        self.assertEqual(error.exception.code, "REVIEWER_MISMATCH")

    def test_verification_use_refuses_a_reviewer_who_owns_the_task(self):
        """Defence in depth: the reviewer must not be the Task owner.

        Independence is required when the Review is requested (reviews.py:14) and
        re-derived at assessment time (evidence.py:48), so on the real path an
        owner-reviewer is refused earlier as INDEPENDENCE_REQUIRED. This is the
        same rule restated where the evidence is consumed. verifier_id is moved
        along with reviewer_id so that only this clause, not the equality above
        it, decides the outcome.

        Note on how this test catches a regression: removing the clause does not
        turn the call into a success. Control falls through to the execution
        binding check further down, which reports EVIDENCE_STALE instead, so the
        test fails on the error code. That is indirect but it is still a failure,
        which is why the exact code is asserted rather than a set that would let
        both values through and lose the pin entirely.
        """
        self.reviewed_quality()
        self.run_verification()
        state = self.state()
        task = state["task:t-1"]
        review_key = f"review:{task['quality_cycle']['reviews']['doc-1']}"
        record_key = sorted(key for key in state if key.startswith("verification:"))[0]
        state[review_key]["reviewer_id"] = state[record_key]["verifier_id"] = task["owner_id"]
        with self.assertRaises(PolicyViolation) as error:
            self._first_verification_use(state)
        self.assertEqual(error.exception.code, "REVIEWER_MISMATCH")

    def test_verification_use_requires_an_agent_reviewer(self):
        """Defence in depth: only a principal of type agent may stand as reviewer.

        records.request already requires the requesting actor to be an agent
        (records.py:186), and that actor becomes the reviewer, so a human reviewer
        cannot arise on the Command path. The State is edited directly to put a
        human identity there and reach this clause.
        """
        self.reviewed_quality()
        self.run_verification()
        state = self.state()
        task = state["task:t-1"]
        review_key = f"review:{task['quality_cycle']['reviews']['doc-1']}"
        record_key = sorted(key for key in state if key.startswith("verification:"))[0]
        state[review_key]["reviewer_id"] = state[record_key]["verifier_id"] = "human-owner"
        with self.assertRaises(PolicyViolation) as error:
            self._first_verification_use(state)
        self.assertEqual(error.exception.code, "PERMISSION_DENIED")

    def test_a_pending_grant_stops_being_usable_once_its_clock_expires(self):
        """A Grant is single-use and time-boxed; an overdue one must not verify anything.

        This one sits on the real path, unlike the identity clauses above. The
        record is left pending by requesting a verification without dispatching it,
        and the only thing that moves is the clock. No State is edited. Without the
        clause an expired Grant would still be consumed to advance an in_review
        Task on evidence it is no longer allowed to produce.
        """
        self.reviewed_quality()
        self.request_verification()
        record = self.verification()
        self.assertEqual(record["status"], "pending")
        self.clock_value = record["grant"]["expires_at_ms"]
        result = self.qcall("task.quality.evaluate", actor="a-2")
        self.assertEqual(result.error_code, "GRANT_EXPIRED")
        self.assertEqual(self.task()["status"], "in_review")
        self.assertIsNone(self.verification()["evidence_id"])

    def test_verification_use_refuses_a_record_whose_input_drifted_from_its_target(self):
        """Defence in depth: a stored record must still describe the target it ran on.

        Nothing on the Command path can move an Artifact once its Task reached
        in_review -- measured: artifact.capture, task.quality.submit and
        task.quality.enroll are each refused at that point. So the record's own
        input snapshot is edited instead.

        The record is left pending on purpose. A finished record would also be
        caught by the report rebuild further down as the same EVIDENCE_STALE, which
        would keep the suite green if this clause were deleted and quietly turn the
        pin back into a non-measurement.
        """
        self.reviewed_quality()
        self.request_verification()
        state = self.state()
        record_key = sorted(key for key in state if key.startswith("verification:"))[0]
        self.assertEqual(state[record_key]["status"], "pending")
        state[record_key]["input"]["artifact_digest"] = "sha256:" + "0" * 64
        with self.assertRaises(PolicyViolation) as error:
            self._first_verification_use(state)
        self.assertEqual(error.exception.code, "EVIDENCE_STALE")

    def test_verification_use_refuses_an_out_of_range_dispatch_count(self):
        """Defence in depth: a dispatch count outside {0, 1} is not a real outcome.

        acceptance/records.py:394 is the only writer and it moves the count 0 -> 1
        under an ACTION_NOT_PENDING guard, so the range cannot be violated from the
        Command path. The State is edited directly to reach the clause.

        Pending again, for the same reason as the test above: on a finished record
        the PASSED/FAILED clause below re-checks dispatch_count == 1 and would catch
        the mutation under the same error code.
        """
        self.reviewed_quality()
        self.request_verification()
        state = self.state()
        record_key = sorted(key for key in state if key.startswith("verification:"))[0]
        self.assertEqual(state[record_key]["status"], "pending")
        state[record_key]["action"]["dispatch_count"] = 2
        with self.assertRaises(PolicyViolation) as error:
            self._first_verification_use(state)
        self.assertEqual(error.exception.code, "EVIDENCE_STALE")

    # ------------------------------------------------------------------
    # _historical_report pins (:71-111).
    #
    # The report artifact and the record are produced together inside
    # acceptance/records.py:293-346 finish(), from one previous record, and the
    # report id is reserved (core/commands.py:189), so no Command can make them
    # disagree -- a six-step probe with real Commands could not (re-capture,
    # artifact.submit, second finish, second dispatch, post-finish recovery).
    # These pins therefore edit State directly, and each one re-seals the digest
    # chain so it reaches the clause it names instead of stopping at the chain
    # check above it.
    #
    # Two clauses below are deliberately NOT pinned: :100-101 (outcome/result
    # membership) and :104 (completed + dispatch_count). Removing either leaves a
    # later clause raising the same EVIDENCE_STALE from the same function, so a
    # test cannot tell the deletion from the normal refusal. They are recorded as
    # same-code redundancy in the evidence file rather than pinned with a test
    # that would stay green under its own mutation.
    # ------------------------------------------------------------------

    def test_historical_report_requires_the_committed_report_artifact(self):
        """Defence in depth: a finished run must still carry its own report.

        finish() writes it under a reserved id, so deleting it is not reachable
        from a Command; the State is edited to reach the clause.
        """
        state, record_key, report_key = self._finished_evidence()
        self.assertIn(report_key, state)
        del state[report_key]
        with self.assertRaises(PolicyViolation) as error:
            self._first_verification_use(state)
        self.assertEqual(error.exception.code, "EVIDENCE_STALE")

    def test_historical_report_rejects_a_report_drifted_from_its_record(self):
        """Defence in depth: the stored report must restate the record exactly.

        The digest chain is re-sealed, so the drift this test reaches is the one
        :86 compares against the record, not the chain check at :75-76.
        """
        state, record_key, report_key = self._finished_evidence()
        self._rewrite_committed_report(state, record_key, report_key,
                                       {"scope": "wider_than_declared"})
        with self.assertRaises(PolicyViolation) as error:
            self._first_verification_use(state)
        self.assertEqual(error.exception.code, "EVIDENCE_STALE")

    def test_historical_report_rejects_extra_fields_on_the_report_artifact(self):
        """Defence in depth: the whole report artifact is rebuilt, not spot-checked.

        An extra key leaves content and digest untouched, so :86 still passes and
        only the full artifact comparison at :98 decides the outcome.
        """
        state, record_key, report_key = self._finished_evidence()
        state[report_key]["unexpected_field"] = "smuggled"
        with self.assertRaises(PolicyViolation) as error:
            self._first_verification_use(state)
        self.assertEqual(error.exception.code, "EVIDENCE_STALE")

    def test_historical_report_rejects_a_result_that_contradicts_its_observation(self):
        """Defence in depth: a PASSED/FAILED verdict must match the recorded checks.

        edit() derives result and reason from the observation, so the two cannot
        disagree when the record is written; the State is edited to reach :106.
        """
        state, record_key, report_key = self._finished_evidence()
        self.assertEqual(state[record_key]["result"], "PASSED")
        self._rewrite_committed_report(state, record_key, report_key, {
            "result": "FAILED",
            "reason": "ALL_CHECKS_MATCHED",
        })
        state[record_key]["result"] = "FAILED"
        with self.assertRaises(PolicyViolation) as error:
            self._first_verification_use(state)
        self.assertEqual(error.exception.code, "EVIDENCE_STALE")

    def test_historical_report_rejects_a_not_executed_run_that_claims_an_observation(self):
        """Defence in depth: outcome, observation and action status must agree.

        finish() sets observation to None for not_executed and cancels the action
        in the same transaction; the State is edited so the three disagree.
        """
        state, record_key, report_key = self._finished_evidence()
        self._rewrite_committed_report(state, record_key, report_key,
                                       {"execution_outcome": "not_executed", "result": "INCONCLUSIVE"})
        state[record_key]["result"] = "INCONCLUSIVE"
        with self.assertRaises(PolicyViolation) as error:
            self._first_verification_use(state)
        self.assertEqual(error.exception.code, "EVIDENCE_STALE")

    def test_historical_report_rejects_a_recovery_with_the_wrong_termination(self):
        """Defence in depth: a recovered run must cite the exclusive-gate termination.

        finish() only accepts outcome=recovered when the channel reports that exact
        termination (records.py:300-303), so a mismatched pair cannot be committed;
        the State is edited to reach :110-111.
        """
        state, record_key, report_key = self._finished_evidence()
        self._rewrite_committed_report(state, record_key, report_key, {
            "execution_outcome": "recovered",
            "observation": None,
            "result": "INCONCLUSIVE",
            "termination": "runner_said_so",
        })
        state[record_key]["result"] = "INCONCLUSIVE"
        state[record_key]["action"]["status"] = "abandoned"
        with self.assertRaises(PolicyViolation) as error:
            self._first_verification_use(state)
        self.assertEqual(error.exception.code, "EVIDENCE_STALE")
