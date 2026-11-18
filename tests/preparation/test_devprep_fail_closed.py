"""Regression cases for the PREP-007 independent review; no product execution."""

import copy
import io
import json
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools import devprep


ROOT = Path(__file__).resolve().parents[2]
SENTINEL = "SYNTHETIC_UNTRUSTED_OUTPUT_DO_NOT_COPY"


def material(name):
    return json.loads((ROOT / "Docs" / "development" / name).read_text(encoding="utf-8-sig"))


class FailClosedPreparationTests(unittest.TestCase):
    def test_graph_rejects_invalid_node_ids_even_if_edges_refer_to_them(self):
        for invalid_id in (None, "", "   ", 0, []):
            with self.subTest(invalid_id=invalid_id):
                graph = material("knowledge-graph.json")
                node = copy.deepcopy(graph["nodes"][0])
                node["id"] = invalid_id
                graph["nodes"].append(node)
                graph["edges"].append({
                    "source": graph["nodes"][0]["id"], "target": invalid_id,
                    "relation": "verified_by", "source_reference": "synthetic fixture",
                })
                try:
                    errors = devprep.validate_graph(graph)
                except (TypeError, KeyError) as error:
                    self.fail(f"Invalid graph must be rejected, not crash: {type(error).__name__}")
                self.assertTrue(errors, "Invalid node ID and target were accepted")

    def test_backlog_rejects_wrong_types_instead_of_coercing_falsey_values(self):
        for field in ("depends_on", "conformance_tests"):
            for invalid in ({}, "", 0, None, [None], [[]]):
                with self.subTest(field=field, invalid=invalid):
                    backlog = material("backlog.json")
                    backlog["work_items"][0][field] = invalid
                    try:
                        errors = devprep.validate_backlog(backlog)
                    except (TypeError, KeyError) as error:
                        self.fail(f"Invalid backlog must be rejected, not crash: {type(error).__name__}")
                    self.assertTrue(errors, f"Accepted invalid {field}")

    def test_backlog_rejects_invalid_work_item_ids(self):
        for invalid_id in (None, "", "   ", 0, []):
            with self.subTest(invalid_id=invalid_id):
                backlog = material("backlog.json")
                # Add an unreferenced synthetic item so invalid-ID detection
                # cannot rely on a dangling dependency edge.
                item = copy.deepcopy(backlog["work_items"][0])
                item.update(id=invalid_id, status="todo", depends_on=[])
                backlog["work_items"].append(item)
                try:
                    errors = devprep.validate_backlog(backlog)
                except (TypeError, KeyError) as error:
                    self.fail(f"Invalid ID must be rejected, not crash: {type(error).__name__}")
                self.assertTrue(errors, "Invalid work-item ID was accepted")

    def test_structural_validation_handles_non_objects_and_unhashable_fields(self):
        cases = (
            ("backlog.json", devprep.validate_backlog, "work_items", None, None),
            ("backlog.json", devprep.validate_backlog, "work_items", "status", []),
            ("backlog.json", devprep.validate_backlog, "work_items", "milestone", {}),
            ("backlog.json", devprep.validate_backlog, "work_items", "files", [None]),
            ("backlog.json", devprep.validate_backlog, "work_items", "acceptance", [""]),
            ("backlog.json", devprep.validate_backlog, "work_items", "evidence", [[]]),
            ("knowledge-graph.json", devprep.validate_graph, "nodes", None, None),
            ("knowledge-graph.json", devprep.validate_graph, "nodes", "type", []),
            ("knowledge-graph.json", devprep.validate_graph, "edges", None, None),
            ("knowledge-graph.json", devprep.validate_graph, "edges", "source", []),
            ("knowledge-graph.json", devprep.validate_graph, "edges", "target", {}),
        )
        for name, validate, collection, field, value in cases:
            with self.subTest(name=name, collection=collection, field=field):
                document = material(name)
                if field is None:
                    document[collection].append(value)
                else:
                    document[collection][0][field] = value
                try:
                    errors = validate(document)
                except (TypeError, KeyError, AttributeError) as error:
                    self.fail(f"Invalid structure must be rejected, not crash: {type(error).__name__}")
                self.assertTrue(errors)

    def test_ready_requires_done_dependencies(self):
        for item_state in ("ready", "in_progress", "done"):
            for dependency_state in ("todo", "ready", "in_progress", "review", "blocked"):
                with self.subTest(item_state=item_state, dependency_state=dependency_state):
                    backlog = material("backlog.json")
                    items = {item["id"]: item for item in backlog["work_items"]}
                    items["PREP-006"]["status"] = dependency_state
                    items["PREP-007"].update(
                        status=item_state,
                        acceptance_evidence="synthetic evidence, not product acceptance",
                        reproduction_command="synthetic command",
                        independent_reviewer="synthetic reviewer",
                    )
                    errors = devprep.validate_backlog(backlog)
                    self.assertTrue(any("PREP-007" in error and "PREP-006" in error for error in errors), errors)

    def test_ready_accepts_fulfilled_dependencies(self):
        backlog = material("backlog.json")
        # Keep plan structure, but isolate this positive case from live statuses.
        # A completed downstream item must not depend on our synthetic ready item.
        for item in backlog["work_items"]:
            item["status"] = "todo"
        items = {item["id"]: item for item in backlog["work_items"]}
        items["PREP-001"].update(
            status="done",
            acceptance_evidence="synthetic evidence, not product acceptance",
            reproduction_command="synthetic command",
            independent_reviewer="synthetic reviewer",
        )
        items["PREP-003"]["status"] = "ready"
        self.assertEqual(devprep.validate_backlog(backlog), [])

    def test_malformed_materials_fail_check_without_creating_success_reports(self):
        for kind in ("null_graph_identity", "falsey_dependency_type", "non_object_item", "malformed_active_items"):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory(dir=ROOT) as directory:
                root = Path(directory)
                backlog, graph, status = (material(name) for name in ("backlog.json", "knowledge-graph.json", "status.json"))
                if kind == "null_graph_identity":
                    node = copy.deepcopy(graph["nodes"][0])
                    node.pop("id")
                    graph["nodes"].append(node)
                    graph["edges"].append({"source": graph["nodes"][0]["id"], "target": None, "relation": "verified_by", "source_reference": "fixture"})
                elif kind == "falsey_dependency_type":
                    backlog["work_items"][0]["depends_on"] = {}
                elif kind == "non_object_item":
                    backlog["work_items"].append(None)
                else:
                    status["active_work_items"] = {}
                paths = {}
                for key, value in (("BACKLOG_PATH", backlog), ("GRAPH_PATH", graph), ("STATUS_PATH", status)):
                    path = root / (key + ".json")
                    path.write_text(json.dumps(value), encoding="utf-8")
                    paths[key] = path
                reports = {key: root / (key + ".json") for key in ("DEVPREP_CHECK_PATH", "GRAPH_CHECK_PATH", "BACKLOG_CHECK_PATH")}
                output = io.StringIO()
                with patch.multiple(devprep, **paths, **reports), redirect_stdout(output):
                    try:
                        exit_code = devprep.command_check()
                    except (TypeError, KeyError, AttributeError) as error:
                        self.fail(f"Malformed materials must be rejected, not crash: {type(error).__name__}")
                self.assertEqual(exit_code, 1, output.getvalue())
                for report in reports.values():
                    self.assertFalse(report.exists(), report.name)

    def test_version_probe_rejects_unknown_empty_or_multiline_output(self):
        for command in ("node", "git", "uv"):
            for stdout, stderr in ((SENTINEL, ""), ("", SENTINEL), ("", ""), ("v24.18.1\n" + SENTINEL, ""), ("v24.18.1", SENTINEL)):
                with self.subTest(command=command, stdout=stdout, stderr=stderr):
                    completed = subprocess.CompletedProcess([command], 0, stdout, stderr)
                    with patch.object(devprep.shutil, "which", return_value="synthetic-tool"), patch.object(devprep.subprocess, "run", return_value=completed):
                        result = devprep._short_version(command, ["--version"])
                    self.assertFalse(result["available"], result)
                    self.assertIsNone(result["version"])
                    self.assertNotIn(SENTINEL, json.dumps(result))

    def test_version_probe_reports_only_recognized_normalized_versions(self):
        cases = (
            ("node", "v24.18.1\n", "v24.18.1"),
            ("git", "git version 2.54.0.windows.1\n", "git version 2.54.0"),
            ("uv", "uv 0.12.5 (210d1f678 2026-08-14 x86_64-pc-windows-msvc)\n", "uv 0.12.5"),
        )
        for command, output, expected in cases:
            with self.subTest(command=command):
                with patch.object(devprep.shutil, "which", return_value="synthetic-tool"), patch.object(devprep.subprocess, "run", return_value=subprocess.CompletedProcess([command], 0, output, "")):
                    result = devprep._short_version(command, ["--version"])
                self.assertTrue(result["available"], result)
                self.assertEqual(result["version"], expected)

    def test_version_probe_failure_paths_never_report_unverified_output(self):
        with patch.object(devprep.shutil, "which", return_value=None):
            self.assertFalse(devprep._short_version("node", ["--version"])["available"])
        failures = (OSError(SENTINEL), subprocess.TimeoutExpired("node", 10, output=SENTINEL))
        for error in failures:
            with self.subTest(error=type(error).__name__):
                with patch.object(devprep.shutil, "which", return_value="synthetic-tool"), patch.object(devprep.subprocess, "run", side_effect=error):
                    result = devprep._short_version("node", ["--version"])
                self.assertFalse(result["available"])
                self.assertNotIn(SENTINEL, json.dumps(result))
        with patch.object(devprep.shutil, "which", return_value="synthetic-tool"), patch.object(devprep.subprocess, "run", return_value=subprocess.CompletedProcess(["node"], 1, SENTINEL, "")):
            result = devprep._short_version("node", ["--version"])
        self.assertFalse(result["available"])
        self.assertNotIn(SENTINEL, json.dumps(result))

    def test_environment_does_not_echo_unrecognized_tool_output(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            report = Path(directory) / "environment.json"
            output = io.StringIO()
            with (
                patch.object(devprep, "ENVIRONMENT_PATH", report),
                patch.object(devprep.shutil, "which", return_value="synthetic-tool"),
                patch.object(devprep.subprocess, "run", return_value=subprocess.CompletedProcess(["tool"], 0, SENTINEL, "")),
                redirect_stdout(output),
            ):
                self.assertEqual(devprep.command_environment(), 0)
            self.assertNotIn(SENTINEL, output.getvalue())
            self.assertNotIn(SENTINEL, report.read_text(encoding="utf-8"))
            facts = json.loads(report.read_text(encoding="utf-8"))
            for command in ("node", "git", "uv"):
                self.assertFalse(facts["tools"][command]["available"])

    def test_markdown_rejects_missing_titled_and_reference_targets(self):
        cases = (
            '[bad](missing.md "title")',
            "[bad](missing.md 'title')",
            '[bad](<missing file.md> "title")',
            '[bad][target]\n\n[target]: missing.md "title"',
            '[bad][]\n\n[bad]: missing.md',
            '[bad]\n\n[bad]: missing.md',
        )
        for text in cases:
            with self.subTest(text=text), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "README.md"
                path.write_text(text, encoding="utf-8")
                self.assertTrue(devprep.validate_markdown_links([path]), text)

    def test_markdown_accepts_existing_titled_reference_and_encoded_targets(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "valid file.md").write_text("# Scope\n", encoding="utf-8")
            markdown = root / "README.md"
            for text in (
                '[ok](<valid file.md> "title")',
                '[ok](valid%20file.md#scope "title")',
                '[ok][target]\n\n[target]: <valid file.md> "title"',
                '[ok][]\n\n[ok]: valid%20file.md',
                '[ok]\n\n[ok]: valid%20file.md',
            ):
                with self.subTest(text=text):
                    markdown.write_text(text, encoding="utf-8")
                    self.assertEqual(devprep.validate_markdown_links([markdown]), [])

    def test_markdown_skips_code_examples_and_rejects_unsupported_link_syntax(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "README.md"
            path.write_text('```markdown\n[example](missing.md)\n```\n`[example](missing.md)`', encoding="utf-8")
            self.assertEqual(devprep.validate_markdown_links([path]), [])
            path.write_text('[bad](missing.md unquoted-title)', encoding="utf-8")
            self.assertTrue(devprep.validate_markdown_links([path]))


    def test_done_rejects_a_reviewer_that_is_the_executor(self):
        """`independent_reviewer` claims independence; a copy of the executor is not one.

        truth_rules.completion_requires names independent_reviewer, but the gate only
        checked that the field was non-empty. An executor signing off on its own work
        therefore validated cleanly, and the report still read as independently
        reviewed. The rule is deliberately narrow: it fires only where both identities
        are declared and agree.
        """
        backlog = material("backlog.json")
        for item in backlog["work_items"]:
            item["status"] = "todo"
        items = {item["id"]: item for item in backlog["work_items"]}
        items["PREP-001"].update(
            status="done",
            acceptance_evidence="synthetic evidence, not product acceptance",
            reproduction_command="synthetic command",
            executor="the same agent",
            independent_reviewer="the same agent",
        )
        errors = devprep.validate_backlog(backlog)
        self.assertTrue(any("PREP-001" in error and "independent_reviewer" in error for error in errors), errors)

    def test_done_rejects_a_reviewer_equal_to_the_executor_after_trailing_prose(self):
        """The comparison is by declared identity, so a trailing date must not hide a match."""
        backlog = material("backlog.json")
        for item in backlog["work_items"]:
            item["status"] = "todo"
        items = {item["id"]: item for item in backlog["work_items"]}
        items["PREP-001"].update(
            status="done",
            acceptance_evidence="synthetic evidence, not product acceptance",
            reproduction_command="synthetic command",
            executor="Codex main agent",
            independent_reviewer="Codex main agent, 2026-01-01",
        )
        errors = devprep.validate_backlog(backlog)
        self.assertTrue(any("PREP-001" in error and "independent_reviewer" in error for error in errors), errors)

    def test_done_without_a_declared_executor_stays_valid(self):
        """Most live done items declare no executor; the gate must not invent a conflict."""
        backlog = material("backlog.json")
        for item in backlog["work_items"]:
            item["status"] = "todo"
        items = {item["id"]: item for item in backlog["work_items"]}
        items["PREP-001"].update(
            status="done",
            acceptance_evidence="synthetic evidence, not product acceptance",
            reproduction_command="synthetic command",
            independent_reviewer="some other reviewer",
        )
        self.assertEqual(devprep.validate_backlog(backlog), [])

    def test_done_with_a_distinct_reviewer_stays_valid(self):
        """The gate must not reject a genuinely different reviewer - no over-tightening."""
        backlog = material("backlog.json")
        for item in backlog["work_items"]:
            item["status"] = "todo"
        items = {item["id"]: item for item in backlog["work_items"]}
        items["PREP-001"].update(
            status="done",
            acceptance_evidence="synthetic evidence, not product acceptance",
            reproduction_command="synthetic command",
            executor="the executing agent",
            independent_reviewer="a different reviewer",
        )
        self.assertEqual(devprep.validate_backlog(backlog), [])

    def test_the_live_backlog_still_satisfies_the_reviewer_gate(self):
        """Tightening must not false-positive on the materials as they actually stand."""
        self.assertEqual(devprep.validate_backlog(material("backlog.json")), [])


    def test_conformance_outcome_counts_must_not_contradict_each_other(self):
        """28 passed and 28 failed in one record is not a record of anything.

        The gate pinned status/registered_tests/passed_tests but never read
        failed_tests or not_applicable_tests, so a self-contradictory count passed.
        """
        for field, value in (("failed_tests", 28), ("not_applicable_tests", 28)):
            with self.subTest(field=field):
                status = material("status.json")
                status["conformance"][field] = value
                errors = devprep.validate_status(status, material("backlog.json"))
                self.assertTrue(any("conformance" in error for error in errors), errors)

    def test_conformance_counters_must_be_non_negative_integers(self):
        """bool subclasses int; a true/false counter must not read as 1/0."""
        for field in ("registered_tests", "passed_tests", "failed_tests", "not_applicable_tests"):
            for bad in (True, -1, None, "28"):
                with self.subTest(field=field, bad=bad):
                    status = material("status.json")
                    status["conformance"][field] = bad
                    errors = devprep.validate_status(status, material("backlog.json"))
                    self.assertTrue(any("conformance" in error for error in errors), errors)

    def test_a_passed_conformance_status_requires_a_full_pass_count(self):
        """`status: passed` with `passed_tests: 0` denies its own headline."""
        status = material("status.json")
        status["conformance"]["status"] = "passed"
        status["conformance"]["passed_tests"] = 0
        errors = devprep.validate_status(status, material("backlog.json"))
        self.assertTrue(any("conformance" in error for error in errors), errors)

    def test_a_registered_conformance_record_stays_valid(self):
        """Nothing has passed yet; the registered state is legitimate, not a defect."""
        status = material("status.json")
        status["conformance"].update(
            status="registered", passed_tests=0, failed_tests=0,
            not_applicable_tests=0, evidence=None,
        )
        self.assertEqual(devprep.validate_status(status, material("backlog.json")), [])

    def test_a_registered_record_cannot_carry_results(self):
        """`registered` means no result exists yet, so reporting one denies the status.

        The sum guard alone let these through: registered=28 with failed=28, or with
        failed=20 + not_applicable=8, sums to exactly 28 and never exceeds it.
        """
        for field, value in (
            ("failed_tests", 28), ("not_applicable_tests", 28), ("passed_tests", 28),
        ):
            with self.subTest(field=field):
                status = material("status.json")
                status["conformance"].update(
                    status="registered", passed_tests=0, failed_tests=0,
                    not_applicable_tests=0, evidence=None,
                )
                status["conformance"][field] = value
                errors = devprep.validate_status(status, material("backlog.json"))
                self.assertTrue(any("conformance" in error for error in errors), errors)

    def test_a_registered_record_cannot_split_the_registration_across_outcomes(self):
        """failed=20 + not_applicable=8 sums to 28: under the sum guard alone it passes."""
        status = material("status.json")
        status["conformance"].update(
            status="registered", passed_tests=0, failed_tests=20,
            not_applicable_tests=8, evidence=None,
        )
        errors = devprep.validate_status(status, material("backlog.json"))
        self.assertTrue(any("conformance" in error for error in errors), errors)

    def test_a_passed_conformance_status_must_cite_evidence(self):
        """A full pass with no evidence reference is a claim with nothing behind it.

        This checks that the reference is non-empty, not that the file exists:
        devprep's docstring disclaims inferring conformance from documents on disk.
        """
        status = material("status.json")
        for bad in (None, "", "   "):
            with self.subTest(evidence=bad):
                status["conformance"]["evidence"] = bad
                errors = devprep.validate_status(status, material("backlog.json"))
                self.assertTrue(any("conformance" in error for error in errors), errors)

    def test_a_registered_record_may_omit_its_evidence_reference(self):
        """Nothing has passed, so there is nothing to cite - this must stay valid."""
        status = material("status.json")
        status["conformance"].update(
            status="registered", passed_tests=0, failed_tests=0,
            not_applicable_tests=0, evidence=None,
        )
        self.assertEqual(devprep.validate_status(status, material("backlog.json")), [])

    def test_the_live_status_still_stands(self):
        """Tightening must not false-positive on the record as it actually stands."""
        self.assertEqual(
            devprep.validate_status(material("status.json"), material("backlog.json")), []
        )


if __name__ == "__main__":
    unittest.main()
