"""A fixed-input host fixture for reproducible Task quality evidence.

These local identities are deterministic test participants, not model calls.
"""

from aetp.quality.service import TaskQualityService
from tests.m3.quality_support import quality_governance
from tests.m3.verification_scenario import VerificationScenario


class QualityScenario(VerificationScenario):
    def __init__(self, store, workspace_root):
        super().__init__(store, workspace_root)
        self.service = TaskQualityService(store, owner_id="human-owner", execution=self.execution,
            input_authority=self.authority, clock=lambda: self.clock)
        self.send("project.governance.configure", "p-1", {"policy": quality_governance()}, actor="human-owner")
        self.send("project.task_quality.configure", "p-1", {"version": "task-quality-1", "max_evidence_age_ms": 60000,
            "integration_exemptions": [{"task_id": "t-1", "scope": "standalone_fixed_json_document",
                "reason": "This specific deliverable is a standalone JSON document with no integration surface"}]}, actor="human-owner")

    def task(self):
        return self.state()["task:t-1"]

    def quality(self, action, payload=None, *, actor="a-1", **kwargs):
        data = dict(payload or {})
        session = None
        if action in {"enroll", "submit", "block", "rework"}:
            session = self.author_session
            data.update(self.fence("t-1", session))
        return self.send(f"task.quality.{action}", "t-1", data, actor=actor, session=session, trusted=True, **kwargs)

    def enroll(self):
        return self.quality("enroll", {"policy_version": "task-quality-1"})

    def submit(self, identifier):
        return self.quality("submit", {"artifact_ids": [identifier], "summary": "The declared document finishes this execution round"})

    def review(self, *, status="approved"):
        self.quality("request_review", {"reviewers": {identifier: "a-2" for identifier in self.task()["quality_cycle"]["artifact_ids"]}}, actor="a-2")
        for identifier in self.task()["quality_cycle"]["reviews"].values():
            self.send("review.quality.submit", identifier, {"status": status,
                "feedback": "The independent fixture peer inspected the fixed content and every criterion"}, actor="a-2", trusted=True)
