import json
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path

from aetp.domain import models
from aetp.storage.sqlite_store import SQLiteStore

ROOT = Path(__file__).resolve().parents[2]
VALID_FIXTURES = ROOT / "schemas" / "m0" / "valid"
INVALID_FIXTURES = ROOT / "schemas" / "m0" / "invalid"

MODEL_TYPES = {
    "project": models.Project,
    "agent": models.Agent,
    "task": models.Task,
    "command": models.Command,
    "event": models.Event,
}
INVALID_MODEL_TYPES = {
    "missing_id": models.Project,
    "unsupported_type": models.Command,
    "negative_revision": models.Task,
    "empty_idempotency_key": models.Command,
}


def load_fixture(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    return MODEL_TYPES[path.stem].from_dict(data)


class ModelTests(unittest.TestCase):
    def test_command_serializes_with_stable_required_fields(self):
        command = models.Command(
            "c-1",
            "p-1",
            "a-1",
            "task.create",
            None,
            {"title": "demo"},
            0,
            "k-1",
            "corr-1",
        )
        self.assertEqual(command.to_dict()["idempotency_key"], "k-1")
        self.assertEqual(
            command.to_json(),
            '{"actor_id":"a-1","correlation_id":"corr-1","expected_revision":0,"id":"c-1","idempotency_key":"k-1","payload":{"title":"demo"},"project_id":"p-1","target_id":null,"type":"task.create"}',
        )

    def test_package_exports_core_contracts(self):
        import aetp

        self.assertEqual(aetp.__version__, "0.1")
        self.assertIs(aetp.Project, models.Project)
        self.assertIs(aetp.Agent, models.Agent)
        self.assertIs(aetp.Task, models.Task)
        self.assertIs(aetp.Command, models.Command)
        self.assertIs(aetp.Event, models.Event)

    def test_models_are_frozen_and_expose_object_schema_version(self):
        objects = [
            models.Project("p-1", 0, "planning"),
            models.Agent("a-1", "p-1", "model-1", "available"),
            models.Task("t-1", "p-1", "Demo", "pending", 0),
            models.Command("c-1", "p-1", "a-1", "task.create", None, {}, 0, "k-1", "corr-1"),
            models.Event("e-1", "p-1", 1, "task.created", "task", "t-1", 0, "c-1", "corr-1", {}),
        ]
        for obj in objects:
            self.assertEqual(obj.schema_version, "0.1")
            with self.assertRaises(FrozenInstanceError):
                obj.id = "changed"
            self.assertEqual(obj.to_versioned_dict()["schema_version"], "0.1")

    def test_valid_fixtures_round_trip_through_models(self):
        paths = sorted(VALID_FIXTURES.glob("*.json"))
        self.assertEqual({p.stem for p in paths}, set(MODEL_TYPES))
        for path in paths:
            obj = load_fixture(path)
            self.assertEqual(obj.schema_version, "0.1")
            self.assertEqual(type(obj).__name__.lower(), path.stem)
            self.assertEqual(type(obj).from_dict(obj.to_versioned_dict()), obj)

    def test_invalid_fixtures_are_rejected(self):
        errors = {}
        for path in sorted(INVALID_FIXTURES.glob("*.json")):
            with self.subTest(path=path.name):
                data = json.loads(path.read_text(encoding="utf-8"))
                try:
                    INVALID_MODEL_TYPES[path.stem].from_dict(data)
                except (TypeError, ValueError) as exc:
                    errors[path.name] = str(exc)
                else:
                    self.fail(f"invalid fixture was accepted: {path}")
        self.assertEqual(
            set(errors),
            {"missing_id.json", "unsupported_type.json", "negative_revision.json", "empty_idempotency_key.json"},
        )

    def test_command_and_event_payloads_are_deeply_immutable(self):
        command = models.Command(
            "c-immutable",
            "p-1",
            "a-1",
            "task.create",
            "t-1",
            {"nested": {"value": 1}, "items": [1]},
            0,
            "k-immutable",
            "corr-immutable",
        )
        event = models.Event(
            "e-immutable",
            "p-1",
            1,
            "task.created",
            "task",
            "t-1",
            0,
            "c-immutable",
            "corr-immutable",
            {"nested": {"value": 1}, "items": [1]},
        )

        command_digest = command.digest()
        with self.assertRaises(TypeError):
            command.payload["nested"]["value"] = 2
        with self.assertRaises(TypeError):
            command.payload["items"].append(2)
        with self.assertRaises(TypeError):
            event.payload["nested"]["value"] = 2
        with self.assertRaises(TypeError):
            event.payload["items"].append(2)
        self.assertEqual(command.digest(), command_digest)

    def test_enum_values_must_use_canonical_lowercase_spelling(self):
        with self.assertRaises(models.ModelValidationError):
            models.Command("c-upper", "p-1", "a-1", "TASK.CREATE", None, {}, 0, "k-upper", "corr-upper")
        with self.assertRaises(models.ModelValidationError):
            models.Project("p-upper", 0, "PLANNING")
        with self.assertRaises(models.ModelValidationError):
            models.Event("e-upper", "p-1", 1, "TASK.CREATED", "task", "t-1", 0, "c-1", "corr-1", {})


class SQLiteStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.tempdir.name) / "m0.sqlite")
        self.store = SQLiteStore.open(self.db_path)
        self.addCleanup(self.tempdir.cleanup)
        self.addCleanup(self.store.close)

    def test_schema_persists_commands_events_and_idempotency(self):
        command = models.Command("c-1", "p-1", "a-1", "task.create", "t-1", {"title": "demo"}, 0, "k-1", "corr-1")
        event = models.Event("e-1", "p-1", 1, "task.created", "task", "t-1", 0, "c-1", "corr-1", {"title": "demo"})
        with self.store.transaction():
            self.store.append_command(command)
            self.store.append_events([event])
        self.assertEqual(self.store.read_events("p-1"), [event])
        record = self.store.read_idempotency(("p-1", "a-1", "k-1"))
        self.assertIsNotNone(record)
        self.assertEqual(record["request_digest"], command.digest())
        self.assertEqual(record["command_id"], "c-1")

    def test_event_sequences_are_unique_per_project(self):
        event = models.Event("e-1", "p-1", 1, "task.created", "task", "t-1", 0, "c-1", "corr-1", {})
        self.store.append_events([event])
        duplicate = models.Event("e-2", "p-1", 1, "task.created", "task", "t-1", 1, "c-2", "corr-2", {})
        with self.assertRaises(ValueError):
            self.store.append_events([duplicate])

    def test_transaction_rolls_back_both_command_and_events(self):
        command = models.Command("c-1", "p-1", "a-1", "task.create", None, {}, 0, "k-1", "corr-1")
        event = models.Event("e-1", "p-1", 1, "task.created", "task", "t-1", 0, "c-1", "corr-1", {})
        with self.assertRaises(RuntimeError):
            with self.store.transaction():
                self.store.append_command(command)
                self.store.append_events([event])
                raise RuntimeError("rollback")
        self.assertEqual(self.store.read_events("p-1"), [])
        self.assertIsNone(self.store.read_idempotency(("p-1", "a-1", "k-1")))

    def test_close_is_idempotent(self):
        self.store.close()
        self.store.close()
        with self.assertRaises(RuntimeError):
            self.store.read_events("p-1")


if __name__ == "__main__":
    unittest.main()

