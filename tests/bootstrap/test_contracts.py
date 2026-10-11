"""Unit tests for Project Bootstrap contracts and reducers."""

import unittest
from aetp.bootstrap.contracts import AGGREGATES, COMMAND_AGGREGATES, DOMAIN_EVENTS
from aetp.bootstrap.records import evaluate_bootstrap_finalize, reduce_bootstrap_event
from aetp.collaboration.policy import PolicyViolation
from aetp.domain.models import Command, Event, ModelValidationError


class BootstrapContractsTests(unittest.TestCase):
    def test_bootstrap_contracts_registered(self):
        self.assertIn("project.bootstrap.finalize", COMMAND_AGGREGATES)
        self.assertIn("project.bootstrap_verified", DOMAIN_EVENTS)
        self.assertEqual(AGGREGATES.get("bootstrap"), "project")

    def _sample_state(self, mission_status="completed", actor="human-owner"):
        pol = {
            "version": "gov-1",
            "subjects": {
                "human-owner": {"type": "human", "roles": ["human_owner"]},
                "a-1": {"type": "agent", "roles": ["engineer"]},
            },
        }
        return {
            "project:p-1": {
                "id": "p-1",
                "revision": 1,
                "status": "planning",
                "governance": {
                    "current_version": "gov-1",
                    "versions": {"gov-1": {"policy": pol}},
                },
            },
            "mission:mission-0-bootstrap": {"status": mission_status},
        }

    def test_evaluate_bootstrap_finalize_requires_human_owner(self):
        state = self._sample_state()
        cmd = Command("cmd-1", "p-1", "a-1", "project.bootstrap.finalize", "p-1", {}, 1, "k-1", "corr")
        with self.assertRaises(PolicyViolation) as ctx:
            evaluate_bootstrap_finalize(cmd, state, 100)
        self.assertEqual(ctx.exception.code, "PERMISSION_DENIED")

    def test_evaluate_bootstrap_finalize_requires_completed_mission(self):
        state = self._sample_state(mission_status="active")
        cmd = Command("cmd-1", "p-1", "human-owner", "project.bootstrap.finalize", "p-1", {}, 1, "k-1", "corr")
        with self.assertRaises(PolicyViolation) as ctx:
            evaluate_bootstrap_finalize(cmd, state, 100)
        self.assertEqual(ctx.exception.code, "BOOTSTRAP_MISSION_INCOMPLETE")

    def test_evaluate_bootstrap_finalize_success(self):
        state = self._sample_state(mission_status="completed")
        cmd = Command("cmd-1", "p-1", "human-owner", "project.bootstrap.finalize", "p-1", {}, 1, "k-1", "corr")
        event_type, record = evaluate_bootstrap_finalize(cmd, state, 100)
        self.assertEqual(event_type, "project.bootstrap_verified")
        self.assertEqual(record["phase"], "BOOTSTRAP_VERIFIED")
        self.assertEqual(record["bootstrap_status"], "verified")
        self.assertEqual(record["revision"], 2)

    def test_reduce_bootstrap_event(self):
        prev = {"id": "p-1", "revision": 1, "status": "planning"}
        event = Event(
            id="e-1",
            project_id="p-1",
            sequence=2,
            type="project.bootstrap_verified",
            aggregate_type="project",
            aggregate_id="p-1",
            aggregate_revision=1,
            causation_id="c-1",
            correlation_id="k-1",
            payload={
                "bootstrap_mission_id": "mission-0-bootstrap",
                "bootstrap_verified_at_ms": 100,
            },
        )
        reduced = reduce_bootstrap_event(event, prev, {})
        self.assertEqual(reduced["phase"], "BOOTSTRAP_VERIFIED")
        self.assertEqual(reduced["bootstrap_status"], "verified")
        self.assertEqual(reduced["revision"], 2)
