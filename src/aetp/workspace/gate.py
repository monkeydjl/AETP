"""Windows resource serialization, always combined with durable fencing."""

import ctypes
import hashlib
import os
from contextlib import contextmanager
from ctypes import wintypes


class EnforcementUnavailable(RuntimeError):
    pass


if os.name == "nt":
    _kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    _kernel.CreateMutexW.restype = wintypes.HANDLE
    _kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _kernel.WaitForSingleObject.restype = wintypes.DWORD
    _kernel.ReleaseMutex.argtypes = [wintypes.HANDLE]
    _kernel.ReleaseMutex.restype = wintypes.BOOL
    _kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel.CloseHandle.restype = wintypes.BOOL


class ResourceGate:
    """One OS gate per canonical database path in the current logon session.

    Losing the mutex cannot grant authority: every write still rechecks the
    Event Store revision, Lease and Session. Unsupported hosts fail closed.
    """

    def __init__(self, database_path):
        if os.name != "nt" or not database_path:
            raise EnforcementUnavailable("Windows and a durable local database are required")
        canonical = os.path.normcase(os.path.realpath(database_path))
        self.name = "Local\\AETP-document-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @contextmanager
    def hold(self):
        handle = _kernel.CreateMutexW(None, False, self.name)
        if not handle:
            raise EnforcementUnavailable("cannot create execution resource gate")
        acquired = False
        try:
            status = _kernel.WaitForSingleObject(handle, 10_000)
            if status not in (0, 0x80):  # Abandoned owner: recover facts, never infer success.
                raise EnforcementUnavailable("execution resource gate unavailable")
            acquired = True
            yield
        finally:
            if acquired:
                _kernel.ReleaseMutex(handle)
            _kernel.CloseHandle(handle)
