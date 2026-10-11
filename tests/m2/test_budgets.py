from dataclasses import replace
import multiprocessing
import sqlite3

from aetp.storage.sqlite_store import SQLiteStore
from tests.m0.support import install_event_failure_fixture
from tests.m2 import support
from tests.m2.support import MeetingCase, admission_worker


class BudgetTests(MeetingCase):
    def test_source_namespace_cannot_change_to_obtain_fresh_allowance(self):
        self.open_discussion()
        meter = support.MeteringAuthority("different-source")
        service = support.MeetingService(self.store, meter=meter, clock=lambda: 1000)
        entry = self.contribution("d")
        with self.assertRaisesRegex(Exception, "INVALID_USAGE_RECEIPT"):
            service.post(entry, authenticated_actor_id="a-1", receipt=meter.issue(entry, call_id="c", tokens=1))

    def test_receipt_call_remains_consumed_after_process_compaction(self):
        self.open_discussion()
        self.post("d", call_id="persist-through-compaction")
        self.synthesize("d")
        decision = self.propose("d")
        self.accept(self.command("discussion.close", "d", {"decision_id": decision["id"]}))
        self.service.compact("p-1", "discussion", "d", authenticated_actor_id="a-1")
        self.open_discussion("second")
        with self.assertRaisesRegex(Exception, "USAGE_ALREADY_CONSUMED"):
            self.post("second", call_id="persist-through-compaction")

    def test_discussion_rejects_inapplicable_round_budgets(self):
        for field in ("max_rounds", "no_new_evidence_rounds"):
            self.reject(self.command("discussion.open", field, {
                "topic": "x", "participants": ["a-1", "a-2"], "policy": {field: 2}}), "INVALID_PAYLOAD")

    def test_later_wall_clock_cannot_move_back_before_uncheckpointed_material(self):
        self.open_discussion()
        self.clock_value = 1005
        self.post("d")
        self.clock_value = 1004
        with self.assertRaisesRegex(Exception, "CLOCK_REGRESSION"):
            self.post("d")
        self.assertEqual(self.usage("d")["messages"], 1)

    def test_process_marker_and_consumption_loss_cannot_reopen_allowance(self):
        self.open_discussion(token_budget=8)
        self.post("d", tokens=6)
        self.store._ensure_open().execute("DELETE FROM collaboration_processes")
        with self.assertRaisesRegex(Exception, "PROCESS_UNRECONCILED"):
            self.post("d", tokens=1)

    def test_exact_budget_closes_atomically_and_retries_do_not_consume_twice(self):
        self.open_discussion(token_budget=10)
        self.post("d", tokens=7)
        entry = self.contribution("d", identifier="last")
        receipt = self.meter.issue(entry, call_id="last-call", tokens=3)
        self.service.post(entry, authenticated_actor_id="a-1", receipt=receipt)
        before = len(self.store.read_events("p-1"))
        self.service.post(entry, authenticated_actor_id="a-1", receipt=receipt)
        self.assertEqual(self.usage("d")["tokens"], 10)
        self.assertEqual(len(self.store.read_events("p-1")), before)
        self.assertEqual(self.state()["discussion:d"]["status"], "synthesizing")

    def test_oversized_admission_is_rejected_without_claiming_provider_refund(self):
        self.open_discussion(token_budget=5)
        self.post("d", tokens=3)
        with self.assertRaisesRegex(Exception, "BUDGET_EXCEEDED"):
            self.post("d", tokens=3)
        self.assertEqual(self.usage("d")["tokens"], 3)
        self.assertEqual(len(self.transcript("d")), 1)

    def test_missing_or_copied_meter_receipt_cannot_grant_usage(self):
        self.open_discussion()
        entry = self.contribution("d")
        with self.assertRaisesRegex(Exception, "ENFORCEMENT_UNAVAILABLE"):
            self.service.post(entry, authenticated_actor_id="a-1", receipt=None)
        receipt = self.meter.issue(entry, call_id="call", tokens=2)
        with self.assertRaisesRegex(Exception, "INVALID_USAGE_RECEIPT"):
            self.service.post(entry, authenticated_actor_id="a-1", receipt=replace(receipt))
        self.assertEqual(self.usage("d")["tokens"], 0)

    def test_receipt_binds_context_references_and_complete_message_identity(self):
        self.open_discussion()
        entry = self.contribution("d", context="private context")
        receipt = self.meter.issue(entry, call_id="call", tokens=2)
        with self.assertRaisesRegex(Exception, "INVALID_USAGE_RECEIPT"):
            self.service.post(replace(entry, context="changed context"), authenticated_actor_id="a-1", receipt=receipt)

    def test_call_cannot_be_reminted_after_service_restart(self):
        self.open_discussion()
        self.post("d", identifier="first", call_id="stable-provider-call", tokens=2)
        with SQLiteStore.open(self.fixture.db_path) as other:
            meter = support.MeteringAuthority("fixture-admission-meter")
            service = support.MeetingService(other, meter=meter, clock=lambda: 1000)
            entry = self.contribution("d", identifier="different")
            receipt = meter.issue(entry, call_id="stable-provider-call", tokens=2)
            with self.assertRaisesRegex(Exception, "USAGE_ALREADY_CONSUMED"):
                service.post(entry, authenticated_actor_id="a-1", receipt=receipt)
        self.assertEqual(self.usage("d")["tokens"], 2)

    def test_restart_preserves_remaining_budget(self):
        self.open_discussion(token_budget=10)
        self.post("d", tokens=7)
        with SQLiteStore.open(self.fixture.db_path) as other:
            meter = support.MeteringAuthority("fixture-admission-meter")
            service = support.MeetingService(other, meter=meter, clock=lambda: 1000)
            entry = self.contribution("d", identifier="after-restart")
            receipt = meter.issue(entry, call_id="new-call", tokens=3)
            service.post(entry, authenticated_actor_id="a-1", receipt=receipt)
        self.assertEqual(self.usage("d")["tokens"], 10)
        self.assertEqual(self.state()["discussion:d"]["status"], "synthesizing")

    def test_missing_process_material_cannot_reset_consumption(self):
        self.open_discussion(token_budget=10)
        self.post("d", tokens=7)
        self.store._ensure_open().execute("DELETE FROM collaboration_entries")
        with self.assertRaisesRegex(Exception, "PROCESS_UNRECONCILED"):
            self.post("d", tokens=4)
        self.assertEqual(self.state()["discussion:d"]["status"], "open")

    def test_budget_transition_failure_rolls_back_local_admission_and_receipt(self):
        self.open_discussion(token_budget=2)
        entry = self.contribution("d")
        receipt = self.meter.issue(entry, call_id="retryable-local-admission", tokens=2)
        remove = install_event_failure_fixture(self, self.store, "discussion.synthesizing")
        with self.assertRaises(ValueError) as failure:
            self.service.post(entry, authenticated_actor_id="a-1", receipt=receipt)
        self.assertIsInstance(failure.exception.__cause__, sqlite3.IntegrityError)
        self.assertEqual(self.usage("d")["tokens"], 0)
        self.assertEqual(self.transcript("d"), [])
        remove()
        self.service.post(entry, authenticated_actor_id="a-1", receipt=receipt)
        self.assertEqual(self.usage("d")["tokens"], 2)

    def test_deadline_blocks_new_speech_and_commits_synthesis(self):
        self.open_discussion(time_budget_ms=10)
        self.clock_value = 1010
        with self.assertRaisesRegex(Exception, "TIME_BUDGET_EXHAUSTED"):
            self.post("d")
        self.assertEqual(self.state()["discussion:d"]["status"], "synthesizing")
        self.assertEqual(self.usage("d")["tokens"], 0)

    def test_idle_tick_uses_host_clock_and_rejects_client_time(self):
        self.open_discussion(time_budget_ms=10)
        self.reject(self.command("discussion.tick", "d", {"now": 9000}), "INVALID_PAYLOAD")
        self.reject(self.command("discussion.tick", "d"), "NO_TERMINATION_CONDITION")
        self.clock_value = 1010
        self.accept(self.command("discussion.tick", "d"))
        self.assertEqual(self.state()["discussion:d"]["termination_reason"], "time_budget")

    def test_invalid_budget_and_usage_types_fail_closed(self):
        for value in (0, -1, True, 1.5, 10**30):
            with self.subTest(value=value):
                self.reject(self.command("discussion.open", f"d-{self.counter}", {
                    "topic": "x", "participants": ["a-1", "a-2"], "policy": {"token_budget": value}}), "INVALID_PAYLOAD")
        self.open_discussion()
        entry = self.contribution("d")
        for value in (0, -1, True, 1.5, 10**30):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.meter.issue(entry, call_id=f"bad-{value}", tokens=value)

    def test_synthesis_is_not_an_unmetered_chat_phase(self):
        self.open_discussion()
        self.synthesize("d")
        with self.assertRaisesRegex(Exception, "PROCESS_NOT_OPEN"):
            self.post("d")
        self.assertEqual(self.usage("d")["tokens"], 0)

    def test_two_processes_cannot_both_take_the_last_allowance(self):
        self.open_discussion(token_budget=5)
        entries = [self.contribution("d", identifier=f"race-{index}", actor=actor)
                   for index, actor in enumerate(("a-1", "a-2"))]
        ctx = multiprocessing.get_context("spawn")
        gate, output = ctx.Event(), ctx.Queue()
        processes = [ctx.Process(target=admission_worker, args=(self.fixture.db_path, entry.to_dict(),
                     f"race-call-{i}", gate, output)) for i, entry in enumerate(entries)]
        for process in processes:
            process.start()
        gate.set()
        results = [output.get(timeout=25) for _ in processes]
        for process in processes:
            process.join(25)
            self.assertEqual(process.exitcode, 0)
        self.assertEqual(sorted(row["status"] for row in results), ["accepted", "rejected"])
        self.assertEqual(self.usage("d")["tokens"], 5)
