"""Trusted fixture ingress over real SQLite, independent Tasks and Sessions."""

from tests.m2.governance_support import GovernanceCase, policy

try:
    from aetp.acceptance.service import AcceptanceService
except ModuleNotFoundError as exc:
    if not exc.name.startswith("aetp.acceptance"):
        raise
    AcceptanceService = None


def verification_policy(version="gov-verification-1", *, mode="selective", approval="auto", risk="low"):
    value = policy(version)
    value["mode"] = mode
    value["rules"].append({"action": "verification.execute", "risk_level": risk, "approval": approval})
    return value


class VerificationCase(GovernanceCase):
    def setUp(self):
        self.assertIsNotNone(AcceptanceService, "M3-02 AcceptanceService is not implemented")
        super().setUp()
        self.service = AcceptanceService(self.store, owner_id="human-owner", execution=self.execution,
            input_authority=self.input_authority, meter=self.meter, clock=lambda: self.clock_value)
        self.configure(verification_policy())
        self.accept(self.command("project.quality.configure", "p-1", {"grant_ttl_ms": 1000}, actor="human-owner"))
        self.eaccept(self.command("task.create", "qa-task", {
            "title": "Independently check a document", "acceptance_criteria": ["Execute Cases"]}, actor="a-2"))
        self.eaccept(self.command("task.claim", "qa-task", actor="a-2"))
        start = self.command("execution.start", "qa-task", self.qa_fence(), actor="a-2")
        result, self.qa_session = self.execution.start_session(start, authenticated_actor_id="a-2")
        self.assertEqual(result.status, "accepted", result.to_dict())
        self.assertIsNotNone(self.qa_session)

    def qa_fence(self):
        task = self.state()["task:qa-task"]
        result = {"binding_id": task["current_binding_id"], "lease_epoch": task["lease_epoch"]}
        session = getattr(self, "qa_session", None)
        if session:
            result["session_id"] = session.id
        return result

    def capture(self, content='{"scope":"local","recovery":true}', *, identifier="doc-1", trusted=True):
        approval_id = f"write-{identifier}"
        self.request_approval(approval_id, trusted=trusted, arguments=self.document_arguments(content))
        if not trusted:
            self.accept(self.grant(approval_id))
        action = self.request_document(approval_id, content)
        action = self.execution.dispatch("p-1", action["id"], session=self.session)
        self.assertEqual(action["status"], "completed")
        command = self.command("artifact.capture", identifier, {"source_action_id": action["id"], **self.fence()})
        receipt = self.input_authority.issue(command, exposure="internal")
        result = self.service.handle(command, authenticated_actor_id="a-1", session=self.session, input_receipt=receipt)
        self.assertEqual(result.status, "accepted", result.to_dict())
        return self.state()[f"artifact:{identifier}"]

    def verification_command(self, identifier="v-1", *, artifact_id="doc-1", **changes):
        artifact = self.state()[f"artifact:{artifact_id}"]
        body = {"artifact_id": artifact_id, "artifact_digest": artifact["content_digest"],
                "exec_task_id": "qa-task", **self.qa_fence(),
                "cases": [{"criterion": "Scope", "path": ["scope"], "equals": "local"},
                          {"criterion": "Recovery", "path": ["recovery"], "equals": True}]}
        body.update(changes)
        return self.command("verification.request", identifier, body, actor="a-2")

    def request_verification(self, identifier="v-1", **changes):
        command = self.verification_command(identifier, **changes)
        receipt = self.input_authority.issue(command, exposure="internal")
        result = self.service.handle(command, authenticated_actor_id="a-2", session=self.qa_session,
                                     input_receipt=receipt)
        self.assertEqual(result.status, "accepted", result.to_dict())
        return self.state()[f"verification:{identifier}"]

    def verification(self, identifier="v-1"):
        return self.state()[f"verification:{identifier}"]
