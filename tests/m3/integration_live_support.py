"""Real registered Commands and authentic fixture ingress, never DraftCommand."""
from tests.m3.quality_support import QualityCase
from tests.m3.test_integration_contract_inputs import target_fixture

try:
    from aetp.integration.service import IntegrationContractService
except ModuleNotFoundError as exc:
    if exc.name != "aetp.integration.service":
        raise
    IntegrationContractService = None

class IntegrationCase(QualityCase):
    def setUp(self):
        self.assertIsNotNone(IntegrationContractService, "Real Integration declaration service is missing")
        super().setUp()
        self.configure_task_quality(version="integration-unexempt", exempt=False)
        self.service = IntegrationContractService(self.store, owner_id="human-owner",
            execution=self.execution, input_authority=self.input_authority,
            meter=self.meter, clock=lambda: self.clock_value)

    def declaration(self, *, version=1, actor="human-owner", **changes):
        payload = {"task_id": "t-1", "expected_task_revision": self.task()["revision"],
            "version": version, "supersedes_version": version - 1 if version > 1 else None,
            "requirement": "required", "target": target_fixture(), "reason": "Human requested integration"}
        payload.update(changes)
        return self.command("project.integration.declare", "p-1", payload, actor=actor)

    def submit(self, command, *, exposure="internal", service=None):
        receipt = self.input_authority.issue(command, exposure=exposure)
        return (service or self.service).handle(command, authenticated_actor_id=command.actor_id, input_receipt=receipt)

    def declare(self, **changes):
        command = self.declaration(**changes)
        result = self.submit(command)
        self.assertEqual(result.status, "accepted", result.to_dict())
        return command, result

    def merge(self, **changes):
        history = self.state()["project:p-1"].get("integration_contract", {}).get("tasks", {}).get("t-1")
        version = history["current_version"] if history else 1
        digest = history["versions"][str(version)]["content_digest"] if history else "sha256:" + "0" * 64
        payload = {"declaration_version": version, "declaration_digest": digest}
        payload.update(changes)
        return self.command("git.merge", "t-1", payload, revision=self.task()["revision"])
