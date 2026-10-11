"""Pinned, no-reparse Windows file access for a trusted fixed-path provider.

    Directory handles deny DELETE sharing for the whole access, preventing
    ancestor replacement between validation and CreateFile. New objects stay
    delete-pending until all content is flushed; Windows then refuses new
    hardlinks during writes. Sharing flags alone do not provide that guarantee.
    No path supplied by an Agent reaches these functions.
"""

from contextlib import contextmanager
import ctypes
from ctypes import wintypes
import os
from pathlib import Path

from aetp.workspace.gate import EnforcementUnavailable

if os.name == "nt":
    import msvcrt
    _api = ctypes.WinDLL("kernel32", use_last_error=True)
    _api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                 wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    _api.CreateFileW.restype = wintypes.HANDLE
    _api.CloseHandle.argtypes = [wintypes.HANDLE]
    _api.CloseHandle.restype = wintypes.BOOL
    _api.CreateDirectoryW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p]
    _api.CreateDirectoryW.restype = wintypes.BOOL


class FileInformation(ctypes.Structure):
    _fields_ = [("attributes", wintypes.DWORD), ("created", wintypes.FILETIME),
                ("accessed", wintypes.FILETIME), ("written", wintypes.FILETIME),
                ("volume", wintypes.DWORD), ("size_high", wintypes.DWORD), ("size_low", wintypes.DWORD),
                ("links", wintypes.DWORD), ("index_high", wintypes.DWORD), ("index_low", wintypes.DWORD)]


if os.name == "nt":
    _api.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(FileInformation)]
    _api.GetFileInformationByHandle.restype = wintypes.BOOL
    _api.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    _api.SetFileInformationByHandle.restype = wintypes.BOOL


class WorkspaceViolation(OSError):
    pass


def _check_platform():
    if os.name != "nt":
        raise EnforcementUnavailable("Windows file-handle enforcement is unavailable")


def absolute(path):
    _check_platform()
    value = Path(os.path.abspath(path))
    if len(value.drive) != 2 or value.drive[1] != ":" or not value.drive[0].isalpha():
        raise WorkspaceViolation("only local drive workspaces are supported")
    for part in value.parts[1:]:
        if not part or part.endswith((".", " ")) or any(char in part for char in '<>:"|?*\x00'):
            raise WorkspaceViolation("invalid workspace path component")
    return value


def _native(path):
    return "\\\\?\\" + str(path)


def information(handle):
    result = FileInformation()
    if not _api.GetFileInformationByHandle(handle, ctypes.byref(result)):
        raise ctypes.WinError(ctypes.get_last_error())
    return result


def identity(handle):
    info = information(handle)
    return info.volume, info.index_high, info.index_low


def _open(path, access, share, disposition, flags):
    handle = _api.CreateFileW(_native(path), access, share, None, disposition, flags, None)
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle


@contextmanager
def directory(path, *, create=False, anchor=None, authorize=None):
    """Pin all ancestors, reject reparse points, optionally pin root identity."""
    path = absolute(path)
    handles = []
    current = Path(path.anchor)
    try:
        for index in range(len(path.parts)):
            if index:
                current = current / path.parts[index]
            # READ_ATTRIBUTES-only handles do not participate in Windows
            # sharing checks. FILE_LIST_DIRECTORY is required to make the
            # omitted FILE_SHARE_DELETE actually prevent ancestor renames.
            try:
                handle = _open(current, 0x1 | 0x80, 0x1 | 0x2, 3, 0x02000000 | 0x00200000)
            except OSError as exc:
                if not create or exc.winerror not in {2, 3}:
                    raise
                if anchor is not None and anchor[0] not in current.parents:
                    raise WorkspaceViolation("the pinned root or an ancestor is missing") from exc
                if authorize is not None:
                    authorize()
                if not _api.CreateDirectoryW(_native(current), None):
                    error = ctypes.get_last_error()
                    if error != 183:
                        raise ctypes.WinError(error)
                handle = _open(current, 0x1 | 0x80, 0x1 | 0x2, 3, 0x02000000 | 0x00200000)
            handles.append(handle)
            info = information(handle)
            if info.attributes & 0x400 or not info.attributes & 0x10:
                raise WorkspaceViolation("directory is a reparse point or not a directory")
            if anchor is not None and current == anchor[0] and identity(handle) != anchor[1]:
                raise WorkspaceViolation("workspace root was replaced")
        yield handles[-1]
    finally:
        for handle in reversed(handles):
            _api.CloseHandle(handle)


def _delete_pending(handle, pending):
    # FILE_DISPOSITION_INFO contains one BOOLEAN, not a Win32 BOOL.
    flag = ctypes.c_ubyte(bool(pending))
    if not _api.SetFileInformationByHandle(handle, 4, ctypes.byref(flag), ctypes.sizeof(flag)):
        raise ctypes.WinError(ctypes.get_last_error())


def open_object(path, *, create):
    """Return an owned handle; new files require explicit immutable publication."""
    handle = _open(path, 0x80000000 | ((0x40000000 | 0x10000) if create else 0),
                   0x1, 1 if create else 3, 0x00200000)
    try:
        if create:
            # Delete-pending blocks new names at the filesystem boundary.
            # The pending original name is excluded from the link count;
            # any remaining link was inserted before this atomic transition.
            _delete_pending(handle, True)
        info = information(handle)
        if info.attributes & (0x400 | 0x10) or info.links != (0 if create else 1):
            raise WorkspaceViolation("document object is a link or not a regular single-link file")
        return handle
    except BaseException:
        _api.CloseHandle(handle)
        raise


def publish_object(handle):
    """Retain a completed new object. The caller must not write after this call."""
    info = information(handle)
    if info.attributes & (0x400 | 0x10) or info.links != 0:
        raise WorkspaceViolation("unpublished object has an unexpected live link")
    _delete_pending(handle, False)


@contextmanager
def file_stream(handle, *, write):
    """Transfer exactly one Windows handle into a Python binary stream."""
    try:
        descriptor = msvcrt.open_osfhandle(handle, (os.O_WRONLY if write else os.O_RDONLY) | os.O_BINARY)
    except BaseException:
        _api.CloseHandle(handle)
        raise
    with os.fdopen(descriptor, "wb" if write else "rb") as stream:
        yield stream
