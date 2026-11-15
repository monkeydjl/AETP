"""Guard the full-suite command against the silent "never collected" failure mode.

`python -m unittest discover -s tests -t .` walks the hard-coded file pattern
``test*.py``. A test module named ``isolation_probe.py`` therefore never runs,
and the run still reports success -- that is exactly how the 2026-11-09
container-isolation probe sat outside the suite while every report said green.

These cases pin the rule that closes that hole: a file that defines test cases
must either be named ``test*.py`` or be declared a compatibility shim here, and
every declared shim must really exist. The second half matters because a shim
entry that stopped existing would read as "covered" while nothing runs.
"""

import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TESTS = ROOT / "tests"

# Files that define test cases but deliberately do NOT match ``test*.py``.
# Every entry below is a shared fixture/harness base class imported by real test
# modules by name (``from tests.m1.support import CollaborationCase``). Splitting
# it into test_*.py would put the base class itself into the suite and run setup
# as if it were a test. Anything else belongs in a ``test_*.py`` file.
DECLARED_COMPATIBILITY_SHIMS: tuple[str, ...] = (
    "tests/m1/execution_support.py",  # ExecutionCase: execution fixture used by tests.m1.test_*
    "tests/m1/support.py",            # CollaborationCase: collaboration fixture
    "tests/m2/support.py",            # MeetingCase: governance/meeting fixture
    "tests/m3/integration_record_support.py",  # RecordCase: integration record fixture
)


def _defines_test_cases(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
    except SyntaxError:
        # An unparseable module is a different failure; do not hide it behind
        # a collection rule.
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for base in node.bases:
            name = base.id if isinstance(base, ast.Name) else base.attr if isinstance(base, ast.Attribute) else ""
            if name == "TestCase":
                return True
    return False


def undiscovered_test_modules() -> list[str]:
    """Test files that define cases yet match neither ``test*.py`` nor a shim."""
    found = []
    for path in sorted(TESTS.rglob("*.py")):
        relative = path.relative_to(ROOT).as_posix()
        if path.name.startswith("test"):
            continue
        if relative in DECLARED_COMPATIBILITY_SHIMS:
            continue
        if path.name != "__init__.py" and _defines_test_cases(path):
            found.append(relative)
    return found


def missing_shims() -> list[str]:
    return [name for name in DECLARED_COMPATIBILITY_SHIMS if not (ROOT / name).is_file()]


class CollectionGuardTests(unittest.TestCase):
    def test_no_test_module_is_invisible_to_discover(self):
        offenders = undiscovered_test_modules()
        self.assertEqual(
            offenders, [],
            "These files define TestCase classes but `unittest discover` will never "
            "collect them because their names do not match 'test*.py'. Rename them "
            "to test_*.py, or declare a real reason in DECLARED_COMPATIBILITY_SHIMS: "
            f"{offenders}",
        )

    def test_declared_compatibility_shims_exist(self):
        self.assertEqual(
            missing_shims(), [],
            "A declared compatibility shim that no longer exists reads as covered "
            "while nothing runs.",
        )

    def test_the_guard_notices_a_hidden_test_module(self):
        # The guard must be a measurement, not a hard-coded empty list: a
        # synthetically hidden module has to be reported.
        import tempfile

        with tempfile.TemporaryDirectory(prefix="aetp-collection-guard-") as raw:
            hidden = Path(raw) / "probe_like_name.py"
            hidden.write_text(
                "import unittest\n\n\nclass Hidden(unittest.TestCase):\n    def test_x(self):\n        pass\n",
                encoding="utf-8",
            )
            self.assertTrue(_defines_test_cases(hidden))
            visible = Path(raw) / "test_visible.py"
            visible.write_text(hidden.read_text(encoding="utf-8"), encoding="utf-8")
            # Named test*: not an offender, even though it defines test cases.
            self.assertTrue(visible.name.startswith("test"))

        self.assertFalse(_defines_test_cases(ROOT / "tests" / "conformance" / "__init__.py"))


class IsolationProbeIsCollectedTests(unittest.TestCase):
    def test_the_isolation_probe_is_a_discoverable_test_module(self):
        probe = TESTS / "conformance" / "test_isolation_probe.py"
        self.assertTrue(probe.is_file(), "the container-isolation probe must exist in the suite")
        self.assertTrue(_defines_test_cases(probe))


if __name__ == "__main__":
    print("undiscovered:", undiscovered_test_modules())
    print("missing shims:", missing_shims())
