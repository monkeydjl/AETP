from tests.m2.support import MeetingCase


class DiscussionTests(MeetingCase):
    def test_nonparticipant_cannot_read_accounting_or_material(self):
        self.open_discussion()
        self.accept(self.command("agent.register", "a-3", {"model_id": "model-3"}, actor="bootstrap"))
        for endpoint in (self.service.transcript, self.service.usage, self.service.compact):
            with self.subTest(endpoint=endpoint.__name__), self.assertRaisesRegex(Exception, "PERMISSION_DENIED"):
                endpoint("p-1", "discussion", "d", authenticated_actor_id="a-3")

    def test_missing_or_wrong_digest_artifact_is_not_accepted_as_evidence(self):
        self.open_discussion()
        with self.assertRaisesRegex(Exception, "INVALID_REFERENCE"):
            self.post("d", evidence=({"artifact_id": "missing", "content_digest": "sha256:fake"},))
        self.assertEqual(self.usage("d")["messages"], 0)

    def test_peer_without_a_task_can_open_and_speak_without_creating_events(self):
        self.open_discussion()
        before = len(self.store.read_events("p-1"))
        for i in range(12):
            self.post("d", actor="a-2", identifier=f"opinion-{i}", content="still a process opinion")
        self.assertEqual(len(self.store.read_events("p-1")), before)
        self.assertEqual(len(self.transcript("d")), 12)
        self.assertEqual(self.state()["discussion:d"]["status"], "open")
        self.assertNotIn("still a process opinion", self.event_text())
        self.assertFalse(any(key.startswith("task:") for key in self.state()))

    def test_nonmember_and_cross_project_participant_cannot_open(self):
        payload = {"topic": "x", "participants": ["a-1", "unknown"], "moderator_id": "a-1"}
        self.reject(self.command("discussion.open", "d", payload), "INVALID_PARTICIPANT")
        self.reject(self.command("discussion.open", "d", {"topic": "x", "participants": ["unknown"]}, actor="unknown"), "PERMISSION_DENIED")

    def test_command_actor_mismatch_cannot_reserve_identity(self):
        command = self.command("discussion.open", "d", {"topic": "x", "participants": ["a-1", "a-2"]})
        before = len(self.store.read_events("p-1"))
        result = self.service.handle(command, authenticated_actor_id="a-2")
        self.assertEqual(result.error_code, "ACTOR_MISMATCH")
        self.assertEqual(len(self.store.read_events("p-1")), before)
        self.accept(command)

    def test_old_revision_cannot_close_or_reopen_a_process(self):
        self.open_discussion()
        self.synthesize("d")
        self.reject(self.command("discussion.synthesize", "d", {"reason": "moderator_decision"}, revision=0), "REVISION_CONFLICT")
        self.assertEqual(self.state()["discussion:d"]["status"], "synthesizing")

    def test_moderator_can_end_agenda_but_peer_cannot_impersonate_it(self):
        self.open_discussion()
        self.reject(self.command("discussion.synthesize", "d", {"reason": "moderator_decision"}, actor="a-2"), "PERMISSION_DENIED")
        self.synthesize("d")
        self.assertEqual(self.state()["discussion:d"]["termination_reason"], "moderator_decision")

    def test_no_consensus_does_not_prevent_a_peer_proposal(self):
        self.open_discussion()
        self.post("d", actor="a-1", position="A")
        self.post("d", actor="a-2", position="B", category="disagreement", content="B is safer")
        self.synthesize("d")
        result = self.propose("d", actor="a-2", choice="B")
        self.assertEqual(result["status"], "proposed")
        self.assertEqual(result["supporting_agents"], ["a-2"])

    def test_existing_process_id_and_duplicate_message_content_are_immutable(self):
        self.open_discussion()
        self.reject(self.command("discussion.open", "d", {"topic": "replacement", "participants": ["a-1"]}), "REVISION_CONFLICT")
        self.post("d", identifier="fixed", content="original")
        with self.assertRaisesRegex(Exception, "MESSAGE_ID_CONFLICT"):
            self.post("d", identifier="fixed", content="replacement")
        self.assertEqual(self.transcript("d")[0]["content"], "original")
