from __future__ import annotations

import os
import sys
import uuid

import pytest

from modal_gen.providers.modal3d_discovery import (
    AgentConnection,
    WindowsCredentialDiscovery,
    _read_windows_credential,
    _windows_pid_alive,
    decode_agent_handoff,
)


def test_handoff_payload_matches_desktop_contract() -> None:
    token = "a" * 64
    connection = decode_agent_handoff(f"v1\n48123\n1234\n5678\n{token}".encode())
    assert connection.endpoint == "http://127.0.0.1:48123"
    assert connection.agent_pid == 1234
    assert connection.desktop_pid == 5678
    assert connection.token == token
    assert token not in repr(connection)


@pytest.mark.parametrize(
    "payload",
    [
        b"v2\n48123\n1\n2\n" + b"a" * 64,
        b"v1\n0\n1\n2\n" + b"a" * 64,
        b"v1\n65536\n1\n2\n" + b"a" * 64,
        b"v1\n48123\n0\n2\n" + b"a" * 64,
        b"v1\n48123\n1\n0\n" + b"a" * 64,
        b"v1\n48123\n1\n2\nnot-a-token",
        b"\xff\xfe",
    ],
)
def test_handoff_rejects_invalid(payload: bytes) -> None:
    with pytest.raises(ValueError):
        decode_agent_handoff(payload)


def test_discovery_is_inactive_off_windows() -> None:
    if sys.platform == "win32":
        pytest.skip("Windows behavior covered by Windows CI")
    assert WindowsCredentialDiscovery().discover() is None


def test_connection_repr_hides_token() -> None:
    token = "b" * 64
    value = AgentConnection("http://127.0.0.1:48123", token, 1, 2)
    assert token not in repr(value)


@pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows")
def test_windows_credential_reader_missing_target() -> None:
    assert _read_windows_credential(f"com.modal3d.client.test.missing.{uuid.uuid4().hex}") is None


@pytest.mark.skipif(sys.platform != "win32", reason="仅 Windows")
def test_windows_pid_probe_current_process() -> None:
    assert _windows_pid_alive(os.getpid()) is True
