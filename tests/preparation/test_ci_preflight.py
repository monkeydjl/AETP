import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools.ci_preflight import (
    _dedent,
    _logical_lines,
    _parse_workflow,
    check_acceptance_evidence,
)

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


class LogicalLinesTests(unittest.TestCase):
    """The continuation joiner, which shipped broken once and was found by eye.

    Treating each physical line as its own command made the wrapped arguments of
    a multi-line invocation look like unknown commands, and skipped the check on
    the invocation itself. Nothing covered it, so these pin the behaviour.
    """

    def test_backslash_continuation_becomes_one_command(self):
        script = (
            "python -m conformance.runner \\\n"
            "  --db /tmp/run.db \\\n"
            "  --json /tmp/run.json \\\n"
            "  --frozen-evidence"
        )
        self.assertEqual(
            _logical_lines(script),
            ["python -m conformance.runner --db /tmp/run.db --json /tmp/run.json --frozen-evidence"],
        )

    def test_separate_commands_stay_separate(self):
        self.assertEqual(
            _logical_lines("python tools/devprep.py check\npython tools/devprep.py render"),
            ["python tools/devprep.py check", "python tools/devprep.py render"],
        )

    def test_trailing_continuation_at_end_is_not_lost(self):
        # A script ending mid-continuation still has to surface its buffer,
        # otherwise the last command vanishes from the check silently.
        self.assertEqual(_logical_lines("python -m unittest \\\n  discover"), ["python -m unittest discover"])

    def test_blank_lines_are_dropped(self):
        self.assertEqual(_logical_lines("\n\n  \npython -m pytest\n\n"), ["python -m pytest"])


class DedentTests(unittest.TestCase):
    def test_strips_only_the_common_indentation(self):
        self.assertEqual(_dedent("      a\n        b\n"), "a\n  b")

    def test_blank_block_is_empty(self):
        self.assertEqual(_dedent("\n   \n"), "")


class ParseWorkflowTests(unittest.TestCase):
    def test_reads_the_committed_workflow(self):
        facts = _parse_workflow(WORKFLOW.read_text(encoding="utf-8"))
        self.assertTrue(facts["python_version"])
        # A bare major such as "3" leaves setup-python unable to pick a series.
        self.assertIn(".", facts["python_version"])
        self.assertTrue(facts["runs_on"])
        self.assertTrue(facts["actions"])
        self.assertTrue(facts["steps"])
        self.assertTrue(all(step["name"] and step["run"] for step in facts["steps"]))

    def test_detects_a_workflow_still_claiming_it_never_ran(self):
        # The disabled note job used to carry this sentence. It has now run, so a
        # workflow that still says so is the stale one and must be flagged.
        facts = _parse_workflow("jobs:\n  x:\n    steps: []\n# has NOT been run against a real remote\n")
        self.assertTrue(facts["claims_never_run"])


class AcceptanceEvidenceTests(unittest.TestCase):
    def test_reports_missing_evidence_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            backlog = Path(tmp) / "backlog.json"
            backlog.write_text(
                json.dumps(
                    {
                        "items": [
                            {
                                "id": "M4-01",
                                "status": "blocked",
                                "evidence": ["does-not-exist.json"],
                                "block_reason": "human sign-off remains",
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            with patch("tools.ci_preflight.BACKLOG_PATH", backlog), patch("tools.ci_preflight.ROOT", Path(tmp)):
                result = check_acceptance_evidence()
            self.assertFalse(result["ok"])
            self.assertTrue(any("evidence missing on disk" in p for p in result["problems"]))

    def test_notes_a_status_that_is_no_longer_blocked(self):
        # The premise of the packet is that these two are blocked. If one moved,
        # the reader needs to be told rather than shown a stale "blocked".
        with tempfile.TemporaryDirectory() as tmp:
            backlog = Path(tmp) / "backlog.json"
            backlog.write_text(
                json.dumps({"items": [{"id": "M4-03", "status": "done", "evidence": [], "block_reason": ""}]}),
                encoding="utf-8",
            )
            with patch("tools.ci_preflight.BACKLOG_PATH", backlog), patch("tools.ci_preflight.ROOT", Path(tmp)):
                result = check_acceptance_evidence()
            self.assertTrue(any("not 'blocked'" in n for n in result["notes"]))

    def test_does_not_quote_a_fragment_of_the_blocker(self):
        # An earlier version split Chinese prose on whitespace and printed pieces
        # like "人类验收（§9.4/INV-019）AI". Only the party names may be reported.
        with tempfile.TemporaryDirectory() as tmp:
            backlog = Path(tmp) / "backlog.json"
            backlog.write_text(
                json.dumps({"items": [{"id": "M4-01", "status": "blocked", "evidence": [], "block_reason": "等待人类验收"}]}),
                encoding="utf-8",
            )
            with patch("tools.ci_preflight.BACKLOG_PATH", backlog), patch("tools.ci_preflight.ROOT", Path(tmp)):
                result = check_acceptance_evidence()
            joined = " ".join(result["notes"])
            self.assertIn("人类验收", joined)
            self.assertNotIn("等待人类验收", joined)


if __name__ == "__main__":
    unittest.main()
