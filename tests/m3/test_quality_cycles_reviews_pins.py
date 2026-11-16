"""Guards in quality/cycles.py and quality/reviews.py that a real Command can reach.

Established by mutation (replace the require() with require(True, ...)) followed by a
reachability probe that reads CommandResult.error_code. A guard is pinned here only when a
genuine command sequence makes IT the deciding refusal -- not an upstream guard that refused
first, possibly with the same code. Guards whose only reachable-by-command trigger is shared
with a neighbour are deliberately absent here; they cannot be pinned, and a test that stays
green under its own mutation would be worse than no test at all.
"""

import unittest

from tests.m3.quality_support import QualityCase, quality_governance


class QualityGuardPinTests(QualityCase):
    def refuse(self, kind, target="t-1", payload=None, *, actor="a-1", **kw):
        result = self.qcall(kind, target, payload, actor=actor, **kw)
        self.assertEqual(result.status, "rejected", result.to_dict())
        return result.error_code

    def reviewers(self):
        identifiers = self.task()["quality_cycle"]["artifact_ids"]
        return {"reviewers": {identifier: "a-2" for identifier in identifiers}}

    # cycles.py:15-16 QUALITY_CONTRACT_REQUIRED -- NOT PINNED, and deliberately so.
    # submission.py:45 raises the same code earlier in the submit path. On the
    # request_review path the first refusal is cycles.py:15-16 itself, raised from
    # durable_cycle before reviews.py:24 (active_cycle) is ever asked (measured).
    # Mutation confirms it: deleting the
    # whole require() at cycles.py:15-16 leaves every test in this file green, because
    # the code the caller sees is produced upstream. A test asserting the code would be
    # green under its own mutation -- a fake pin -- so the contract is left unpinned here
    # and the gap is recorded in the audit evidence instead.

    # cycles.py:30-31 TASK_QUALITY_POLICY_CHANGED -- the task-quality policy moved on.
    def test_a_task_quality_policy_change_invalidates_an_enrolled_round(self):
        self.ready_quality()
        self.configure_task_quality(version="task-quality-2")
        self.assertEqual(self.refuse("task.quality.request_review", payload=self.reviewers()),
                         "TASK_QUALITY_POLICY_CHANGED")

    # cycles.py:33-34 GOVERNANCE_CHANGED -- governance version/digest moved on.
    def test_a_governance_change_invalidates_an_enrolled_round(self):
        self.ready_quality()
        self.configure(quality_governance("gov-task-quality-2"))
        self.assertEqual(self.refuse("task.quality.request_review", payload=self.reviewers()),
                         "GOVERNANCE_CHANGED")

    # reviews.py:58 INVALID_TARGET -- the named review does not exist.
    def test_submitting_a_review_that_does_not_exist_is_refused_by_the_target_guard(self):
        self.reviewed_quality()
        self.assertEqual(
            self.refuse("review.quality.submit", "review-never-created",
                        {"status": "approved", "feedback": "x"}, actor="a-2"),
            "INVALID_TARGET")

    # reviews.py:17 PERMISSION_DENIED -- the reviewer agent lacks the independence role.
    # reviews.py:15 (principal must be an agent) cannot be pinned on its own: a human reviewer
    # that trips :15 trips :17 with the same code, and normalize() forbids a human from ever
    # holding independent_reviewer, so :15 can never be the sole decider. :17 has a clean door.
    def test_a_reviewer_agent_without_the_independence_role_is_refused(self):
        value = quality_governance("gov-task-quality-2")
        for subject in value["subjects"].values():
            subject["roles"] = [role for role in subject["roles"] if role != "independent_reviewer"]
        self.configure(value)
        self.ready_quality()
        self.assertEqual(self.refuse("task.quality.request_review", payload=self.reviewers()),
                         "PERMISSION_DENIED")

    # reviews.py:70 INVALID_PAYLOAD -- the review status is not one of the three verbs.
    def test_a_review_status_outside_the_enum_is_refused_by_the_payload_guard(self):
        self.enroll_quality()
        self.capture()
        self.quality_submit()
        self.quality_review()
        identifier = self.task()["quality_cycle"]["reviews"]["doc-1"]
        self.assertEqual(
            self.refuse("review.quality.submit", identifier,
                        {"status": "looks_fine_to_me", "feedback": "x"}, actor="a-2"),
            "INVALID_PAYLOAD")


if __name__ == "__main__":
    unittest.main()
