"""Non-authoritative process material, sharing the kernel's SQLite transaction."""

import json

from aetp.collaboration.policy import PolicyViolation, canonical_json, digest_value
from aetp.meetings.records import summarize, validate_checkpoint_prefixes

SCHEMA = (
    "CREATE TABLE IF NOT EXISTS collaboration_processes (project_id TEXT, kind TEXT, object_id TEXT, "
    "origin_command_id TEXT NOT NULL, metadata TEXT NOT NULL, PRIMARY KEY(project_id,kind,object_id))",
    "CREATE TABLE IF NOT EXISTS collaboration_entries (project_id TEXT, kind TEXT, object_id TEXT, "
    "entry_id TEXT, ordinal INTEGER NOT NULL, record TEXT NOT NULL, PRIMARY KEY(project_id,kind,object_id,entry_id))",
    "CREATE TABLE IF NOT EXISTS collaboration_usage (source_id TEXT, call_id TEXT, project_id TEXT NOT NULL, "
    "kind TEXT NOT NULL, object_id TEXT NOT NULL, entry_id TEXT NOT NULL, receipt TEXT NOT NULL, "
    "PRIMARY KEY(source_id,call_id))",
)


class ProcessLog:
    def __init__(self, store):
        self.store = store
        with store.transaction():
            for sql in SCHEMA:
                store._ensure_open().execute(sql)

    @staticmethod
    def key(record):
        return record["project_id"], record["kind"], record["id"]

    def create(self, record):
        metadata = {"messages": 0, "tokens": 0, "digest": digest_value([]),
                    "last_observed_at_ms": record["observed_at_ms"], "compacted": False}
        self.store._ensure_open().execute("INSERT INTO collaboration_processes VALUES (?,?,?,?,?)",
            (*self.key(record), record["origin_command_id"], canonical_json(metadata)))

    def read(self, record):
        connection = self.store._ensure_open()
        result = connection.execute("SELECT origin_command_id, metadata FROM collaboration_processes "
            "WHERE project_id=? AND kind=? AND object_id=?", self.key(record)).fetchone()
        if result is None or result[0] != record["origin_command_id"]:
            raise PolicyViolation("PROCESS_UNRECONCILED")
        metadata = json.loads(result[1])
        rows = [json.loads(row[0]) for row in connection.execute("SELECT record FROM collaboration_entries "
            "WHERE project_id=? AND kind=? AND object_id=? ORDER BY ordinal", self.key(record))]
        receipts = [json.loads(row[0]) for row in connection.execute("SELECT receipt FROM collaboration_usage "
            "WHERE project_id=? AND kind=? AND object_id=?", self.key(record))]
        if (len(receipts) != metadata["messages"] or sum(row["tokens"] for row in receipts) != metadata["tokens"]):
            raise PolicyViolation("PROCESS_UNRECONCILED")
        checkpoint = record["checkpoint"]
        if metadata["messages"] < checkpoint["messages"] or metadata["tokens"] < checkpoint["tokens"]:
            raise PolicyViolation("PROCESS_UNRECONCILED")
        if metadata["messages"] == checkpoint["messages"] and (
                metadata["digest"] != checkpoint["digest"] or metadata["tokens"] != checkpoint["tokens"]):
            raise PolicyViolation("PROCESS_UNRECONCILED")
        if metadata["compacted"]:
            if rows or record["status"] != "closed" or record["checkpoint"]["digest"] != metadata["digest"]:
                raise PolicyViolation("PROCESS_UNRECONCILED")
            return rows, metadata
        if len(rows) != metadata["messages"] or digest_value(rows) != metadata["digest"]:
            raise PolicyViolation("PROCESS_UNRECONCILED")
        by_subject = {item["subject_digest"]: item for item in receipts}
        for row in rows:
            if row["receipt"] != by_subject.get(row["semantic_digest"]):
                raise PolicyViolation("PROCESS_UNRECONCILED")
        validate_checkpoint_prefixes(record, rows)
        return rows, metadata

    def snapshot(self, record):
        rows, meta = self.read(record)
        if meta["compacted"]:
            return dict(record["checkpoint"])
        return summarize(rows, record["participants"])

    def append(self, record, contribution, receipt, at):
        connection = self.store._ensure_open()
        if connection.execute("SELECT 1 FROM collaboration_usage WHERE source_id=? AND call_id=?",
                              (receipt["source_id"], receipt["call_id"])).fetchone():
            raise PolicyViolation("USAGE_ALREADY_CONSUMED")
        rows, meta = self.read(record)
        row = {**json.loads(contribution.to_json()), "semantic_digest": contribution.digest(),
               "phase": record["status"], "round": record["round"], "observed_at_ms": at,
               "untrusted_input": True, "receipt": receipt}
        connection.execute("INSERT INTO collaboration_usage VALUES (?,?,?,?,?,?,?)",
            (receipt["source_id"], receipt["call_id"], *self.key(record), contribution.id, canonical_json(receipt)))
        connection.execute("INSERT INTO collaboration_entries VALUES (?,?,?,?,?,?)",
            (*self.key(record), contribution.id, len(rows) + 1, canonical_json(row)))
        rows.append(row)
        meta.update(messages=len(rows), tokens=meta["tokens"] + receipt["tokens"], digest=digest_value(rows), last_observed_at_ms=at)
        connection.execute("UPDATE collaboration_processes SET metadata=? WHERE project_id=? AND kind=? AND object_id=?",
                           (canonical_json(meta), *self.key(record)))
        return row

    def compact(self, record):
        rows, meta = self.read(record)
        if record["status"] != "closed" or not record["decision_id"] or record["checkpoint"]["digest"] != meta["digest"]:
            raise PolicyViolation("PROCESS_NOT_SETTLED")
        meta["compacted"] = True
        connection = self.store._ensure_open()
        connection.execute("DELETE FROM collaboration_entries WHERE project_id=? AND kind=? AND object_id=?", self.key(record))
        connection.execute("UPDATE collaboration_processes SET metadata=? WHERE project_id=? AND kind=? AND object_id=?",
                           (canonical_json(meta), *self.key(record)))
        return len(rows)
