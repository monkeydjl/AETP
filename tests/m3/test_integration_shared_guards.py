"""Guard unit tests over prospective records, NOT an accepted declaration stream."""

import copy
from contextlib import ExitStack
from types import SimpleNamespace
from unittest.mock import patch

from aetp.collaboration.policy import PolicyViolation, digest_value
from aetp.domain.models import Command, ModelValidationError
from tests.m3.integration_record_support import RecordCase

try:
    from aetp.integration import guards
    from aetp.integration.history import validated_history
except ImportError:
    guards = None
    validated_history = None


def request(kind="task.complete", *, target="t-1", payload=None):
    return Command(id="guard-command", project_id="p-1", actor_id="human-owner", type=kind,
        target_id=target, payload={} if payload is None else payload, expected_revision=0,
        idempotency_key="guard-key", correlation_id="guard-correlation")


def configuration(*ids):
    return {"version": "next-quality", "max_evidence_age_ms": 60000,
        "integration_exemptions": [{"task_id": i, "scope": "standalone_fixed_json_document",
            "reason": "Explicit document scope"} for i in ids]}


def fact(kind="task.completed", aggregate="task", identifier="t-1"):
    return SimpleNamespace(type=kind, aggregate_type=aggregate, aggregate_id=identifier,
                           project_id="p-1", payload={})


class SharedGuardTests(RecordCase):
    def setUp(self):
        super().setUp()
        self.assertIsNotNone(guards, "Integration shared guard API is not implemented")
        self.assertIsNotNone(validated_history, "Integration history reader is not implemented")
        self.state["project:p-1"] = self.result()[0][3]

    def error(self, command, state=None):
        state = self.state if state is None else state
        before = copy.deepcopy(state)
        try:
            return guards.command_error(command, state)
        finally:
            self.assertEqual(state, before)

    def test_absent_registry_preserves_legacy_payload_handling(self):
        state = copy.deepcopy(self.snapshot)
        self.assertIsNone(validated_history(state["project:p-1"]))
        self.assertIsNone(self.error(request(), state))
        self.assertIsNone(self.error(request("project.task_quality.configure", target="p-1",
                                            payload={"malformed": True}), state))
        self.assertNotIn("integration_contract", state["project:p-1"])

    def test_unrelated_commands_do_not_acquire_an_integration_gate(self):
        self.project()["integration_contract"] = None
        self.assertIsNone(self.error(request("task.claim")))

    def test_both_completion_commands_refuse_required_without_metadata(self):
        for kind in ("task.complete", "task.quality.complete"):
            with self.subTest(kind=kind):
                self.assertEqual(self.error(request(kind)), "INTEGRATION_REQUIRED")

    def test_other_task_and_other_project_are_not_marked_required(self):
        self.assertIsNone(self.error(request(target="t-other")))
        self.state["project:p-2"] = self.state.pop("project:p-1")
        self.assertIsNone(self.error(request()))

    def test_stale_owner_epoch_policy_and_criteria_do_not_remove_requirement(self):
        self.task().update(owner_id="new-owner", lease_epoch=100, criteria_digest="changed",
                           current_binding_id="new-binding", status="blocked")
        self.project()["governance"]["owner_id"] = "new-human"
        self.project().pop("task_quality_policy")
        self.assertEqual(self.error(request()), "INTEGRATION_REQUIRED")

    def test_configure_can_remove_exemptions_or_add_another_task(self):
        for payload in (configuration(), configuration("t-other")):
            self.assertIsNone(self.error(request("project.task_quality.configure", target="p-1", payload=payload)))

    def test_configure_cannot_restore_required_exemption(self):
        self.assertEqual(self.error(request("project.task_quality.configure", target="p-1",
            payload=configuration("t-other", "t-1"))), "INTEGRATION_SCOPE_CONFLICT")

    def test_full_payload_is_validated_before_any_conflict(self):
        variants = []
        for key, value in (("max_evidence_age_ms", True), ("version", " "),
                           ("integration_exemptions", {}), ("extra", "unexpected")):
            value_payload = configuration("t-1")
            value_payload[key] = value
            variants.append(value_payload)
        later_bad = configuration("t-1", "t-other")
        later_bad["integration_exemptions"][1]["reason"] = " "
        variants.extend((later_bad, {"integration_exemptions": []}))
        for payload in variants:
            with self.subTest(payload=payload):
                self.assertEqual(self.error(request("project.task_quality.configure", target="p-1", payload=payload)),
                                 "INVALID_PAYLOAD")

    def test_duplicate_and_unsupported_scope_keep_typed_errors(self):
        self.assertEqual(self.error(request("project.task_quality.configure", target="p-1",
            payload=configuration("t-1", "t-1"))), "INVALID_REFERENCE")
        payload = configuration("t-1")
        payload["integration_exemptions"][0]["scope"] = "any-code"
        self.assertEqual(self.error(request("project.task_quality.configure", target="p-1", payload=payload)),
                         "INTEGRATION_SCOPE_UNSUPPORTED")

    def test_malformed_present_registry_is_not_treated_as_absent(self):
        for value in (None, {}, [], {"schema": "future", "tasks": {}},
                      {"schema": "aetp-integration-contract-1", "tasks": {}}):
            with self.subTest(value=value):
                self.project()["integration_contract"] = value
                self.assertEqual(self.error(request()), "INVALID_REFERENCE")
                with self.assertRaises(ModelValidationError):
                    guards.validate_fact(fact(), self.state)

    def test_history_reader_returns_detached_validated_record(self):
        result = validated_history(self.project())
        self.assertEqual(result, self.project()["integration_contract"])
        result["tasks"].clear()
        self.assertIn("t-1", self.project()["integration_contract"]["tasks"])

    def test_history_rejects_gaps_pointer_bool_digest_and_optional_requirement(self):
        original = copy.deepcopy(self.project()["integration_contract"])
        for change in (lambda x: x["tasks"]["t-1"].update(current_version=True),
                       lambda x: x["tasks"]["t-1"]["versions"].update({"01": {}}),
                       lambda x: x["tasks"]["t-1"]["versions"]["1"].update(reason="changed"),
                       lambda x: x["tasks"]["t-1"]["versions"]["1"].update(requirement="optional")):
            value = copy.deepcopy(original)
            change(value)
            self.project()["integration_contract"] = value
            with self.assertRaises(PolicyViolation) as caught:
                validated_history(self.project())
            self.assertEqual(caught.exception.code, "INVALID_REFERENCE")

    def test_fact_guard_blocks_required_exemption_and_completion_without_schema(self):
        for kind in ("task.integration_exempted", "task.completed"):
            with self.subTest(kind=kind), self.assertRaises(ModelValidationError):
                guards.validate_fact(fact(kind), self.state)
        guards.validate_fact(fact(identifier="t-other"), self.state)
        guards.validate_fact(fact("task.blocked"), self.state)

    def test_post_guard_rejects_completed_record_disguised_as_another_event(self):
        updated = {**self.task(), "status": "completed"}
        with self.assertRaises(ModelValidationError):
            guards.validate_record(fact("task.blocked"), self.task(), updated, self.state)

    def test_unimplemented_integration_states_rejected_even_without_registry(self):
        for status in ("ready_for_integration", "integrating", "integrated", "system_verified"):
            with self.subTest(status=status), self.assertRaises(ModelValidationError):
                guards.validate_record(fact("task.blocked"), self.task(), {**self.task(), "status": status}, self.snapshot)
        guards.validate_record(fact(), self.task(), {**self.task(), "status": "completed"}, self.snapshot)

    def test_unrelated_project_update_preserves_exact_registry(self):
        updated = copy.deepcopy(self.project())
        updated.update(revision=updated["revision"] + 1, status="paused")
        guards.validate_record(fact("project.paused", "project", "p-1"), self.project(), updated, self.state)

    def test_project_cannot_drop_replace_or_reseal_declaration(self):
        for how in ("drop", "null", "empty", "bool", "reason"):
            updated = copy.deepcopy(self.project())
            if how == "drop":
                updated.pop("integration_contract")
            elif how == "null":
                updated["integration_contract"] = None
            elif how == "empty":
                updated["integration_contract"]["tasks"] = {}
            elif how == "bool":
                updated["integration_contract"]["tasks"]["t-1"]["current_version"] = True
            else:
                version = updated["integration_contract"]["tasks"]["t-1"]["versions"]["1"]
                version["reason"] = "new"
                version["content_digest"] = digest_value({k: v for k, v in version.items() if k != "content_digest"})
            with self.subTest(how=how), self.assertRaises(ModelValidationError):
                guards.validate_record(fact("project.paused", "project", "p-1"), self.project(), updated, self.state)

    def test_new_registry_and_self_claimed_declaration_event_stay_closed(self):
        for kind in ("project.paused", "project.integration_declared"):
            with self.subTest(kind=kind), self.assertRaises(ModelValidationError):
                guards.validate_record(fact(kind, "project", "p-1"), self.snapshot["project:p-1"],
                                       self.project(), self.snapshot)

    def test_project_post_guard_checks_current_not_old_exemption_policy(self):
        # The real prior policy contains an old exemption. Its superseding policy does not.
        event = fact("project.task_quality_configured", "project", "p-1")
        guards.validate_record(event, self.project(), self.project(), self.state)
        updated = copy.deepcopy(self.project())
        updated["task_quality_policy"]["current_version"] = "task-quality-1"
        with self.assertRaises(ModelValidationError):
            guards.validate_record(event, self.project(), updated, self.state)

    def test_guard_computation_is_pure_and_does_not_observe_live_authority(self):
        before = copy.deepcopy(self.state)
        paths = ("builtins.open", "pathlib.Path.open", "subprocess.Popen", "socket.socket", "time.time",
                 "sqlite3.connect", "aetp.governance.trust.InputAuthority.issue", "aetp.governance.trust.InputAuthority.verify")
        with ExitStack() as stack:
            blocked = [stack.enter_context(patch(path, side_effect=AssertionError(path))) for path in paths]
            self.assertEqual(self.error(request()), "INTEGRATION_REQUIRED")
            guards.validate_record(fact("project.paused", "project", "p-1"), self.project(), self.project(), self.state)
            for call in blocked:
                call.assert_not_called()
        self.assertEqual(self.state, before)
