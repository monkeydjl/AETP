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
