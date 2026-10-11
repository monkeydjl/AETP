"""Unit and scenario tests for the Project Bootstrap lifecycle."""

import os
import tempfile
import unittest

from aetp.bootstrap.runner import run_project_bootstrap
from aetp.core.projection import Projection
from aetp.storage.sqlite_store import SQLiteStore


class BootstrapLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="aetp-boot-test-")
        self.db_path = os.path.join(self.tmp, "bootstrap_test.sqlite")

    def tearDown(self):
        try:
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            if os.path.exists(self.tmp):
                os.rmdir(self.tmp)
        except OSError:
            pass

    def test_run_project_bootstrap_full_lifecycle(self):
        """Execute full B0-B5 Bootstrap scenario and assert BOOTSTRAP_VERIFIED."""
        report = run_project_bootstrap(self.db_path)
        self.assertEqual(report["verdict"], "BOOTSTRAP_VERIFIED")
        self.assertEqual(report["final_project_phase"], "BOOTSTRAP_VERIFIED")
        self.assertEqual(report["final_bootstrap_status"], "verified")
        self.assertTrue(report["events_count"] > 0)

        # Check all logged steps passed
        for step in report["steps_verified"]:
            self.assertEqual(step["status"], "passed", f"Step failed: {step}")

        # Deterministic Event Replay assertion from the stored database
        store = SQLiteStore.open(self.db_path)
        events = store.read_events("p-bootstrap")
        rebuilt = Projection.rebuild(events)
        store.close()

        proj = rebuilt.get("project:p-bootstrap")
        self.assertIsNotNone(proj)
        self.assertEqual(proj.get("phase"), "BOOTSTRAP_VERIFIED")
        self.assertEqual(proj.get("bootstrap_status"), "verified")

        m0 = rebuilt.get("mission:mission-0-bootstrap")
        self.assertIsNotNone(m0)
        self.assertEqual(m0.get("status"), "completed")

    def test_run_project_bootstrap_rejects_existing_database(self):
        """Bootstrap refuses to overwrite an existing database file."""
        with open(self.db_path, "w") as f:
            f.write("existing")
        with self.assertRaises(FileExistsError):
            run_project_bootstrap(self.db_path)

    def test_finalize_requires_human_owner_and_rejection_preserves_project_business_state(self):
        """Non-owner cannot finalize; the rejection appends no business Event or Project revision."""
        from aetp.core.commands import CommandHandler
        from aetp.domain.models import Command
        from aetp.planning.service import PlanningService
        from tests.m2.governance_support import policy

        store = SQLiteStore.open(self.db_path)
        handler = CommandHandler(store)
        project_id = "p-finalize-auth"
        project = Command("create-project", project_id, "bootstrap", "project.create", None,
                          {"status": "planning"}, 0, "create-project", "bootstrap")
        self.assertEqual(handler.handle(project, authenticated_actor_id="bootstrap").status, "accepted")
        # Register two ordinary agents; human_owner remains a governance principal,
        # not an Agent Registry identity.
        for agent_id, model_id in (("a-1", "model-a1"), ("a-2", "model-a2")):
            agent = Command(f"register-{agent_id}", project_id, "bootstrap", "agent.register", agent_id,
                            {"model_id": model_id, "status": "available"}, 0, f"register-{agent_id}", "bootstrap")
            self.assertEqual(handler.handle(agent, authenticated_actor_id="bootstrap").status, "accepted")

        planning = PlanningService(store, owner_id="human-owner")
        gov = policy("gov-finalize-auth")
        gov_command = Command("configure-governance", project_id, "human-owner", "project.governance.configure",
                              project_id, {"policy": gov}, 0, "configure-governance", "bootstrap")
        self.assertEqual(planning.handle(gov_command, authenticated_actor_id="human-owner").status, "accepted")
        plan_command = Command("configure-planning", project_id, "human-owner", "project.planning.configure",
                               project_id, {"mode": "candidate_only"}, 1, "configure-planning", "bootstrap")
        self.assertEqual(planning.handle(plan_command, authenticated_actor_id="human-owner").status, "accepted")

        # Seed the completed bootstrap mission using the normal planning lifecycle.
        mission = Command("propose-m0", project_id, "a-1", "mission.propose", "mission-0-bootstrap", {
            "content": {"title": "Bootstrap", "objective": "Initialize", "constraints": [],
                        "success_criteria": ["B0-B5 verified"]}
        }, 0, "propose-m0", "bootstrap")
        self.assertEqual(planning.handle(mission, authenticated_actor_id="a-1").status, "accepted")
        activate = Command("activate-m0", project_id, "human-owner", "mission.activate", "mission-0-bootstrap",
                           {}, 0, "activate-m0", "bootstrap")
        self.assertEqual(planning.handle(activate, authenticated_actor_id="human-owner").status, "accepted")
        start = Command("start-m0-acceptance", project_id, "human-owner", "mission.acceptance_start",
                        "mission-0-bootstrap", {}, 1, "start-m0-acceptance", "bootstrap")
        self.assertEqual(planning.handle(start, authenticated_actor_id="human-owner").status, "accepted")
        verify = Command("verify-m0", project_id, "a-1", "mission.verify", "mission-0-bootstrap", {
            "criterion": "B0-B5 verified", "result": "PASSED",
            "evidence": {"artifact_id": "bootstrap-proof", "content_digest": "sha256:" + "a" * 64},
            "verifier_id": "a-1",
        }, 2, "verify-m0", "bootstrap")
        self.assertEqual(planning.handle(verify, authenticated_actor_id="a-1").status, "accepted")
        complete = Command("complete-m0", project_id, "human-owner", "mission.complete", "mission-0-bootstrap",
                           {}, 3, "complete-m0", "bootstrap")
        self.assertEqual(planning.handle(complete, authenticated_actor_id="human-owner").status, "accepted")

        before_events = store.read_events(project_id)
        before_project = store.read_projection(project_id)[f"project:{project_id}"]
        forbidden = Command("forbidden-finalize", project_id, "a-1", "project.bootstrap.finalize",
                            project_id, {"mission_id": "mission-0-bootstrap"}, before_project["revision"],
                            "forbidden-finalize", "bootstrap")
        rejected = planning.handle(forbidden, authenticated_actor_id="a-1")
        self.assertEqual(rejected.status, "rejected")
        self.assertEqual(rejected.error_code, "PERMISSION_DENIED")
        after_project = store.read_projection(project_id)[f"project:{project_id}"]
        self.assertEqual(after_project["revision"], before_project["revision"])
        self.assertNotEqual(after_project.get("phase"), "BOOTSTRAP_VERIFIED")
        after_events = store.read_events(project_id)
        self.assertFalse(any(event.type == "project.bootstrap_verified" for event in after_events))
        self.assertEqual(len(after_events), len(before_events) + 2)  # only command.received/rejected audit facts
        store.close()

    def test_human_owner_finalize_persists_event_and_replay_matches_projection(self):
        """Valid finalization must be a durable Event whose pure replay matches cached Projection."""
        # The full runner already constructs Mission #0, verifies B0-B5, and invokes
        # project.bootstrap.finalize. Reopen its real SQLite store and inspect facts.
        report = run_project_bootstrap(self.db_path)
        self.assertEqual(report["verdict"], "BOOTSTRAP_VERIFIED")
        store = SQLiteStore.open(self.db_path)
        events = store.read_events("p-bootstrap")
        self.assertTrue(any(event.type == "project.bootstrap_verified" for event in events))
        replayed = Projection.rebuild(events)
        cached = store.read_projection("p-bootstrap")
        self.assertEqual(replayed, cached)
        project = replayed["project:p-bootstrap"]
        self.assertEqual(project["phase"], "BOOTSTRAP_VERIFIED")
        self.assertEqual(project["bootstrap_status"], "verified")
        store.close()
