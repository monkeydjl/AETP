"""Hand-derived checks for the bounded, data-only JSON Verification Runner."""

import copy
import importlib
import json
import unittest


class VerificationRunnerTests(unittest.TestCase):
    def setUp(self):
        try:
            module = importlib.import_module("aetp.acceptance.runner")
        except ModuleNotFoundError as exc:
            if not exc.name.startswith("aetp.acceptance"):
                raise
            module = None
        self.assertIsNotNone(module, "M3-02 fixed JSON Verification Runner is missing")
        self.runner = module.FixedJsonRunner()

    def run_case(self, content, expected, path=None):
        return self.runner.run(content, [{"criterion": "Value", "path": path or [], "equals": expected}])

    def test_complete_checks_are_required_for_pass(self):
        result = self.runner.run('{"scope":"local","items":[2,null]}', [
            {"criterion": "Scope", "path": ["scope"], "equals": "local"},
            {"criterion": "Items", "path": ["items", 0], "equals": 2},
            {"criterion": "Nullable", "path": ["items", 1], "equals": None},
        ])
        self.assertEqual(result["observed_result"], "PASSED")
        self.assertEqual([x["matched"] for x in result["checks"]], [True, True, True])
        self.assertEqual([x["criterion"] for x in result["checks"]], ["Scope", "Items", "Nullable"])
        self.assertEqual(result["diagnostic"], "ALL_CHECKS_MATCHED")

    def test_type_sensitive_matching_includes_nested_booleans(self):
        fixtures = [('true', 1), ('1', True), ('false', 0), ('[true]', [1]),
                    ('{"flag":true}', {"flag": 1}), ('"1"', 1), ('1.0', 1)]
        for content, expected in fixtures:
            with self.subTest(content=content, expected=expected):
                result = self.run_case(content, expected)
                self.assertEqual(result["observed_result"], "FAILED")
                self.assertFalse(result["checks"][0]["matched"])

    def test_missing_null_and_wrong_container_are_distinct(self):
        fixtures = [('{}', ["key"], False), ('{"key":null}', ["key"], True),
                    ('[null]', [0], True), ('[null]', ["0"], False), ('{}', [0], False),
                    ('[]', [0], False), ('null', ["key"], False)]
        for content, path, matched in fixtures:
            with self.subTest(content=content, path=path):
                result = self.run_case(content, None, path)
                self.assertEqual(result["checks"][0]["matched"], matched)
                self.assertEqual(result["checks"][0]["observed_type"], "null" if matched else "missing")

    def test_invalid_target_documents_fail_without_throwing(self):
        fixtures = ['{"a":1,"a":2}', 'NaN', 'Infinity', '-Infinity', '1e400',
                    '1' * 400, '"\\ud800"', '"\ud800"', '[1,]', '', '{}{}',
                    '[' * 40 + '0' + ']' * 40, '"' + ('x' * 65536) + '"']
        for content in fixtures:
            with self.subTest(content=content[:60]):
                result = self.run_case(content, None)
                self.assertEqual(result, {"observed_result": "FAILED", "checks": [],
                                          "diagnostic": "INVALID_DOCUMENT"})

    def test_malformed_cases_cannot_vacuously_pass(self):
        fixtures = [[], {}, [None], [{"criterion": "A", "path": [], "equals": 1, "code": "x"}],
                    [{"criterion": "", "path": [], "equals": 1}],
                    [{"criterion": "A", "path": [-1], "equals": 1}],
                    [{"criterion": "A", "path": [True], "equals": 1}],
                    [{"criterion": "A", "path": [0] * 17, "equals": 1}],
                    [{"criterion": "A", "path": ["\ud800"], "equals": 1}],
                    [{"criterion": "A", "path": [], "equals": float("nan")}],
                    [{"criterion": "A", "path": [], "equals": 10 ** 400}],
                    [{"criterion": "A", "path": [], "equals": {1: "wrong key"}}],
                    [{"criterion": "A", "path": [], "equals": "x" * 16384}],
                    [{"criterion": "A", "path": [], "equals": (1,)}],
                    [{"criterion": "A", "path": [], "equals": 1}] * 33]
        for cases in fixtures:
            with self.subTest(cases=repr(cases)[:80]):
                with self.assertRaises(ValueError):
                    self.runner.run("1", cases)

    def test_valid_limits_and_unicode_preserve_inputs(self):
        cases = [{"criterion": f"Criterion {i}", "path": ["ключ"], "equals": "中文"} for i in range(32)]
        before = copy.deepcopy(cases)
        result = self.runner.run('{"ключ":"中文"}', cases)
        self.assertEqual(result["observed_result"], "PASSED")
        self.assertEqual(len(result["checks"]), 32)
        self.assertEqual(cases, before)

    def test_source_descriptor_and_diagnostics_do_not_execute_expressions(self):
        # The fixture below is deliberately constructed as literal JSON data.
        content = json.dumps({"value": "__import__('os').system('bad')"})
        result = self.run_case(content, "__import__('os').system('bad')", ["value"])
        self.assertEqual(result["observed_result"], "PASSED")
        descriptor = self.runner.descriptor
        self.assertEqual(descriptor["method"], "strict_json_path_equals")
        self.assertTrue(descriptor["implementation_digest"].startswith("sha256:"))
        self.assertIn("python_version", descriptor["environment"])
        self.assertNotIn("observed_value", result["checks"][0])
        self.assertTrue(result["checks"][0]["observed_digest"].startswith("sha256:"))

    def test_repeated_invocation_is_deterministic(self):
        cases = [{"criterion": "Items", "path": [], "equals": {"b": [1, 2], "a": 3}}]
        first = self.runner.run('{"a":3,"b":[1,2]}', cases)
        second = self.runner.run('{"b":[1,2],"a":3}', cases)
        self.assertEqual(first, second)
        self.assertEqual(first["observed_result"], "PASSED")


if __name__ == "__main__":
    unittest.main()
