import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from tools import devprep
from tools.devprep import validate_markdown_links

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "devprep.py"


# Hand-written PREP-003 navigation fixture, independent of SKILL_MARKERS.
EXECUTION_SKILL_FIXTURE = (
    "---\n"
    "name: execution-contracts\n"
    "description: Use when reviewing execution contracts\n"
    "---\n"
    "Command\nEvent\nEvent Store\nProjection\nReplay\nUNKNOWN\nLease\n"
    "\u5e42\u7b49\n\u6267\u884c\u8fb9\u754c\n"
)


class DevprepPreparationTests(unittest.TestCase):
    def run_cli(self, command):
        return subprocess.run(
            [sys.executable, str(SCRIPT), command],
            cwd=ROOT,
            text=True,
            capture_output=True,
        )

    def test_check_accepts_internal_preparation_material(self):
        result = self.run_cli("check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK", result.stdout)


    def test_check_reports_markdown_link_validation(self):
        result = self.run_cli("check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report_path = ROOT / "Docs" / "development" / "evidence" / "devprep-check.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["validations"].get("markdown_links"), "passed")

    def test_render_reports_zero_product_completion_and_no_bootstrap_claim(self):
        result = self.run_cli("render")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("product_completion_percent: 0%", result.stdout)
        self.assertNotIn("BOOTSTRAP_VERIFIED", result.stdout)
        report_path = ROOT / "Docs" / "development" / "evidence" / "preparation-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertEqual(report["product_completion_percent"], 0)
        self.assertEqual(report["bootstrap_status"], "not_started")

    def test_environment_report_contains_versions_only_and_no_secret_names(self):
        result = self.run_cli("environment")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        report_path = ROOT / "Docs" / "development" / "evidence" / "environment.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        self.assertIn("tools", report)
        self.assertNotIn("OPENAI_API_KEY", result.stdout)
        self.assertNotIn("SECRET", result.stdout.upper())
        self.assertNotIn("TOKEN", result.stdout.upper())
        self.assertNotIn("KEY", result.stdout.upper())

    def test_graph_and_backlog_invariants_are_checked(self):
        result = self.run_cli("check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("graph", result.stdout.lower())
        self.assertIn("backlog", result.stdout.lower())
        self.assertIn("acyclic", result.stdout.lower())
        self.assertIn("skills=3", result.stdout.lower())

    def test_skill_validation_rejects_missing_execution_contract_marker(self):
        for missing in (
            "Command", "Event Store", "Projection", "Replay", "UNKNOWN", "Lease",
            "\u5e42\u7b49", "\u6267\u884c\u8fb9\u754c",
        ):
            with self.subTest(missing=missing):
                with tempfile.TemporaryDirectory(dir=ROOT) as directory:
                    skill = Path(directory) / "execution-contracts.md"
                    skill.write_text(EXECUTION_SKILL_FIXTURE.replace(missing, ""), encoding="utf-8")
                    with patch.dict(devprep.SKILL_PATHS, {"execution-contracts": skill}):
                        errors, count = devprep.validate_skills()
                self.assertEqual(count, 3)
                self.assertTrue(
                    any(error.endswith(f"required marker missing: {missing}") for error in errors),
                    errors,
                )

    def test_skill_validation_accepts_complete_execution_contract_markers(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as directory:
            skill = Path(directory) / "execution-contracts.md"
            skill.write_text(EXECUTION_SKILL_FIXTURE, encoding="utf-8")
            with patch.dict(devprep.SKILL_PATHS, {"execution-contracts": skill}):
                errors, count = devprep.validate_skills()
        self.assertEqual(errors, [])
        self.assertEqual(count, 3)

    def test_check_rejects_missing_skill_marker_without_success_reports(self):
        for missing in ("Event Store", "Projection", "\u5e42\u7b49", "\u6267\u884c\u8fb9\u754c"):
            with self.subTest(missing=missing):
                with tempfile.TemporaryDirectory(dir=ROOT) as directory:
                    root = Path(directory)
                    skill = root / "execution-contracts.md"
                    skill.write_text(EXECUTION_SKILL_FIXTURE.replace(missing, ""), encoding="utf-8")
                    reports = {
                        "DEVPREP_CHECK_PATH": root / "devprep-check.json",
                        "GRAPH_CHECK_PATH": root / "knowledge-graph-check.json",
                        "BACKLOG_CHECK_PATH": root / "backlog-check.json",
                    }
                    output = io.StringIO()
                    with (
                        patch.dict(devprep.SKILL_PATHS, {"execution-contracts": skill}),
                        patch.multiple(devprep, **reports),
                        redirect_stdout(output),
                    ):
                        exit_code = devprep.command_check()
                    self.assertEqual(exit_code, 1, output.getvalue())
                    self.assertIn(f"required marker missing: {missing}", output.getvalue())
                    for report in reports.values():
                        self.assertFalse(report.exists(), report.name)

    def test_check_writes_separate_preparation_evidence_reports(self):
        result = self.run_cli("check")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for name in ("devprep-check.json", "knowledge-graph-check.json", "backlog-check.json"):
            path = ROOT / "Docs" / "development" / "evidence" / name
            self.assertTrue(path.is_file(), name)
            report = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(report["exit_code"], 0)
            self.assertFalse(report.get("product_acceptance", True))

    def test_markdown_link_validator_rejects_missing_target(self):
        with tempfile.TemporaryDirectory() as directory:
            markdown = Path(directory) / "README.md"
            markdown.write_text("[missing](does-not-exist.md)\n", encoding="utf-8")
            errors = validate_markdown_links([markdown])
        self.assertEqual(len(errors), 1)
        self.assertIn("does-not-exist.md", errors[0])


    def test_markdown_link_validator_accepts_existing_relative_target(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            docs = root / "docs"
            docs.mkdir()
            (docs / "plan.md").write_text("# Scope\n", encoding="utf-8")
            markdown = root / "README.md"
            markdown.write_text("[plan](docs/plan.md#scope)\n", encoding="utf-8")
            self.assertEqual(validate_markdown_links([markdown]), [])

    def test_markdown_link_validator_skips_non_file_links(self):
        with tempfile.TemporaryDirectory() as directory:
            markdown = Path(directory) / "README.md"
            markdown.write_text(
                "[section](#scope) [web](https://example.invalid/docs) "
                "[email](mailto:team@example.invalid)\n",
                encoding="utf-8",
            )
            self.assertEqual(validate_markdown_links([markdown]), [])

    def test_material_validation_includes_broken_entry_links(self):
        with tempfile.TemporaryDirectory() as directory:
            markdown = Path(directory) / "README.md"
            markdown.write_text("[plan](missing-plan.md)\n", encoding="utf-8")
            with patch.object(devprep, "MARKDOWN_ENTRY_PATHS", (markdown,)):
                errors, _, _, _ = devprep.validate_materials()
            self.assertTrue(any("missing-plan.md" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
