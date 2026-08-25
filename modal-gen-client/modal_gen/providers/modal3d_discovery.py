from __future__ import annotations

import ctypes
import re
import sys
from dataclasses import dataclass, field
from typing import Protocol

HANDOFF_TARGET = "com.modal3d.client.agent-handoff.v1"
_TOKEN = re.compile(r"^[0-9a-fA-F]{64}$")
_CRED_TYPE_GENERIC = 1
_ERROR_NOT_FOUND = 1168
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_STILL_ACTIVE = 259


@dataclass(frozen=True, slots=True)
class AgentConnection:
    endpoint: str
    token: str = field(repr=False)
    agent_pid: int
    desktop_pid: int


class AgentDiscovery(Protocol):
    def discover(self) -> AgentConnection | None: ...


class WindowsCredentialDiscovery:
    """从当前 Windows 用户的 Credential Manager 读取 3D Agent handoff。"""

    def discover(self) -> AgentConnection | None:
        if sys.platform != "win32":
            return None
        blob = _read_windows_credential(HANDOFF_TARGET)
        if blob is None:
            return None
        connection = decode_agent_handoff(blob)
        if not _windows_pid_alive(connection.agent_pid):
            return None
        if not _windows_pid_alive(connection.desktop_pid):
            return None
        return connection


def decode_agent_handoff(data: bytes) -> AgentConnection:
    try:
        parts = data.decode("utf-8").split("\n")
    except UnicodeDecodeError as exc:
        raise ValueError("modal-3D Agent handoff 编码无效") from exc
    if len(parts) != 5 or parts[0] != "v1":
        raise ValueError("modal-3D Agent handoff 版本无效")
    try:
        port = int(parts[1])
        agent_pid = int(parts[2])
        desktop_pid = int(parts[3])
    except ValueError as exc:
        raise ValueError("modal-3D Agent handoff 数字字段无效") from exc
    token = parts[4].strip()
    if not 1 <= port <= 65535:
        raise ValueError("modal-3D Agent handoff 端口无效")
    if agent_pid <= 0 or desktop_pid <= 0:
        raise ValueError("modal-3D Agent handoff PID 无效")
    if not _TOKEN.fullmatch(token):
        raise ValueError("modal-3D Agent handoff session token 无效")
    return AgentConnection(
        endpoint=f"http://127.0.0.1:{port}",
        token=token.lower(),
        agent_pid=agent_pid,
        desktop_pid=desktop_pid,
    )


def _read_windows_credential(target: str) -> bytes | None:
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    class CredentialW(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", wintypes.FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    credential_pointer = ctypes.POINTER(CredentialW)()
    advapi32 = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
    advapi32.CredReadW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(CredentialW)),
    ]
    advapi32.CredReadW.restype = wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    advapi32.CredFree.restype = None

    if not advapi32.CredReadW(target, _CRED_TYPE_GENERIC, 0, ctypes.byref(credential_pointer)):
        error = ctypes.get_last_error()
        if error == _ERROR_NOT_FOUND:
            return None
        raise OSError(error, "读取 modal-3D Agent handoff 失败")
    try:
        credential = credential_pointer.contents
        if credential.CredentialBlobSize == 0:
            return b""
        return ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
    finally:
        advapi32.CredFree(credential_pointer)


def _windows_pid_alive(pid: int) -> bool:
    if sys.platform != "win32":
        return False
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return False
    try:
        code = wintypes.DWORD()
        return (
            bool(kernel32.GetExitCodeProcess(handle, ctypes.byref(code)))
            and code.value == _STILL_ACTIVE
        )
    finally:
        kernel32.CloseHandle(handle)
