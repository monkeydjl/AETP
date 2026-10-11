"""Task quality scenarios over the real document Runtime and trusted fixture ingress."""

from tests.m3.verification_support import VerificationCase, verification_policy

try:
    from aetp.quality.service import TaskQualityService
except ModuleNotFoundError as exc:
    if not exc.name.startswith("aetp.quality"):
        raise
    TaskQualityService = None


def quality_governance(version="gov-task-quality-1", *, mode="selective"):
    value = verification_policy(version, mode=mode)
    value["rules"].extend({"action": action, "risk_level": "low", "approval": "auto"} for action in (
        "task.quality.transition", "task.quality.review", "task.quality.evaluate", "task.integration.exempt"))
    return value


class QualityCase(VerificationCase):
    def setUp(self):
        self.assertIsNotNone(TaskQualityService, "Task quality transitions are not implemented")
        super().setUp()
        self.service = TaskQualityService(self.store, owner_id="human-owner", execution=self.execution,
            input_authority=self.input_authority, meter=self.meter, clock=lambda: self.clock_value)
        self.configure(quality_governance())
        self.configure_task_quality()

    def configure_task_quality(self, *, version="task-quality-1", exempt=True, age=60000):
        values = [{"task_id": "t-1", "scope": "standalone_fixed_json_document",
                   "reason": "A standalone JSON document with no integration surface"}] if exempt else []
        command = self.command("project.task_quality.configure", "p-1", {
            "version": version, "max_evidence_age_ms": age, "integration_exemptions": values}, actor="human-owner")
        return self.accept(command)

    def qcall(self, kind, target="t-1", payload=None, *, actor="a-1", session=None, trusted=True, revision=None):
        command = self.command(kind, target, payload, actor=actor, revision=revision)
        receipt = self.input_authority.issue(command, exposure="internal") if trusted else None
        if session is None:
            session = self.session if actor == "a-1" else self.qa_session if actor == "a-2" else None
        return self.service.handle(command, authenticated_actor_id=actor, session=session, input_receipt=receipt)

    def qaccept(self, *args, **kwargs):
        result = self.qcall(*args, **kwargs)
        self.assertEqual(result.status, "accepted", result.to_dict())
        return result

    def enroll_quality(self):
        version = self.state()["project:p-1"]["task_quality_policy"]["current_version"]
        return self.qaccept("task.quality.enroll", payload={"policy_version": version, **self.fence()})

    def quality_submit(self, artifact_ids=None):
        return self.qaccept("task.quality.submit", payload={"artifact_ids": artifact_ids or ["doc-1"],
            "summary": "This execution round has finished with the declared documents", **self.fence()})

    def quality_review(self, reviewer="a-2", *, actor="a-2"):
        return self.qaccept("task.quality.request_review", payload={"reviewers": {
            identifier: reviewer for identifier in self.task()["quality_cycle"]["artifact_ids"]}}, actor=actor)

    def approve_quality_review(self, *, status="approved", artifact_id="doc-1", actor="a-2"):
        identifier = self.task()["quality_cycle"]["reviews"][artifact_id]
        return self.qaccept("review.quality.submit", identifier,
            {"status": status, "feedback": "Independently inspected the declared document and criteria"}, actor=actor)

    def quality_evaluate(self, *, actor="a-2"):
        return self.qaccept("task.quality.evaluate", actor=actor)

    def quality_complete(self, *, actor="a-2"):
        return self.qaccept("task.quality.complete", actor=actor)

    def ready_quality(self, *, content='{"scope":"local","recovery":true}'):
        self.enroll_quality()
        self.capture(content)
        self.quality_submit()

    def reviewed_quality(self, *, status="approved", content='{"scope":"local","recovery":true}'):
        self.ready_quality(content=content)
        self.quality_review()
        self.approve_quality_review(status=status)

    def verified_quality(self):
        self.reviewed_quality()
        self.request_verification()
        self.service.dispatch("p-1", "v-1", session=self.qa_session)
        self.quality_evaluate()
        self.assertEqual(self.task()["status"], "verified")
