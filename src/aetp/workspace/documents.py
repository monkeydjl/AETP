"""Fixed immutable document objects in independent, handle-pinned copies."""

import hashlib
import os
from pathlib import Path

from aetp.workspace.gate import EnforcementUnavailable
from aetp.workspace import windows_files
from aetp.collaboration.policy import MAX_CONTENT_BYTES, canonical_json
from aetp.runtime.records import envelope, object_key, receipt

MAX_OBJECT_BYTES = MAX_CONTENT_BYTES * 6 + 16_384


class DocumentWorkspace:
    def __init__(self, root):
        if os.name != "nt":
            raise EnforcementUnavailable("fixed document provider currently supports Windows only")
        self.root = windows_files.absolute(root)
        # Host provisioning is separate from Agent effects. All document
        # objects are created only after a durable IN_FLIGHT Action exists.
        with windows_files.directory(self.root, create=True) as handle:
            self._root_identity = windows_files.identity(handle)
        scope = f"{os.path.normcase(str(self.root))}:{self._root_identity}"
        self.identity = "workspace-" + hashlib.sha256(scope.encode("utf-8")).hexdigest()

    def path_for(self, action):
        if action["workspace_provider_id"] != self.identity:
            raise windows_files.WorkspaceViolation("document belongs to another workspace")
        return self.root / Path(object_key(action))

    def write(self, action, authorize):
        """Trusted broker callback rechecks facts at the actual access point."""
        authorize()
        path = self.path_for(action)
        data = canonical_json(envelope(action)).encode("utf-8")
        if len(data) > MAX_OBJECT_BYTES:
            raise windows_files.WorkspaceViolation("document object exceeds fixed size limit")
        with windows_files.directory(path.parent, create=True, anchor=(self.root, self._root_identity), authorize=authorize):
            authorize()
            handle = windows_files.open_object(path, create=True)
            with windows_files.file_stream(handle, write=True) as stream:
                authorize()
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
                windows_files.publish_object(handle)
        return receipt(action)

    def query(self, action):
        """Missing/partial/mismatched output never proves safe non-execution."""
        try:
            path = self.path_for(action)
            with windows_files.directory(path.parent, anchor=(self.root, self._root_identity)):
                handle = windows_files.open_object(path, create=False)
                with windows_files.file_stream(handle, write=False) as stream:
                    content = stream.read(MAX_OBJECT_BYTES + 1)
            expected = canonical_json(envelope(action)).encode("utf-8")
            if len(content) > MAX_OBJECT_BYTES or content != expected:
                return {"status": "unknown", "reason": "OBJECT_IDENTITY_OR_CONTENT_MISMATCH"}
            return {"status": "confirmed", "result": receipt(action)}
        except OSError:
            return {"status": "unknown", "reason": "OBJECT_UNAVAILABLE"}
