from tests.m2.support import MeetingCase


class MeetingTests(MeetingCase):
    def test_forged_actor_and_private_id_retry_do_not_reveal_another_answer(self):
        self.begin_meeting()
        entry = self.contribution("m", category="analysis", content="private first-round answer", identifier="secret")
        receipt = self.meter.issue(entry, call_id="private", tokens=7)
        self.service.post(entry, authenticated_actor_id="a-1", receipt=receipt)
        with self.assertRaisesRegex(Exception, "ACTOR_MISMATCH"):
            self.service.post(entry, authenticated_actor_id="a-2", receipt=receipt)
        with self.assertRaisesRegex(Exception, "MESSAGE_ID_CONFLICT"):
            self.post("m", actor="a-2", identifier="secret", category="analysis")
        self.assertNotIn("private", str(self.usage("m")))
        self.assertEqual(self.transcript("m", actor="a-2"), [])

    def test_only_new_valid_artifacts_reset_the_no_evidence_round_counter(self):
        self.ready_debate(max_rounds=6, no_new_evidence_rounds=2)
        self.accept(self.command("meeting.advance", "m"))
        self.assertEqual(self.state()["meeting:m"]["no_new_evidence"], 1)
        self.accept(self.command("task.create", "evidence-task", {"title": "Document evidence", "acceptance_criteria": ["fact"]}))
        self.accept(self.command("artifact.submit", "evidence", {"task_id": "evidence-task", "type": "document", "content": "fact"}))
        artifact = self.state()["artifact:evidence"]
        ref = {"artifact_id": artifact["id"], "content_digest": artifact["content_digest"]}
        self.post("m", evidence=(ref,), category="evidence")
        self.accept(self.command("meeting.advance", "m"))
        self.assertEqual(self.state()["meeting:m"]["no_new_evidence"], 0)
        for index in range(2):
            self.post("m", evidence=(ref,), identifier=f"repeat-proof-{index}", category="evidence")
            self.accept(self.command("meeting.advance", "m"))
        self.assertEqual(self.state()["meeting:m"]["termination_reason"], "no_new_evidence")
        decision = self.propose("m")
        self.assertEqual(decision["source"]["checkpoint"]["evidence"], [ref])
        self.assertTrue(all(row["untrusted_input"] for row in decision["source"]["records"]))

    def test_first_round_is_blind_on_both_participant_read_paths(self):
        self.begin_meeting()
        self.post("m", category="analysis", content="secret independent A", identifier="answer-A")
        self.assertEqual(self.transcript("m", actor="a-2"), [])
        self.assertEqual([row["content"] for row in self.transcript("m")], ["secret independent A"])
        self.post("m", actor="a-2", category="analysis", content="secret independent B")
        self.assertEqual([row["content"] for row in self.transcript("m", actor="a-2")], ["secret independent B"])
        self.assertNotIn("secret independent", self.event_text())
        self.accept(self.command("meeting.advance", "m", actor="a-2"))
        self.assertEqual(len(self.transcript("m", actor="a-2")), 2)

    def test_first_round_cannot_be_bypassed_by_reference_or_early_proposal(self):
        self.begin_meeting()
        self.post("m", category="analysis", identifier="secret", content="private")
        with self.assertRaisesRegex(Exception, "REFERENCE_NOT_VISIBLE"):
            self.post("m", actor="a-2", category="analysis", references=("secret",))
        self.reject(self.command("decision.propose", "early", {
            "title": "x", "choice": "A", "alternatives": ["A", "B"], "reasoning": "x",
            "source": {"kind": "meeting", "id": "m", "revision": 2}}), "SOURCE_NOT_READY")
        self.assertNotIn("private", self.event_text())

    def test_analysis_requires_one_answer_from_each_participant_before_debate(self):
        self.begin_meeting()
        self.post("m", category="analysis")
        self.reject(self.command("meeting.advance", "m"), "ANALYSIS_INCOMPLETE")
        with self.assertRaisesRegex(Exception, "ANALYSIS_ALREADY_SUBMITTED"):
            self.post("m", category="analysis")
        with self.assertRaisesRegex(Exception, "INVALID_PHASE"):
            self.post("m", actor="a-2", category="opinion")

    def test_budget_during_analysis_reveals_existing_answers_without_inventing_missing_ones(self):
        self.begin_meeting(token_budget=3)
        self.post("m", category="analysis", position="A", content="my own view", tokens=3)
        self.assertEqual(self.state()["meeting:m"]["status"], "synthesis")
        self.assertEqual(len(self.transcript("m", actor="a-2")), 1)
        decision = self.propose("m")
        self.assertEqual(decision["missing_participants"], ["a-2"])
        self.assertEqual(decision["supporting_agents"], ["a-1"])

    def test_max_rounds_and_no_new_evidence_are_real_termination_conditions(self):
        self.ready_debate(max_rounds=1)
        self.accept(self.command("meeting.advance", "m"))
        self.assertEqual(self.state()["meeting:m"]["status"], "synthesis")
        self.assertEqual(self.state()["meeting:m"]["termination_reason"], "max_rounds")

    def test_repeated_opinions_do_not_count_as_new_evidence(self):
        self.ready_debate(max_rounds=5, no_new_evidence_rounds=2)
        self.post("m", category="opinion", content="I think this proves it")
        self.accept(self.command("meeting.advance", "m"))
        self.post("m", category="opinion", content="I think this proves it again")
        self.accept(self.command("meeting.advance", "m"))
        self.assertEqual(self.state()["meeting:m"]["termination_reason"], "no_new_evidence")

    def test_unanimity_only_converges_it_does_not_activate_a_decision(self):
        self.ready_debate()
        self.post("m", position="A", category="agreement")
        self.post("m", actor="a-2", position="A", category="agreement")
        self.assertEqual(self.state()["meeting:m"]["status"], "synthesis")
        self.assertFalse(any(key.startswith("decision:") for key in self.state()))
        proposal = self.propose("m")
        self.assertEqual((proposal["consensus_level"], proposal["status"]), (1.0, "proposed"))
        self.reject(self.command("decision.activate", proposal["id"]), "ENFORCEMENT_UNAVAILABLE")

    def test_full_meeting_lifecycle_binds_its_own_proposal(self):
        self.ready_debate()
        self.synthesize("m")
        self.reject(self.command("meeting.close", "m"), "INVALID_PHASE")
        decision = self.propose("m")
        self.accept(self.command("meeting.advance", "m", {"decision_id": decision["id"]}))
        self.accept(self.command("meeting.close", "m"))
        self.assertEqual(self.state()["meeting:m"]["status"], "closed")
        self.assertEqual(self.state()["decision:decision-1"]["status"], "proposed")
