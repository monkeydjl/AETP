"""Independent writer processes compete on the shared SQLite facts."""

import multiprocessing
import os

from aetp.core.projection import Projection
from tests.m3.support import PlanningCase


def planning_worker(path, mode, command_data, ready, go, output):
    from aetp.core.commands import CommandHandler
    from aetp.domain.models import Command
    from aetp.planning.service import PlanningService
    from aetp.storage.sqlite_store import SQLiteStore
    try:
        with SQLiteStore.open(path) as store:
            service = CommandHandler(store) if mode == "core" else PlanningService(store, clock=lambda: 1000)
            command = Command.from_dict(command_data)
            ready.put(os.getpid())
            if not go.wait(15):
                raise TimeoutError("writer release not received")
            output.put(service.handle(command, authenticated_actor_id=command.actor_id).to_dict())
    except BaseException as exc:
        output.put({"error": type(exc).__name__, "detail": str(exc)})


class ProcessCase(PlanningCase):
    def compete(self, submissions):
        context = multiprocessing.get_context("spawn")
        ready, output, go = context.Queue(), context.Queue(), context.Event()
        workers = [context.Process(target=planning_worker, args=(self.fixture.db_path, mode, command.to_dict(), ready, go, output))
                   for mode, command in submissions]
        try:
            for worker in workers:
                worker.start()
            for _ in workers:
                self.assertNotEqual(ready.get(timeout=15), os.getpid())
            go.set()
            results = [output.get(timeout=20) for _ in workers]
            for worker in workers:
                worker.join(10)
                self.assertEqual(worker.exitcode, 0)
            self.assertFalse(any("error" in result for result in results), results)
            return results
        finally:
            for worker in workers:
                if worker.is_alive():
                    worker.terminate()
                worker.join(5)
            ready.close()
            output.close()


class PlanningVersionProcessTests(ProcessCase):
    def test_two_reverse_dependency_changes_on_one_base_cannot_both_commit(self):
        self.team()
        content = self.blueprint_content()
        content["tasks"] = [self.task_content("a"), self.task_content("b")]
        self.blueprint(content=content)
        first = self.blueprint_content()
        first["tasks"] = [self.task_content("a", [{"type": "task", "id": "b"}]), self.task_content("b")]
        second = self.blueprint_content()
        second["tasks"] = [self.task_content("a"), self.task_content("b", [{"type": "task", "id": "a"}])]
        commands = [self.change(first, actor="a-1"), self.change(second, actor="a-2")]
        results = self.compete([("planning", command) for command in commands])
        self.assertEqual(sorted(result["status"] for result in results), ["accepted", "rejected"])
        self.assertEqual(next(result["error_code"] for result in results if result["status"] == "rejected"), "REVISION_CONFLICT")
        candidate = self.candidate("blueprint", "bp-1")
        self.assertEqual(candidate["version"], 2)
        self.assertEqual(len(candidate["dag"]["edges"]), 1)
        self.assertEqual(Projection.pending_command_ids(self.store.read_events("p-1"), self.commands()), [])

    def test_identical_proposal_in_two_processes_has_one_domain_effect(self):
        self.team()
        command = self.command("blueprint.propose", "bp-1", {"content": self.blueprint_content()})
        results = self.compete([("planning", command), ("planning", command)])
        self.assertEqual(results[0], results[1])
        self.assertEqual(results[0]["status"], "accepted")
        self.assertEqual(sum(event.type == "blueprint.proposed" for event in self.store.read_events("p-1")), 1)


class PlanningConfigurationProcessTests(ProcessCase):
    configure_scope = False

    def test_configuration_races_legacy_task_creation_in_final_writer_transaction(self):
        configure = self.command("project.planning.configure", "p-1", {"mode": "candidate_only"}, actor="human-owner")
        create = self.command("task.create", "legacy-task", {"title": "No planning metadata"})
        results = self.compete([("planning", configure), ("core", create)])
        self.assertEqual(sorted(result["status"] for result in results), ["accepted", "rejected"])
        state = self.state()
        scoped = "planning" in state["project:p-1"]
        self.assertNotEqual(scoped, "task:legacy-task" in state)
        self.assertEqual(next(result["error_code"] for result in results if result["status"] == "rejected"),
                         "PLANNING_NOT_ACTIVE" if scoped else "TASK_GRAPH_ALREADY_EXISTS")
