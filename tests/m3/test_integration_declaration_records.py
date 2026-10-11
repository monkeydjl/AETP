"""Deterministic declaration records, not live ingress/transaction acceptance."""

import copy
from dataclasses import asdict, replace

from aetp.collaboration.policy import digest_value
from aetp.domain.models import Command, ModelValidationError
from aetp.governance.trust import InputAuthority
from tests.m3.integration_record_support import RecordCase


class InitialDeclarationTests(RecordCase):
    def test_first_declaration_is_one_detached_project_only_effect(self):
        command = self.command()
        effects = self.result(command)
        self.assertEqual(len(effects), 1)
        self.assertEqual(effects[0][:3], ("project.integration_declared", "project", "p-1"))
        record = effects[0][3]
        old = self.project()
        self.assertEqual(record["revision"], old["revision"] + 1)
        self.assertEqual(record["observed_at_ms"], self.at)
        self.assertEqual({k:v for k,v in record.items() if k not in {"revision", "observed_at_ms", "integration_contract"}},
                         {k:v for k,v in old.items() if k not in {"revision", "observed_at_ms"}})
        self.assertEqual(record["integration_contract"]["schema"], "aetp-integration-contract-1")
        self.assertEqual(record["integration_contract"]["tasks"]["t-1"]["current_version"], 1)
        record["governance"]["owner_id"] = "changed-result"
        self.assertEqual(self.project(), old)
        self.assertEqual(old["governance"]["owner_id"], "human-owner")

    def test_version_pins_all_payload_authority_and_execution_facts(self):
        command = self.command()
        record = self.version(self.result(command)[0][3])
        task, project = self.task(), self.project()
        expected = {**command.payload, "declared_by": command.actor_id, "command_id": command.id,
                    "observed_at_ms": self.at, "project_revision": project["revision"], "task_revision": task["revision"],
                    **{k:task[k] for k in ("criteria_digest", "owner_id", "current_binding_id", "lease_epoch", "workspace_provider_id")},
                    "source": {**self.context(command)["input_proof"], "untrusted_input": False}}
        for key in ("governance", "task_quality_policy"):
            h = project[key]
            expected[key] = {"version": h["current_version"], "content_digest": h["versions"][h["current_version"]]["content_digest"]}
        expected["governance"]["owner_id"] = "human-owner"
        self.assertEqual(record, {**expected, "content_digest": digest_value(expected)})
        record["target"]["source"]["ref"] = "refs/heads/changed"
        self.assertNotEqual(record["target"], command.payload["target"])

    def test_nonowners_and_agent_impersonating_owner_are_denied(self):
        for actor in ("a-1", "a-2", "human-peer", "bootstrap", "old-owner"):
            with self.subTest(actor=actor):
                self.reject("PERMISSION_DENIED", self.command(actor_id=actor))
        self.state["agent:human-owner"] = copy.deepcopy(self.state["agent:a-1"])
        self.reject("PERMISSION_DENIED")

    def test_current_owner_must_retain_human_owner_role_and_type(self):
        for subject in ({"type": "human", "roles": ["human_collaborator"]},
                        {"type": "agent", "roles": ["agent_reviewer"]}):
            with self.subTest(subject=subject):
                g = self.project()["governance"]
                g["versions"][g["current_version"]]["policy"]["subjects"]["human-owner"] = subject
                self.rehash_policies()
                self.reject("PERMISSION_DENIED")

    def test_missing_unknown_or_marked_source_is_unverified(self):
        command = self.command()
        self.reject("SOURCE_UNVERIFIED", command, context={"channel": "agent"})
        for exposure in ("unknown", "untrusted"):
            for ancestor in (False, True):
                context = self.context(command)
                if ancestor:
                    context["input_proof"]["sources"][0]["exposure"] = exposure
                else:
                    context["input_proof"]["exposure"] = exposure
                with self.subTest(exposure=exposure, ancestor=ancestor):
                    self.reject("SOURCE_UNVERIFIED", command, context=context)

    def test_mismatched_or_malformed_proof_is_invalid(self):
        command = self.command()
        for key, value in (("command_digest", "0"*64), ("actor_id", "a-1"), ("source_id", "other-authority"),
                           ("receipt_id", None), ("exposure", []), ("sources", {})):
            context = self.context(command)
            context["input_proof"][key] = value
            with self.subTest(key=key):
                self.reject("INPUT_CONTEXT_INVALID", command, context=context)
        context = self.context(command)
        context["input_proof"]["sources"][0]["exposure"] = {}
        self.reject("INPUT_CONTEXT_INVALID", command, context=context)

    def test_proof_cannot_be_transplanted_to_changed_payload(self):
        original = self.command()
        changed = replace(original, payload={**original.payload, "reason": "changed"})
        self.reject("INPUT_CONTEXT_INVALID", changed, context=self.context(original))

    def test_context_rejects_extra_authority_or_wrong_channel(self):
        command = self.command()
        self.reject("INVALID_PAYLOAD", command, context={**self.context(command), "owner_id": "human-owner"})
        for channel in ("system", "replay", [], None):
            self.reject("ENFORCEMENT_UNAVAILABLE", command, context={**self.context(command), "channel": channel})
        self.reject("ENFORCEMENT_UNAVAILABLE", replace(command, type="git.merge"))

    def test_only_current_full_project_and_task_revisions_are_accepted(self):
        command = self.command()
        for value in (None, True, 0, command.expected_revision-1, command.expected_revision+1):
            with self.subTest(project_revision=value):
                self.reject("REVISION_CONFLICT", replace(command, expected_revision=value))
        for value in (0, self.task()["revision"]-1, self.task()["revision"]+1):
            self.reject("REVISION_CONFLICT", replace(command, payload={**command.payload, "expected_task_revision": value}))
        self.reject("INVALID_PAYLOAD", replace(command, payload={**command.payload, "expected_task_revision": True}))

    def test_project_and_task_address_must_match(self):
        command = self.command()
        self.reject("INVALID_TARGET", replace(command, target_id="p-other"))
        self.reject("INVALID_TARGET", replace(command, payload={**command.payload, "task_id": "missing"}))
        self.task()["project_id"] = "p-other"
        self.reject("INVALID_TARGET", command)
        del self.state["project:p-1"]
        self.reject("INVALID_TARGET", command, context={"channel": "agent"})

    def test_project_pause_terminal_candidate_and_policy_boundaries(self):
        for status, code in (("paused", "PROJECT_PAUSED"), ("completed", "PROJECT_INACTIVE"), ("cancelled", "PROJECT_INACTIVE")):
            self.project()["status"] = status
            self.reject(code)
        self.project()["status"] = "planning"
        self.project()["planning"] = {"mode": "candidate_only"}
        self.reject("PLANNING_NOT_ACTIVE")
        del self.project()["planning"]
        self.project()["execution_policy_version"] = "unsupported"
        self.reject("POLICY_UNAVAILABLE")

    def test_supported_task_stages_do_not_change_task(self):
        for stage in ("assigned", "in_progress", "ready_for_review", "in_review", "verified", "rejected", "blocked"):
            with self.subTest(stage=stage):
                self.task()["status"] = stage
                self.result()
        for stage in ("pending", "failed", "completed", "cancelled", "ready_for_integration", "integrating", "integrated", "system_verified"):
            with self.subTest(stage=stage):
                self.task()["status"] = stage
                self.reject("INVALID_TRANSITION")

    def test_durable_binding_owner_epoch_and_workspace_must_agree(self):
        original = copy.deepcopy(self.task())
        for field, value in (("agent_id", "a-2"), ("id", "wrong"), ("lease_epoch", 2), ("lease_epoch", True)):
            self.state["task:t-1"] = copy.deepcopy(original)
            binding = self.task()["bindings"][self.task()["current_binding_id"]]
            binding[field] = value
            with self.subTest(field=field):
                self.reject("STALE_EXECUTION")
        self.state["task:t-1"] = copy.deepcopy(original)
        self.task()["current_binding_id"] = "missing"
        self.reject("STALE_EXECUTION")
        self.state["task:t-1"] = copy.deepcopy(original)
        self.task()["workspace_provider_id"] = "wrong"
        self.reject("WORKSPACE_MISMATCH")
        self.state["task:t-1"] = copy.deepcopy(original)
        self.task()["bindings"][self.task()["current_binding_id"]]["workspace_provider_id"] = "wrong"
        self.reject("WORKSPACE_MISMATCH")

    def test_configuration_does_not_require_live_author_lease_or_session(self):
        binding = self.task()["bindings"][self.task()["current_binding_id"]]
        binding["session"] = None
        binding["status"] = "stopped"
        self.task()["lease"]["revoked"] = True
        self.task()["lease"]["expires_at_governance_ms"] = 0
        self.task()["status"] = "blocked"
        self.result(at=400000)
        self.task()["lease"] = None
        self.result(at=400000)

    def test_missing_owner_or_fixed_task_policies_are_rejected(self):
        self.task()["owner_id"] = None
        self.reject("INVALID_TARGET")
        self.task()["owner_id"] = "a-1"
        for field in ("execution_policy_version", "policy_version"):
            old = self.task()[field]
            self.task()[field] = "unsupported"
            self.reject("POLICY_UNAVAILABLE")
            self.task()[field] = old

    def test_only_current_policy_exemption_blocks_declaration(self):
        self.state = copy.deepcopy(self.exempt_snapshot)
        self.reject("INTEGRATION_SCOPE_CONFLICT")
        self.state = copy.deepcopy(self.snapshot)
        self.task()["quality_cycle"] = {"policy": "old-exempt", "integration_exempted": True}
        self.result()
        del self.project()["task_quality_policy"]
        self.reject("TASK_QUALITY_POLICY_REQUIRED")

    def test_policy_digests_cannot_pin_tampered_contents(self):
        for key in ("governance", "task_quality_policy"):
            self.state = copy.deepcopy(self.snapshot)
            history = self.project()[key]
            history["versions"][history["current_version"]]["content_digest"] = "sha256:" + "0"*64
            self.reject("INVALID_REFERENCE")

    def test_timestamp_is_explicit_monotonic_and_strict(self):
        self.reject("CLOCK_REGRESSION", at=self.at-1)
        for at in (True, None, -1):
            if at is not None:
                self.reject("INVALID_PAYLOAD", at=at)
        self.result(at=self.at+1)

    def test_error_priority_revision_before_authority_before_payload(self):
        command = self.command(actor_id="a-1", payload={})
        self.reject("REVISION_CONFLICT", replace(command, expected_revision=0))
        self.reject("PERMISSION_DENIED", command)
        command = self.command(payload={})
        self.reject("SOURCE_UNVERIFIED", command, context={"channel": "agent"})
        self.reject("INVALID_PAYLOAD", command)

    def test_registered_data_does_not_authenticate_a_draft_or_history(self):
        command = self.command()
        for kind in ("project.integration.declare", "git.merge"):
            self.assertEqual(Command(**{**asdict(command), "type": kind}).type, kind)
        with self.assertRaises(TypeError):
            InputAuthority("fixture-only").issue(command, exposure="trusted")


class DeclarationHistoryTests(RecordCase):
    def append(self, *, task_id="t-1", version=1, **changes):
        command = self.command(task_id=task_id, version=version, **changes)
        record = self.result(command)[0][3]
        # Detached unit-test simulation only. No Event/Projection publication.
        self.state["project:p-1"] = record
        return record

    def test_supersession_appends_one_version_without_rewriting_history(self):
        first = copy.deepcopy(self.append())
        second_command = self.command(version=2)
        second_command.payload["reason"] = "New target intent"
        second_command.payload["target"]["target"]["expected_commit"] = "3" * 40
        second = self.result(second_command)[0][3]
        self.assertIn("1", second["integration_contract"]["tasks"]["t-1"]["versions"])
        self.assertEqual(self.version(second), self.version(first))
        entry = second["integration_contract"]["tasks"]["t-1"]
        self.assertEqual(entry["current_version"], 2)
        self.assertEqual(set(entry["versions"]), {"1", "2"})
        self.assertEqual(entry["versions"]["2"]["supersedes_version"], 1)
        self.assertEqual(entry["versions"]["2"]["project_revision"], first["revision"])
        self.assertEqual(entry["versions"]["2"]["task_revision"], self.task()["revision"])
        self.version(second)["target"]["source"]["ref"] = "refs/heads/mutated"
        self.assertEqual(self.project(), first)

    def test_first_version_must_be_one(self):
        self.reject("INTEGRATION_DECLARATION_VERSION_CONFLICT", self.command(version=2))

    def test_same_and_skipped_version_never_replace_current(self):
        self.append()
        self.reject("INTEGRATION_DECLARATION_VERSION_CONFLICT", self.command(version=1))
        self.reject("INTEGRATION_DECLARATION_VERSION_CONFLICT", self.command(version=3))
        second = self.command(version=2)
        self.reject("INVALID_PAYLOAD", replace(second, payload={**second.payload, "supersedes_version": None}))

    def test_sixty_four_versions_are_retained_then_limit_rejects(self):
        for version in range(1, 65):
            self.append(version=version)
        entry = self.project()["integration_contract"]["tasks"]["t-1"]
        self.assertEqual(entry["current_version"], 64)
        self.assertEqual(set(entry["versions"]), {str(v) for v in range(1, 65)})
        self.reject("INTEGRATION_DECLARATION_LIMIT", self.command(version=64))

    def test_task_cap_preserves_other_histories_and_allows_existing_task_update(self):
        first = copy.deepcopy(self.append())
        for index in range(2, 65):
            task_id = f"t-{index}"
            self.state[f"task:{task_id}"] = {**copy.deepcopy(self.task()), "id": task_id}
            self.append(task_id=task_id)
        before = copy.deepcopy(self.project()["integration_contract"]["tasks"])
        self.assertEqual(len(before), 64)
        self.assertEqual(before["t-1"]["versions"]["1"], self.version(first))
        after = self.append(version=2)["integration_contract"]["tasks"]
        self.assertEqual({k:v for k,v in after.items() if k != "t-1"}, {k:v for k,v in before.items() if k != "t-1"})
        self.state["task:t-65"] = {**copy.deepcopy(self.task()), "id": "t-65"}
        self.reject("INTEGRATION_DECLARATION_LIMIT", self.command(task_id="t-65"))

    def test_history_schema_shape_and_entry_fields_are_validated(self):
        self.append()
        original = copy.deepcopy(self.project())
        bad_histories = [None, [], {}, {"schema": "unknown", "tasks": {}},
                         {"schema": "aetp-integration-contract-1", "tasks": []},
                         {**original["integration_contract"], "drop_history": True}]
        for history in bad_histories:
            self.project()["integration_contract"] = history
            with self.subTest(history=history):
                self.reject("INVALID_REFERENCE", self.command(version=2))
        for entry in (None, {}, {"current_version": 1, "versions": {}},
                      {"current_version": 1, "versions": {"1": None}}):
            self.state["project:p-1"] = copy.deepcopy(original)
            self.project()["integration_contract"]["tasks"]["t-1"] = entry
            with self.subTest(entry=entry):
                self.reject("INVALID_REFERENCE", self.command(version=2))

    def test_history_versions_are_contiguous_canonical_and_pointer_is_strict(self):
        self.append()
        original = copy.deepcopy(self.project())
        for key in ("01", "0", "2", 1):
            self.state["project:p-1"] = copy.deepcopy(original)
            entry = self.project()["integration_contract"]["tasks"]["t-1"]
            entry["versions"][key] = entry["versions"].pop("1")
            with self.subTest(key=key):
                self.reject("INVALID_REFERENCE", self.command(version=2))
        for pointer in (True, "1", 0, 2, 65):
            self.state["project:p-1"] = copy.deepcopy(original)
            self.project()["integration_contract"]["tasks"]["t-1"]["current_version"] = pointer
            self.reject("INVALID_REFERENCE", self.command(version=2))

    def test_history_digest_and_semantic_version_links_cannot_be_rewritten(self):
        self.append()
        original = copy.deepcopy(self.project())
        cases = [("reason", "tampered", False), ("content_digest", "sha256:"+"0"*64, False),
                 ("task_id", "other", True), ("version", True, True),
                 ("supersedes_version", 0, True), ("requirement", "exempt", True)]
        for key, value, rehash in cases:
            self.state["project:p-1"] = copy.deepcopy(original)
            version = self.version(self.project())
            version[key] = value
            if rehash:
                version["content_digest"] = digest_value({k:v for k,v in version.items() if k != "content_digest"})
            with self.subTest(key=key):
                self.reject("INVALID_REFERENCE", self.command(version=2))

    def test_changed_owner_policy_or_execution_only_pins_new_version(self):
        first = copy.deepcopy(self.append())
        g = self.project()["governance"]
        g["owner_id"] = "human-peer"
        old_policy = copy.deepcopy(g["versions"][g["current_version"]])
        old_policy["policy"]["version"] = "gov-new-owner"
        old_policy["policy"]["subjects"]["human-owner"]["roles"] = ["human_collaborator"]
        old_policy["policy"]["subjects"]["human-peer"]["roles"] = ["human_owner"]
        g["versions"]["gov-new-owner"] = old_policy
        g["current_version"] = "gov-new-owner"
        q = self.project()["task_quality_policy"]
        q["versions"]["new-quality"] = copy.deepcopy(q["versions"][q["current_version"]])
        q["versions"]["new-quality"]["policy"]["version"] = "new-quality"
        q["current_version"] = "new-quality"
        self.rehash_policies()
        self.task()["owner_id"] = "a-2"
        self.task()["lease_epoch"] = 2
        binding = self.task()["bindings"][self.task()["current_binding_id"]]
        binding["agent_id"] = "a-2"
        binding["lease_epoch"] = 2
        self.task()["revision"] += 1
        self.project()["revision"] += 1
        self.reject("PERMISSION_DENIED", self.command(version=2))
        second = self.append(version=2, actor_id="human-peer")
        self.assertIn("1", second["integration_contract"]["tasks"]["t-1"]["versions"])
        self.assertEqual(self.version(second), self.version(first))
        new = self.version(second, version=2)
        self.assertEqual(new["requirement"], "required")
        self.assertEqual(new["declared_by"], "human-peer")
        self.assertEqual(new["lease_epoch"], 2)
        self.assertEqual(new["governance"]["version"], "gov-new-owner")
        self.assertEqual(new["task_quality_policy"]["version"], "new-quality")

    def test_current_exemption_also_blocks_supersession(self):
        self.append()
        q = self.project()["task_quality_policy"]
        q["versions"][q["current_version"]]["policy"]["integration_exemptions"]["t-1"] = {"reason": "stale"}
        self.rehash_policies()
        self.reject("INTEGRATION_SCOPE_CONFLICT", self.command(version=2))

    def test_evaluation_is_json_roundtrip_deterministic_without_io_or_authority(self):
        from contextlib import ExitStack
        import json
        from unittest.mock import patch
        from tests.m3.integration_record_support import evaluate
        self.append()
        command = self.command(version=2)
        context = self.context(command)
        expected = self.result(command)
        state = json.loads(json.dumps(self.state))
        context = json.loads(json.dumps(context))
        guards = ("builtins.open", "pathlib.Path.open", "pathlib.Path.resolve", "subprocess.Popen", "os.system",
                  "socket.socket", "time.time", "sqlite3.connect",
                  "aetp.governance.trust.InputAuthority.issue", "aetp.governance.trust.InputAuthority.verify")
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch(name, side_effect=AssertionError(name))) for name in guards]
            actual = evaluate(command, state, self.at, context)
            self.assertEqual(actual, expected)
            for guard in mocks:
                guard.assert_not_called()
        self.assertEqual(state, self.state)
        self.assertEqual(context, self.context(command))
