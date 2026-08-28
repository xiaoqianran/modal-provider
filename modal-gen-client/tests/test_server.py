from modal_gen import server


def test_server_is_loopback_only(monkeypatch):
    calls = []
    monkeypatch.delenv("MODAL_GEN_HOST", raising=False)
    monkeypatch.setenv("MODAL_GEN_PORT", "48123")
    monkeypatch.setattr(server.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    server.main()

    assert calls == [
        (("modal_gen.app:app",), {"host": "127.0.0.1", "port": 48123, "log_level": "info"})
    ]


def test_server_allows_explicit_external_bind_with_warning(monkeypatch, capsys):
    """External bind is opt-in: allowed, but must warn loudly."""
    monkeypatch.setenv("MODAL_GEN_HOST", "0.0.0.0")
    calls = []
    monkeypatch.setattr(server.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    server.main()

    assert calls == [
        (("modal_gen.app:app",), {"host": "0.0.0.0", "port": 48123, "log_level": "info"})
    ]
    assert "警告" in capsys.readouterr().err
