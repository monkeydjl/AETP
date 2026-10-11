"""Mission Acceptance verification and delivery gate tests (TEST-010 / INV-019)."""

from aetp.core.projection import Projection
from tests.m3.support import PlanningCase


class MissionAcceptanceTests(PlanningCase):
    def setUp(self):
        super().setUp()
        self.mission_id = "mission-1"
        self.mission(self.mission_id)

    def activate_mission(self):
        cmd = self.command("mission.activate", self.mission_id, actor="human-owner")
        return self.accept(cmd)

    def start_acceptance(self):
        self.activate_mission()
        cmd = self.command("mission.acceptance_start", self.mission_id, actor="human-owner")
        return self.accept(cmd)

    def verify_criterion(self, criterion, result="PASSED", verifier="a-2"):
        payload = {
            "criterion": criterion,
            "result": result,
            "evidence": {
                "artifact_id": f"art-verify-{self.counter + 1}",
                "content_digest": "sha256:" + "a" * 64,
                "runner_id": "runner-1"
            },
            "verifier_id": verifier
        }
        cmd = self.command("mission.verify", self.mission_id, payload, actor=verifier)
        return self.accept(cmd)

    def test_unaccepted_mission_cannot_complete_inv_019(self):
        """Active mission cannot complete without entering acceptance state (INV-019)."""
        self.activate_mission()
        complete_cmd = self.command("mission.complete", self.mission_id, actor="human-owner")
        result = self.reject(complete_cmd, "MISSION_NOT_IN_ACCEPTANCE")
        self.assertEqual(result.error_code, "MISSION_NOT_IN_ACCEPTANCE")
        self.assertNotEqual(self.state()[f"mission:{self.mission_id}"]["status"], "completed")

    def test_mission_with_unverified_criteria_cannot_complete_test_010(self):
        """TEST-010: Mission cannot complete if any success criteria is unverified."""
        self.start_acceptance()
        # Only verify the first criterion out of two
        self.verify_criterion("Roles remain equal", result="PASSED")

        complete_cmd = self.command("mission.complete", self.mission_id, actor="human-owner")
        result = self.reject(complete_cmd, "CRITERIA_UNVERIFIED")
        self.assertEqual(result.error_code, "CRITERIA_UNVERIFIED")
        self.assertEqual(self.state()[f"mission:{self.mission_id}"]["status"], "acceptance")

    def test_mission_with_failed_or_inconclusive_criteria_cannot_complete(self):
        """TEST-010: Failed or inconclusive criteria blocks completion."""
        self.start_acceptance()
        self.verify_criterion("Roles remain equal", result="PASSED")
        self.verify_criterion("Recovery is explained", result="FAILED")

        complete_cmd = self.command("mission.complete", self.mission_id, actor="human-owner")
        result = self.reject(complete_cmd, "CRITERIA_UNVERIFIED")
        self.assertEqual(result.error_code, "CRITERIA_UNVERIFIED")

    def test_mission_completion_requires_human_owner_or_critical_approval(self):
        """Completion requires human_owner or CRITICAL approval authority (§9.4 / INV-019)."""
        self.start_acceptance()
        self.verify_criterion("Roles remain equal", result="PASSED")
        self.verify_criterion("Recovery is explained", result="PASSED")

        # Agent a-1 attempts completion
        complete_cmd = self.command("mission.complete", self.mission_id, actor="a-1")
        result = self.reject(complete_cmd, "CRITICAL_APPROVAL_REQUIRED")
        self.assertEqual(result.error_code, "CRITICAL_APPROVAL_REQUIRED")
        self.assertEqual(self.state()[f"mission:{self.mission_id}"]["status"], "acceptance")

    def test_mission_completion_success_with_all_criteria_passed_and_human_owner(self):
        """All criteria PASSED and human_owner actor enables successful completion."""
        self.start_acceptance()
        self.verify_criterion("Roles remain equal", result="PASSED")
        self.verify_criterion("Recovery is explained", result="PASSED")

        complete_cmd = self.command("mission.complete", self.mission_id, actor="human-owner")
        result = self.accept(complete_cmd)
        self.assertEqual(result.status, "accepted")
        self.assertEqual(self.state()[f"mission:{self.mission_id}"]["status"], "completed")

    def test_deterministic_replay_of_mission_acceptance_events(self):
        """Replaying mission acceptance events deterministically reconstructs state."""
        self.start_acceptance()
        self.verify_criterion("Roles remain equal", result="PASSED")
        self.verify_criterion("Recovery is explained", result="PASSED")
        self.accept(self.command("mission.complete", self.mission_id, actor="human-owner"))

        events = self.store.read_events("p-1")
        replayed = Projection.rebuild(events)
        self.assertEqual(replayed[f"mission:{self.mission_id}"]["status"], "completed")
