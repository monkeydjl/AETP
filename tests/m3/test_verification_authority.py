"""Observable authority and execution contracts for the new Verification path."""

import copy
import json
from dataclasses import replace
from unittest.mock import patch

from aetp.acceptance.runner import FixedJsonRunner
from aetp.core.projection import Projection
from aetp.runtime.document import Session
from tests.m2.governance_support import policy
from tests.m3.support import PlanningCase
from tests.m3.verification_support import (
    AcceptanceService,
    VerificationCase,
    verification_policy,
)


class VerificationAuthorityTests(VerificationCase):
    def submit(self, command, *, session=None, trusted=True, receipt=None):
        if receipt is None and trusted:
            receipt = self.input_authority.issue(command, exposure="internal")
        return self.service.handle(command, authenticated_actor_id=command.actor_id,
            session=self.qa_session if session is None else session, input_receipt=receipt)

    def test_only_current_human_owner_can_configure_quality(self):
        before = self.state()["project:p-1"]["quality"]
        for actor in ("a-1", "a-2", "human-peer", "bootstrap"):
            with self.subTest(actor=actor):
                self.reject(self.command("project.quality.configure", "p-1", {"grant_ttl_ms": 1000}, actor=actor),
                            "PERMISSION_DENIED")
        self.assertEqual(self.state()["project:p-1"]["quality"], before)

    def test_passed_report_binds_real_action_and_leaves_tasks_uncompleted(self):
        artifact = self.capture()
        author_before = self.task()
        verification = self.request_verification()
        self.assertEqual(verification["case_set"]["author_id"], "a-2")
        self.assertEqual(verification["action"]["status"], "pending")
        result = self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.assertEqual(result["result"], "PASSED")
        self.assertEqual(result["action"]["dispatch_count"], 1)
        self.assertEqual(result["action"]["status"], "completed")
        report_artifact = self.state()[f"artifact:{result['evidence_id']}"]
        report = json.loads(report_artifact["content"])
        self.assertEqual(report["input"]["artifact_digest"], artifact["content_digest"])
        self.assertEqual(report["action_id"], verification["action"]["id"])
        self.assertEqual(report["runner"]["method"], "strict_json_path_equals")
        self.assertEqual([x["matched"] for x in report["observation"]["checks"]], [True, True])
        self.assertEqual(self.task(), author_before)
        self.assertEqual(self.state()["task:qa-task"]["status"], "in_progress")
        self.assertEqual(Projection.pending_command_ids(self.store.read_events("p-1"), self.commands()), [])

    def test_failed_checks_are_not_reported_inconclusive(self):
        self.capture('{"scope":"public","recovery":true}')
        self.request_verification()
        result = self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.assertEqual(result["result"], "FAILED")
        self.assertEqual(result["reason"], "CHECKS_FAILED")

    def test_request_and_dispatch_retries_never_run_twice(self):
        self.capture()
        command = self.verification_command()
        accepted = self.submit(command)
        self.assertEqual(accepted.status, "accepted", accepted.to_dict())
        # A valid saved Command returns its facts even if this capability expires.
        repeated = self.service.handle(command, authenticated_actor_id="a-2")
        self.assertEqual(accepted.to_dict(), repeated.to_dict())
        count = []
        run = FixedJsonRunner.run

        def counted(runner, content, cases):
            count.append(1)
            return run(runner, content, cases)

        with patch.object(FixedJsonRunner, "run", counted):
            first = self.service.dispatch("p-1", "v-1", session=self.qa_session)
            event_count = len(self.store.read_events("p-1"))
            second = self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.assertEqual(first, second)
        self.assertEqual(first["result"], "PASSED")
        self.assertEqual(len(count), 1)
        self.assertEqual(len(self.store.read_events("p-1")), event_count)

    def test_author_cannot_use_own_task_to_certify_own_artifact(self):
        self.capture()
        command = self.verification_command(exec_task_id="t-1", **self.fence())
        command = replace(command, actor_id="a-1")
        result = self.submit(command, session=self.session)
        self.assertEqual(result.error_code, "INDEPENDENCE_REQUIRED")
        self.assertNotIn("verification:v-1", self.state())

    def test_independent_actor_cannot_borrow_author_lease(self):
        self.capture()
        result = self.submit(self.verification_command(exec_task_id="t-1", **self.fence()))
        self.assertEqual(result.error_code, "INDEPENDENT_EXECUTION_TASK_REQUIRED")

    def test_copied_session_is_not_a_runtime_capability(self):
        self.capture()
        counterfeit = Session(**{name: getattr(self.qa_session, name) for name in Session.__slots__})
        result = self.submit(self.verification_command(), session=counterfeit)
        self.assertEqual(result.error_code, "SESSION_INVALID")

    def test_case_authorship_or_runner_result_cannot_be_self_reported(self):
        self.capture()
        for index, change in enumerate(({"test_authorship": "a-2"}, {"result": "PASSED"},
                                        {"runner": {"trusted": True}}, {"untrusted_input": False})):
            result = self.submit(self.verification_command(f"v-{index}", **change))
            self.assertEqual(result.error_code, "INVALID_PAYLOAD")
        self.assertFalse(any(key.startswith("verification:") for key in self.state()))

    def test_every_current_criterion_needs_one_ordered_case(self):
        self.capture()
        fixtures = [[{"criterion": "Scope", "path": ["scope"], "equals": "local"}],
                    [{"criterion": "Recovery", "path": ["recovery"], "equals": True},
                     {"criterion": "Scope", "path": ["scope"], "equals": "local"}]]
        for index, cases in enumerate(fixtures):
            result = self.submit(self.verification_command(f"v-{index}", cases=cases))
            self.assertEqual(result.error_code, "INVALID_PAYLOAD")

    def test_governance_manual_missing_rule_and_approval_path_remain_closed(self):
        self.capture()
        policies = [policy("no-rule"), verification_policy("manual", mode="manual"),
                    verification_policy("approval", approval="decision_based")]
        for index, value in enumerate(policies):
            self.configure(value)
            result = self.submit(self.verification_command(f"v-{index}"))
            self.assertEqual(result.error_code, "POLICY_DENIED" if index == 0 else "APPROVAL_REQUIRED")
        self.assertFalse(any(key.startswith("verification:") for key in self.state()))

    def test_declared_risk_cannot_be_lowered_by_fixed_checker(self):
        self.capture()
        for risk in ("medium", "high", "critical"):
            result = self.submit(self.verification_command(f"v-{risk}", risk_level=risk))
            self.assertEqual(result.error_code, "APPROVAL_REQUIRED")

    def test_untrusted_inline_cannot_be_laundered_by_new_ingress(self):
        self.accept(self.command("artifact.submit", "doc-1", {"task_id": "t-1", "type": "document",
                            "content": '{"scope":"local","recovery":true}'}))
        result = self.submit(self.verification_command())
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        self.assertTrue(self.state()["artifact:doc-1"]["source"]["untrusted_input"])

    def test_capture_inherits_marked_origin_even_after_document_approval(self):
        artifact = self.capture(trusted=False)
        self.assertTrue(artifact["source"]["untrusted_input"])
        result = self.submit(self.verification_command())
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")

    def test_unknown_control_or_copied_ingress_capability_cannot_authorize(self):
        self.capture()
        result = self.submit(self.verification_command("v-unknown"), trusted=False)
        self.assertEqual(result.error_code, "APPROVAL_REQUIRED")
        command = self.verification_command("v-forged")
        receipt = self.input_authority.issue(command, exposure="internal")
        result = self.submit(command, receipt=copy.copy(receipt))
        self.assertEqual(result.error_code, "INPUT_CONTEXT_INVALID")

    def test_agent_cannot_dispatch_or_record_host_result(self):
        self.capture()
        self.request_verification()
        for kind in ("verification.dispatch", "verification.record"):
            command = self.command(kind, "v-1", {}, actor="a-2")
            result = self.submit(command)
            self.assertEqual(result.error_code, "ENFORCEMENT_UNAVAILABLE")
        self.assertEqual(self.verification()["action"]["status"], "pending")

    def test_revoke_prevents_execution_and_produces_conservative_report(self):
        self.capture()
        self.request_verification()
        self.accept(self.command("verification.revoke", "v-1", {"reason": "Cases need correction"}, actor="a-2"))
        with patch.object(FixedJsonRunner, "run", side_effect=AssertionError("revoked grant ran")):
            result = self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.assertEqual(result["result"], "INCONCLUSIVE")
        self.assertEqual(result["reason"], "GRANT_REVOKED")
        self.assertEqual(result["action"]["dispatch_count"], 0)

    def test_quality_pass_does_not_open_legacy_completion_gate(self):
        self.capture()
        self.request_verification()
        self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.accept(self.command("review.request", "r-1", {"artifact_id": "doc-1",
            "artifact_digest": self.state()["artifact:doc-1"]["content_digest"], "reviewer_id": "a-2"}))
        self.accept(self.command("review.submit", "r-1", {"artifact_digest": self.state()["artifact:doc-1"]["content_digest"],
            "status": "approved", "feedback": "Independently compared the document"}, actor="a-2"))
        self.reject(self.command("task.complete", "t-1", {"artifact_id": "doc-1", "review_id": "r-1",
            "verification_id": "v-1"}), "ENFORCEMENT_UNAVAILABLE")


class VerificationCandidateBoundaryTests(PlanningCase):
    def test_candidate_planning_cannot_open_verification_execution(self):
        self.assertIsNotNone(AcceptanceService)
        self.service = AcceptanceService(self.store, owner_id="human-owner", clock=lambda: self.clock_value)
        command = self.command("verification.request", "v-1", {"artifact_id": "not-executable",
            "artifact_digest": "sha256:" + "0" * 64, "exec_task_id": "qa", "binding_id": "absent",
            "lease_epoch": 1, "session_id": "absent", "cases": [{"criterion": "Scope", "path": [], "equals": 1}]})
        with patch.object(FixedJsonRunner, "run", side_effect=AssertionError("candidate mode executed")):
            self.reject(command, "PLANNING_NOT_ACTIVE")
        self.assertFalse(any(key.startswith(("task:", "verification:")) for key in self.state()))
