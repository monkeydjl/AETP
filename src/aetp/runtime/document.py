"""Trusted data-only Runtime. It never evaluates Agent-provided code."""

from dataclasses import dataclass
import threading

from aetp.workspace.documents import DocumentWorkspace


@dataclass(frozen=True, slots=True, eq=False)
class Session:
    id: str
    project_id: str
    task_id: str
    actor_id: str
    binding_id: str
    lease_epoch: int
    expires_at_wall_ms: int


class DocumentRuntime:
    def __init__(self, workspace):
        if not isinstance(workspace, DocumentWorkspace):
            raise TypeError("workspace must be the fixed document provider")
        self.workspace = workspace
        # Trusted host attaches a registered tool channel; it is never set by an
        # Agent Command and remains optional for document-only deployments.
        self.mcp_provider = None
        self._sessions = {}
        self._lock = threading.RLock()

    def register(self, descriptor):
        """Trusted host activation only, after its start Command committed."""
        with self._lock:
            existing = self._sessions.get(descriptor["id"])
            if existing is not None:
                if any(getattr(existing, key) != value for key, value in descriptor.items()):
                    raise ValueError("Session identity conflict")
                return existing
            session = Session(**descriptor)
            self._sessions[session.id] = session
            return session

    def registered(self, session):
        with self._lock:
            return isinstance(session, Session) and self._sessions.get(session.id) is session

    def lookup(self, identifier):
        with self._lock:
            return self._sessions.get(identifier)

    def sessions(self):
        with self._lock:
            return {key: {"project_id": value.project_id, "task_id": value.task_id,
                          "binding_id": value.binding_id, "expires_at_wall_ms": value.expires_at_wall_ms}
                    for key, value in self._sessions.items()}
