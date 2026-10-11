"""Every admitted proposal identifier is usable; invalid JSON values are audited."""

from tests.m3.support import PlanningCase


class PlanningInputTests(PlanningCase):
    def test_creation_cannot_accept_identifiers_its_references_will_reject(self):
        self.team()
        cases = [("mission.propose", {"title": "Initial idea", "objective": "Write guide", "constraints": [],
                                      "success_criteria": ["Readable"]}),
                 ("team.propose", self.team_content()), ("blueprint.propose", self.blueprint_content())]
        for kind, content in cases:
            for identifier in ("x" * 513, "界" * 171):
                self.reject(self.command(kind, identifier, {"content": content}), "INVALID_PAYLOAD")
                self.assertNotIn(f"{kind.split('.')[0]}:{identifier}", self.state())

    def test_huge_json_estimate_is_a_typed_rejection_not_unhandled_overflow(self):
        self.mission()
        content = self.team_content()
        content["estimated_cost"]["amount"] = 10 ** 1000
        command = self.command("team.propose", "team-1", {"content": content})
        try:
            self.reject(command, "INVALID_PAYLOAD")
        except OverflowError:
            self.fail("JSON integer escaped the typed Command rejection path")
        self.assertIn(command.id, [saved.id for saved in self.commands()])

    def test_huge_confidence_is_a_typed_rejection_not_unhandled_overflow(self):
        self.mission()
        content = self.team_content()
        content["members"][0]["confidence"] = 10 ** 1000
        command = self.command("team.propose", "team-1", {"content": content})
        try:
            self.reject(command, "INVALID_TEAM")
        except OverflowError:
            self.fail("Out-of-range confidence escaped the typed Command rejection path")
        self.assertIn(command.id, [saved.id for saved in self.commands()])

    def test_identifier_at_byte_limit_can_be_referenced_and_revised(self):
        self.mission()
        identifier = "t" * 512
        self.accept(self.command("team.propose", identifier, {"content": self.team_content()}))
        self.accept(self.command("team.revise", identifier, {"base": self.ref("team", identifier),
            "content": self.team_content(), "reason": "Revision keeps an addressable identifier"}, actor="a-2"))
        self.assertEqual(self.candidate("team", identifier)["version"], 2)

    def test_negative_or_boolean_estimates_are_rejected(self):
        self.mission()
        for value in (-1, True):
            content = self.team_content()
            content["estimated_cost"]["amount"] = value
            self.reject(self.command("team.propose", "team-1", {"content": content}), "INVALID_PAYLOAD")
