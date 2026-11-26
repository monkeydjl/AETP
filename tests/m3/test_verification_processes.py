"""Actual processes compete at the shared grant/OS gate; no Session is copied."""

import multiprocessing
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from aetp.acceptance.runner import FixedJsonRunner
from aetp.acceptance.service import AcceptanceService
from aetp.core.projection import Projection
from aetp.domain.models import Command
from aetp.storage.sqlite_store import SQLiteStore
from tests.m3.verification_scenario import VerificationScenario


def verification_worker(root, mode, output, release):
    try:
        with SQLiteStore.open(str(Path(root) / "facts.sqlite")) as store:
            scenario = VerificationScenario(store, Path(root) / "workspace")
            scenario.write()
            scenario.request()
            original = FixedJsonRunner.run

            def controlled(runner, content, cases):
                output.send({"phase": "in_flight", "pid": os.getpid(), "transaction": store.in_transaction})
                if mode == "crash":
                    os._exit(73)
                if not release.wait(15):
                    raise AssertionError("parent did not release real invocation")
                return original(runner, content, cases)

            with patch.object(FixedJsonRunner, "run", controlled):
                result = scenario.service.dispatch("p-1", "v-1", session=scenario.qa_session)
            output.send({"phase": "finished", "result": result["result"]})
    except BaseException as exc:
        output.send({"phase": "error", "error": type(exc).__name__, "detail": str(exc)})
    finally:
        output.close()


def revocation_worker(database, output):
    try:
        with SQLiteStore.open(database) as store:
            service = AcceptanceService(store, clock=lambda: 1000)
            current = store.read_projection("p-1")["verification:v-1"]
            command = Command("process-revoke", "p-1", "human-owner", "verification.revoke", "v-1",
                {"reason": "Competing human revocation"}, current["revision"], "process-revoke", "process-race")
            output.send({"phase": "attempting", "pid": os.getpid()})
            result = service.handle(command, authenticated_actor_id="human-owner")
            output.send({"phase": "result", "result": result.to_dict()})
    except BaseException as exc:
        output.send({"phase": "error", "error": type(exc).__name__, "detail": str(exc)})
    finally:
        output.close()


class VerificationProcessTests(unittest.TestCase):
    def setUp(self):
        directory = Path(__file__).resolve().parents[2] / ".tmp"
        directory.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(prefix="verification-process-", dir=directory)
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def launch(self, mode):
        context = multiprocessing.get_context("spawn")
        parent, child = context.Pipe()
        release = context.Event()
        worker = context.Process(target=verification_worker, args=(str(self.root), mode, child, release))
        worker.start()
        child.close()
        self.addCleanup(parent.close)

        def cleanup():
            release.set()
            worker.join(10)
            if worker.is_alive():
                worker.terminate()
                worker.join(10)
        self.addCleanup(cleanup)
        self.assertTrue(parent.poll(20), "worker did not reach actual Runner boundary")
        observation = parent.recv()
        self.assertEqual(observation["phase"], "in_flight", observation)
        self.assertNotEqual(observation["pid"], os.getpid())
        self.assertFalse(observation["transaction"])
        return context, worker, parent, release

    def test_real_process_crash_is_recovered_without_new_invocation(self):
        _, worker, _, _ = self.launch("crash")
        worker.join(10)
        self.assertEqual(worker.exitcode, 73)
        with SQLiteStore.open(str(self.root / "facts.sqlite")) as store:
            service = AcceptanceService(store, clock=lambda: 1000)
            self.assertEqual(store.read_projection("p-1")["verification:v-1"]["action"]["status"], "in_flight")
            with patch.object(FixedJsonRunner, "run", side_effect=AssertionError("recovery ran lost Action")):
                rows = service.recover_verifications("p-1")
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["result"], "INCONCLUSIVE")
            self.assertEqual(rows[0]["action"]["status"], "abandoned")
            self.assertEqual(rows[0]["action"]["dispatch_count"], 1)

    def test_other_process_cannot_revoke_inside_actual_fixed_call(self):
        context, worker, output, release = self.launch("delayed")
        parent, child = context.Pipe()
        revoker = context.Process(target=revocation_worker, args=(str(self.root / "facts.sqlite"), child))
        revoker.start()
        child.close()
        try:
            self.assertTrue(parent.poll(15))
            attempted = parent.recv()
            self.assertEqual(attempted["phase"], "attempting", attempted)
            self.assertFalse(parent.poll(0.15), "revocation crossed the held resource gate")
            release.set()
            self.assertTrue(output.poll(15))
            self.assertEqual(output.recv(), {"phase": "finished", "result": "PASSED"})
            self.assertTrue(parent.poll(15))
            rejected = parent.recv()
            self.assertEqual(rejected["phase"], "result", rejected)
            self.assertEqual(rejected["result"]["error_code"], "REVISION_CONFLICT")
            worker.join(10)
            revoker.join(10)
            self.assertEqual((worker.exitcode, revoker.exitcode), (0, 0))
            with SQLiteStore.open(str(self.root / "facts.sqlite")) as store:
                events = store.read_events("p-1")
                final = Projection.rebuild(events)["verification:v-1"]
                self.assertEqual(final["result"], "PASSED")
                self.assertEqual(final["action"]["dispatch_count"], 1)
                self.assertFalse(final["grant"]["revoked"])
        finally:
            release.set()
            revoker.join(10)
            if revoker.is_alive():
                revoker.terminate()
                revoker.join(10)
            parent.close()

    def test_two_threads_with_genuine_same_session_consume_grant_once(self):
        with SQLiteStore.open(str(self.root / "facts.sqlite")) as store:
            scenario = VerificationScenario(store, self.root / "workspace")
            scenario.write()
            scenario.request()
            observed = []
            original = FixedJsonRunner.run

            def counted(runner, content, cases):
                observed.append(1)
                return original(runner, content, cases)

            with patch.object(FixedJsonRunner, "run", counted), ThreadPoolExecutor(max_workers=2) as executor:
                futures = [executor.submit(scenario.service.dispatch, "p-1", "v-1", session=scenario.qa_session) for _ in range(2)]
                results = [future.result(timeout=20) for future in futures]
            self.assertEqual(results[0], results[1])
            self.assertEqual(results[0]["result"], "PASSED")
            self.assertEqual(len(observed), 1)
            self.assertEqual([event.type for event in store.read_events("p-1")].count("verification.dispatched"), 1)
