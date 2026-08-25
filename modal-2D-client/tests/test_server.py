import pytest

from modal_2d_client import server


def test_server_is_loopback_only(monkeypatch):
    calls = []
    monkeypatch.delenv("MODAL_2D_HOST", raising=False)
    monkeypatch.setenv("MODAL_2D_PORT", "4321")
    monkeypatch.setattr(server.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    server.main()

    assert calls == [
        (("modal_2d_client.app:app",), {"host": "127.0.0.1", "port": 4321, "log_level": "info"})
    ]


def test_server_rejects_external_bind(monkeypatch):
    monkeypatch.setenv("MODAL_2D_HOST", "0.0.0.0")
    with pytest.raises(RuntimeError, match="127.0.0.1"):
        server.main()
