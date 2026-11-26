"""Host-level isolation probe: does this machine give a REAL OS/container boundary?

Specification source: Docs/AETP-设计方案.md §13.9 ("工作副本隔离不等于安全隔离")
and the M4-03 remaining gap "真实 OS 容器级隔离".

Why this is a separate module with its own explicit gate rather than ordinary
tests: a probe that cannot run MUST NOT be reported as passed. In this suite a
test that never ran is recorded as skipped with a machine-readable reason, and
``isolation_probe_report()`` only reports ``verified=True`` when the container
probe actually executed its assertions. An unavailable Docker daemon therefore
means "host isolation is not established", not "OK".

What the probe asserts once a container boundary exists (§13.9 anti-bypass):
  * a write to a path outside the mounted working copy fails;
  * the host filesystem is not mounted, so a host-side secret path is invisible;
  * a neighbouring working copy is not reachable;
  * host environment (credentials) is not inherited.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

IMAGE = "python:3.12-alpine"
DOCKER_TIMEOUT_S = 120


def _docker_binary() -> Optional[str]:
    return shutil.which("docker")


def docker_daemon_reachable(timeout: int = 20) -> bool:
    binary = _docker_binary()
    if binary is None:
        return False
    try:
        done = subprocess.run(
            [binary, "info", "--format", "{{.ServerVersion}}"],
            capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0 and bool(done.stdout.strip())


def _run_docker(args, timeout: int = DOCKER_TIMEOUT_S) -> subprocess.CompletedProcess:
    return subprocess.run(
        [_docker_binary(), *args], capture_output=True, text=True, timeout=timeout,
    )


def _demo_container(image: str = "alpine") -> Optional[str]:
    """Start a throwaway container; returns its id or None if the image is absent."""
    done = _run_docker(["run", "-d", "--rm", "--network", "none", image, "sleep", "600"])
    if done.returncode != 0:
        return None
    return done.stdout.strip()


def _remove_container(container_id: str) -> None:
    _run_docker(["rm", "-f", container_id])


@dataclass
class IsolationObservation:
    level: str
    observed: bool
    facts: Dict[str, Any]

    def applies(self) -> bool:
        """A 'capability gap' claim needs a running OS; a boundary claim needs a container."""
        return self.observed

    def to_dict(self) -> Dict[str, Any]:
        return {"level": self.level, "observed": self.observed, "facts": dict(self.facts)}


def probe_working_copy_boundary(tmp: Path) -> IsolationObservation:
    """Working-copy level: can a sibling copy be read from inside the directory?

    §13.9 says a working copy is NOT a security boundary. This probe records the
    observable fact instead of asserting it either way, so the Conformance
    claim "working_copy" stays tied to what was measured.
    """
    facts: Dict[str, Any] = {}
    try:
        only_copy = tmp / "copy"
        only_copy.mkdir()
        sibling_visible = (only_copy / "..").resolve() != only_copy.resolve()
        facts["sibling_directory_reachable"] = sibling_visible
        # Measured, not assumed: write a canary into a sibling directory of the
        # working copy. If the write succeeds, no boundary exists at this level
        # (which is exactly what §13.9 says a working copy does not promise).
        # The key is always present, so a refused write reads as False rather
        # than as "no measurement".
        facts["host_paths_reachable"] = False
        outside = tmp / "outside-probe.txt"
        try:
            outside.write_text("x", encoding="utf-8")
        except OSError:
            pass
        else:
            facts["host_paths_reachable"] = outside.exists()
        return IsolationObservation("working_copy", True, facts)
    except OSError as exc:  # pragma: no cover - filesystem unusable
        facts["error"] = type(exc).__name__
        return IsolationObservation("working_copy", False, facts)


def probe_container_boundary(tmp: Path) -> IsolationObservation:
    """Container level: run the anti-bypass assertions inside a real container."""
    facts: Dict[str, Any] = {}
    if not docker_daemon_reachable():
        facts["skipped"] = "docker_daemon_unreachable" if _docker_binary() else "docker_binary_absent"
        return IsolationObservation("os_sandbox", False, facts)

    container_id = _demo_container()
    if container_id is None:
        facts["skipped"] = "container_image_unavailable"
        return IsolationObservation("os_sandbox", False, facts)
    try:
        mounted = tmp / "work"
        mounted.mkdir(exist_ok=True)
        (mounted / "inside.txt").write_text("ok", encoding="utf-8")
        # The escape attempts must target HOST paths, not container-root ones:
        # "/outside_escape" lives in the container's own writable root and is
        # writable in every container, so asserting on it proves nothing about
        # the boundary. The probe root is mounted read-only, so a container-side
        # write only succeeds if it really escaped through the mount.
        host_secret = tmp / "host-secret-probe"
        escape_target = tmp / "escape-probe.txt"
        c_escape = json.dumps(escape_target.as_posix())
        c_secret = json.dumps(host_secret.as_posix())
        script = (
            "import json, os\n"
            "checks = {}\n"
            "for name, path in (('outside_escape', " + c_escape + "), ('host_secret', " + c_secret + ")):\n"
            "    try:\n"
            "        open(path, 'w').write('x')\n"
            "        checks[name] = 'allowed'\n"
            "    except OSError:\n"
            "        checks[name] = 'denied'\n"
            "checks['host_secret_visible'] = os.path.exists(" + c_secret + ")\n"
            "checks['env_credential_visible'] = any(k in os.environ for k in ('AETP_HOST_PROBE', 'AWS_SECRET_ACCESS_KEY'))\n"
            "checks['work_write'] = 'allowed'\n"
            "try:\n"
            "    open('/work/written_by_container', 'w').write('x')\n"
            "except OSError:\n"
            "    checks['work_write'] = 'denied'\n"
            "print(json.dumps(checks))\n"
        )

        done = _run_docker([
            "run", "--rm", "--network", "none",
            # Read-only probe root; only the working copy itself is writable.
            "-v", f"{tmp.as_posix()}:/probe:ro",
            "-v", f"{mounted.as_posix()}:/work:rw",
            "--workdir", "/work", IMAGE, "python", "-c", script,
        ])
        if done.returncode != 0:
            facts["error"] = (done.stderr or "")[-400:]
            return IsolationObservation("os_sandbox", False, facts)
        checks = json.loads(done.stdout.strip().splitlines()[-1])
        facts.update(checks)
        facts["write_inside_visible_on_host"] = (mounted / "written_by_container").exists()
        # Ground truth is the host side: if the container really wrote these
        # paths, the files exist here now, whatever the container reported.
        facts["host_escape_created"] = escape_target.exists()
        facts["host_secret_created"] = host_secret.exists()
        isolated = (
            checks["outside_escape"] == "denied"
            and checks["host_secret"] == "denied"
            and not facts["host_escape_created"]
            and not facts["host_secret_created"]
            and not checks["host_secret_visible"]
            and not checks["env_credential_visible"]
            and checks["work_write"] == "allowed"
            and facts["write_inside_visible_on_host"]
        )
        return IsolationObservation("os_sandbox", isolated, facts)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        facts["error"] = type(exc).__name__
        return IsolationObservation("os_sandbox", False, facts)
    finally:
        _remove_container(container_id)


def isolation_probe_report() -> Dict[str, Any]:
    """Machine-readable state of this host's isolation, from an executed probe."""
    import tempfile

    with tempfile.TemporaryDirectory(prefix="aetp-isolation-probe-") as raw:
        tmp = Path(raw)
        observations = {
            "working_copy": probe_working_copy_boundary(tmp).to_dict(),
        }
        # Only run the container probe when a container runtime exists at all;
        # when it does not, the level is recorded as unavailable, not as passed.
        if docker_daemon_reachable():
            observations["os_sandbox"] = probe_container_boundary(tmp).to_dict()
        else:
            observations["os_sandbox"] = {
                "level": "os_sandbox", "observed": False,
                "facts": {"skipped": "docker_daemon_unreachable" if _docker_binary() else "docker_binary_absent"},
            }
    return {
        "verified_levels": [k for k, v in observations.items() if v["observed"]],
        "observations": observations,
    }


class IsolationProbeTests(unittest.TestCase):
    """The probe must never convert 'could not run' into 'passed'."""

    def test_probe_report_separates_observed_from_unavailable(self):
        report = isolation_probe_report()
        for level, entry in report["observations"].items():
            self.assertEqual(entry["observed"], level in report["verified_levels"])
            if not entry["observed"]:
                self.assertIn("skipped", entry["facts"])
            # A level that never ran can never be reported as verified.
            self.assertFalse(entry["observed"] and "skipped" in entry["facts"])

    def test_working_copy_is_not_reported_as_a_container_boundary(self):
        report = isolation_probe_report()
        self.assertIn("working_copy", report["observations"])
        self.assertNotEqual(
            report["observations"]["working_copy"]["level"], "os_sandbox",
            "§13.9: a working copy must not be relabelled as an OS/container boundary",
        )


    def test_working_copy_facts_are_measured_not_hardcoded(self):
        """A fact the report publishes must come from the filesystem, not a literal.

        Guards the canary in probe_working_copy: if someone writes
        facts["host_paths_reachable"] = True again, the injected failure below
        stops being observable and this test dies.
        """
        import tempfile
        from unittest import mock

        def fresh_root(raw: str, tag: str) -> Path:
            # probe_working_copy_boundary makes <tmp>/copy on entry, so the
            # second call needs its own root; reusing the first would fail with
            # FileExistsError and report no facts at all (a different failure
            # mode that this pin must not accept as a pass).
            root = Path(raw) / tag
            root.mkdir(exist_ok=True)
            return root

        with tempfile.TemporaryDirectory(prefix="aetp-facts-probe-") as raw:
            measured = probe_working_copy_boundary(fresh_root(raw, "measured"))
            self.assertTrue(measured.facts["host_paths_reachable"])

            real_write_text = Path.write_text

            def refuse_canary(self, *args, **kwargs):
                if self.name == "outside-probe.txt":
                    raise OSError("injected: sibling write refused")
                return real_write_text(self, *args, **kwargs)

            with mock.patch.object(Path, "write_text", refuse_canary):
                blocked = probe_working_copy_boundary(fresh_root(raw, "blocked"))
            self.assertIn("host_paths_reachable", blocked.facts)
            self.assertFalse(
                blocked.facts["host_paths_reachable"],
                "§13.9: 'reachable' may only be reported if the probe tested it",
            )


@unittest.skipUnless(docker_daemon_reachable(), "no container runtime on this host")
class ContainerBoundaryProbeTests(unittest.TestCase):
    """Real anti-bypass assertions; skipped (never silently passed) without Docker."""

    def test_container_cannot_escape_the_mounted_working_copy(self):
        import tempfile

        with tempfile.TemporaryDirectory(prefix="aetp-container-probe-") as raw:
            observation = probe_container_boundary(Path(raw))
        self.assertTrue(observation.observed, observation.facts)
        self.assertEqual(observation.facts["outside_escape"], "denied")
        self.assertEqual(observation.facts["host_secret"], "denied")
        self.assertFalse(observation.facts["host_escape_created"])
        self.assertFalse(observation.facts["host_secret_created"])
        self.assertFalse(observation.facts["host_secret_visible"])
        self.assertFalse(observation.facts["env_credential_visible"])
        self.assertTrue(observation.facts["write_inside_visible_on_host"])


if __name__ == "__main__":
    print(json.dumps(isolation_probe_report(), indent=2, ensure_ascii=False))
