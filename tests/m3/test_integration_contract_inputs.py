"""Input-only Integration contracts: valid data never grants execution authority."""

import copy
import importlib
import unittest

from aetp.collaboration.policy import PolicyViolation


def target_fixture():
    return {
        "provider_id": "future_git_provider",
        "repository_id": "project_repository",
        "object_format": "sha1",
        "source": {"ref": "refs/heads/agent/task_042", "commit": "1" * 40},
        "target": {"ref": "refs/heads/main", "expected_commit": "2" * 40},
    }


class InputCase(unittest.TestCase):
    def validator(self, name):
        try:
            module = importlib.import_module("aetp.integration.validation")
        except ModuleNotFoundError as exc:
            if exc.name not in {"aetp.integration", "aetp.integration.validation"}:
                raise
            module = None
        self.assertIsNotNone(module, "M3-02 Integration input validation is missing")
        result = getattr(module, name, None)
        self.assertTrue(callable(result), f"M3-02 {name} is missing")
        return result

    def rejects(self, validate, value):
        before = copy.deepcopy(value)
        with self.assertRaises(PolicyViolation) as raised:
            validate(value)
        self.assertEqual(raised.exception.code, "INVALID_PAYLOAD")
        self.assertEqual(value, before)


class TargetInputTests(InputCase):
    def setUp(self):
        self.validate = self.validator("validate_target")

    def test_full_sha1_and_sha256_intents_preserve_exact_data(self):
        # Catches accepting only one format or rewriting opaque identifiers/refs.
        for fmt, width in (("sha1", 40), ("sha256", 64)):
            value = target_fixture()
            value["object_format"] = fmt
            value["source"]["commit"] = "a" * width
            value["target"]["expected_commit"] = "b" * width
            with self.subTest(format=fmt):
                self.assertEqual(self.validate(value), value)

    def test_returned_target_does_not_alias_caller_mappings(self):
        value = target_fixture()
        before = copy.deepcopy(value)
        result = self.validate(value)
        result["source"]["commit"] = "f" * 40
        result["target"]["ref"] = "refs/heads/elsewhere"
        result["provider_id"] = "another"
        self.assertEqual(value, before)
        value["source"]["ref"] = "refs/heads/later"
        self.assertEqual(result["source"]["ref"], "refs/heads/agent/task_042")

    def test_every_object_level_requires_exact_fields(self):
        for path in ((), ("source",), ("target",)):
            sample = target_fixture()
            node = sample if not path else sample[path[0]]
            for field in tuple(node):
                value = target_fixture()
                changed = value if not path else value[path[0]]
                del changed[field]
                with self.subTest(path=path, missing=field):
                    self.rejects(self.validate, value)
            for field in ("authority", "result_commit", "verified", "binding", "status"):
                value = target_fixture()
                changed = value if not path else value[path[0]]
                changed[field] = "caller-controlled"
                with self.subTest(path=path, extra=field):
                    self.rejects(self.validate, value)

    def test_wrong_containers_and_unhashable_formats_are_typed_rejections(self):
        for bad in (None, [], (), "target", 1, True):
            with self.subTest(top=bad):
                self.rejects(self.validate, bad)
            for key in ("source", "target", "object_format"):
                value = target_fixture()
                value[key] = bad
                with self.subTest(key=key, value=bad):
                    self.rejects(self.validate, value)
        for bad in ({}, "SHA1", "sha512"):
            value = target_fixture()
            value["object_format"] = bad
            self.rejects(self.validate, value)

    def test_identifier_limits_are_inclusive(self):
        for key in ("provider_id", "repository_id"):
            for good in ("a", "0", "A_z-9", "a" * 128):
                value = target_fixture()
                value[key] = good
                self.assertEqual(self.validate(value)[key], good)
            value[key] = "a" * 129
            self.rejects(self.validate, value)

    def test_identifiers_are_opaque_ascii_not_paths_urls_or_shell(self):
        fixtures = ("", "_id", "-id", "has.dot", "../repo", "D:/repo", "https://host/repo",
                    "hello world", "id\n", " id", "id ", "仓库", "$(whoami)", None, 7, [], {})
        for key in ("provider_id", "repository_id"):
            for bad in fixtures:
                value = target_fixture()
                value[key] = bad
                with self.subTest(key=key, value=bad):
                    self.rejects(self.validate, value)

    def test_ref_length_boundary_and_allowed_components(self):
        for key in ("source", "target"):
            for good in ("refs/heads/a", "refs/heads/_agent/Task_042-2", "refs/heads/" + "a" * 244):
                value = target_fixture()
                value[key]["ref"] = good
                self.assertEqual(self.validate(value)[key]["ref"], good)
            value[key]["ref"] = "refs/heads/" + "a" * 245
            self.rejects(self.validate, value)

    def test_ref_traversal_metacharacters_unicode_and_nonbranch_refs_rejected(self):
        fixtures = ("", "main", "refs/tags/v1", "refs/heads/", "refs/heads//a", "refs/heads/a/",
                    "refs/heads/../a", "refs/heads/a.lock", "refs/heads/a.b", "refs/heads/-a",
                    "refs/heads/a\\b", "refs/heads/a b", "refs/heads/a;whoami", "refs/heads/a$(x)",
                    "refs/heads/中文", "refs/heads/a\n", "refs/heads/a\x00", None, [], 4)
        for key in ("source", "target"):
            for bad in fixtures:
                value = target_fixture()
                value[key]["ref"] = bad
                with self.subTest(key=key, value=bad):
                    self.rejects(self.validate, value)

    def test_source_and_target_ref_must_differ(self):
        value = target_fixture()
        value["source"]["ref"] = value["target"]["ref"]
        self.rejects(self.validate, value)

    def test_oids_are_full_lowercase_nonzero_and_format_specific(self):
        for fmt, width in (("sha1", 40), ("sha256", 64)):
            for side, field in (("source", "commit"), ("target", "expected_commit")):
                fixtures = ("", "HEAD", "deadbee", "0" * width, "A" * width, "g" * width,
                            "a" * (width - 1), "a" * (width + 1), "b" * (64 if width == 40 else 40),
                            "sha256:" + "a" * 64, "a" * width + "\n", None, True, [], {})
                for bad in fixtures:
                    value = target_fixture()
                    value["object_format"] = fmt
                    value["source"]["commit"] = "1" * width
                    value["target"]["expected_commit"] = "2" * width
                    value[side][field] = bad
                    with self.subTest(format=fmt, side=side, value=bad):
                        self.rejects(self.validate, value)

    def test_nonzero_oid_with_leading_zeroes_is_not_mistaken_for_null_oid(self):
        for fmt, width in (("sha1", 40), ("sha256", 64)):
            value = target_fixture()
            value["object_format"] = fmt
            value["source"]["commit"] = "0" * (width - 1) + "1"
            value["target"]["expected_commit"] = "0" * (width - 1) + "2"
            self.assertEqual(self.validate(value), value)


def declaration_fixture():
    return {"task_id": "task_042", "expected_task_revision": 7, "version": 1,
            "supersedes_version": None, "requirement": "required", "target": target_fixture(),
            "reason": "  需要集成  "}


class DeclarationInputTests(InputCase):
    def setUp(self):
        self.validate = self.validator("validate_declaration_payload")

    def test_initial_and_superseding_payloads_preserve_original_reason(self):
        for version, previous in ((1, None), (2, 1), (64, 63)):
            value = declaration_fixture()
            value.update(version=version, supersedes_version=previous)
            with self.subTest(version=version):
                self.assertEqual(self.validate(value), value)
                self.assertEqual(self.validate(value)["reason"], "  需要集成  ")

    def test_required_payload_fields_cannot_be_omitted_or_extended(self):
        for field in declaration_fixture():
            value = declaration_fixture()
            del value[field]
            with self.subTest(missing=field):
                self.rejects(self.validate, value)
        for field in ("author", "binding", "epoch", "policy_digest", "verified", "result_commit", "authority"):
            value = declaration_fixture()
            value[field] = "caller-controlled"
            with self.subTest(extra=field):
                self.rejects(self.validate, value)
        for value in (None, [], (), "payload", 7, True):
            self.rejects(self.validate, value)

    def test_versions_require_strict_integers_and_contiguous_local_predecessor(self):
        fixtures = ((True, None), (False, None), (1.0, None), ("1", None), (0, None), (65, 64),
                    (None, None), ([], None), (1, 0), (1, 1), (2, None), (2, 0), (2, 2),
                    (3, 1), (2, True), (2, 1.0), (2, "1"), (2, []), (64, 62))
        for version, previous in fixtures:
            value = declaration_fixture()
            value.update(version=version, supersedes_version=previous)
            with self.subTest(version=version, previous=previous):
                self.rejects(self.validate, value)

    def test_task_revision_is_a_bounded_natural_not_a_boolean(self):
        for revision in (0, 1, 2**63 - 1):
            value = declaration_fixture()
            value["expected_task_revision"] = revision
            self.assertEqual(self.validate(value)["expected_task_revision"], revision)
        for revision in (None, True, False, -1, 1.0, "1", [], {}, 2**63):
            value = declaration_fixture()
            value["expected_task_revision"] = revision
            with self.subTest(revision=revision):
                self.rejects(self.validate, value)

    def test_only_required_requirement_is_supported(self):
        for requirement in ("exempt", "optional", "none", "REQUIRED", " required", "required ", None, True, [], {}):
            value = declaration_fixture()
            value["requirement"] = requirement
            with self.subTest(requirement=requirement):
                self.rejects(self.validate, value)

    def test_task_id_uses_existing_unicode_byte_bound_identifier_contract(self):
        for identifier in ("task_042", "任务:42", "a" * 512, "任" * 170):
            value = declaration_fixture()
            value["task_id"] = identifier
            self.assertEqual(self.validate(value)["task_id"], identifier)
        for identifier in ("", " ", " task", "task ", "a" * 513, "任" * 171, "\ud800", None, 1, []):
            value = declaration_fixture()
            value["task_id"] = identifier
            with self.subTest(identifier=repr(identifier)):
                self.rejects(self.validate, value)

    def test_reason_character_limit_accepts_multibyte_text_without_truncating(self):
        for reason in ("x", "中文", "x" * 2048, "理" * 2048, "😀" * 2048, " reason "):
            value = declaration_fixture()
            value["reason"] = reason
            self.assertEqual(self.validate(value)["reason"], reason)

    def test_reason_rejects_blank_overlong_nonstring_and_surrogate_data(self):
        for reason in ("", " ", "\t\n", "x" * 2049, "理" * 2049, "\ud800", "x\udfff", None, True, [], {}):
            value = declaration_fixture()
            value["reason"] = reason
            with self.subTest(reason=repr(reason)[:60]):
                self.rejects(self.validate, value)

    def test_nested_target_rules_are_enforced_and_result_does_not_alias_input(self):
        value = declaration_fixture()
        value["target"]["source"]["commit"] = "HEAD"
        self.rejects(self.validate, value)
        value = declaration_fixture()
        before = copy.deepcopy(value)
        result = self.validate(value)
        result["target"]["target"]["ref"] = "refs/heads/new"
        result["reason"] = "changed"
        self.assertEqual(value, before)

    def test_accepts_immutable_command_payload_without_mutating_it(self):
        from aetp.domain.models import Command
        # Existing Command carrier only; neither new command type is registered.
        command = Command("cmd-input", "p", "human", "project.create", "p",
                          declaration_fixture(), 0, "key-input", "input-test")
        result = self.validate(command.payload)
        self.assertEqual(result, declaration_fixture())
        result["target"]["source"]["commit"] = "f" * 40
        self.assertEqual(command.payload["target"]["source"]["commit"], "1" * 40)


class MergeInputTests(InputCase):
    def setUp(self):
        self.validate = self.validator("validate_merge_payload")

    def test_content_digest_reference_preserves_prefix_and_version(self):
        for version in (1, 64):
            for digest in ("sha256:" + "a" * 64, "sha256:" + "0" * 64):
                value = {"declaration_version": version, "declaration_digest": digest}
                self.assertEqual(self.validate(value), value)
                result = self.validate(value)
                result["declaration_version"] = 2
                self.assertEqual(value["declaration_version"], version)

    def test_digest_namespace_and_full_lowercase_encoding_are_required(self):
        fixtures = ("", "a" * 64, "a" * 40, "SHA256:" + "a" * 64, "sha256:" + "A" * 64,
                    "sha256:" + "g" * 64, "sha256:" + "a" * 63, "sha256:" + "a" * 65,
                    "sha256:" + "a" * 64 + "\n", " sha256:" + "a" * 64, None, True, [], {})
        for digest in fixtures:
            value = {"declaration_version": 1, "declaration_digest": digest}
            with self.subTest(digest=digest):
                self.rejects(self.validate, value)

    def test_reference_version_rejects_bool_float_and_out_of_range(self):
        for version in (0, -1, 65, True, False, 1.0, "1", None, [], {}):
            value = {"declaration_version": version, "declaration_digest": "sha256:" + "a" * 64}
            with self.subTest(version=version):
                self.rejects(self.validate, value)

    def test_merge_payload_rejects_omissions_extra_execution_claims_and_nonobjects(self):
        good = {"declaration_version": 1, "declaration_digest": "sha256:" + "a" * 64}
        for field in good:
            value = dict(good)
            del value[field]
            self.rejects(self.validate, value)
        for field in ("source", "target", "result", "result_commit", "ready", "authority", "runner", "session"):
            value = {**good, field: "caller-controlled"}
            self.rejects(self.validate, value)
        for value in (None, [], (), "merge", True, 1):
            self.rejects(self.validate, value)

    def test_validation_is_data_only_without_files_process_network_or_clock(self):
        from contextlib import ExitStack
        from unittest.mock import patch
        target_validator = self.validator("validate_target")
        declaration_validator = self.validator("validate_declaration_payload")
        good = {"declaration_version": 1, "declaration_digest": "sha256:" + "a" * 64}
        # Guards catch a validator that resolves a repository or starts execution;
        # these are forbidden dependency boundaries, not mocked business results.
        guarded = ("builtins.open", "pathlib.Path.open", "pathlib.Path.resolve",
                   "subprocess.Popen", "os.system", "socket.socket", "time.time")
        with ExitStack() as stack:
            guards = [stack.enter_context(patch(name, side_effect=AssertionError(name))) for name in guarded]
            self.assertEqual(target_validator(target_fixture()), target_fixture())
            self.assertEqual(declaration_validator(declaration_fixture()), declaration_fixture())
            self.assertEqual(self.validate(good), good)
            for guard in guards:
                guard.assert_not_called()
