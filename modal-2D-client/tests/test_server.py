from modal_2d_client import server


def test_server_defaults_to_all_interfaces(monkeypatch):
    calls = []
    monkeypatch.delenv("MODAL_2D_HOST", raising=False)
    monkeypatch.delenv("MODAL_2D_PORT", raising=False)
    monkeypatch.setattr(server.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    server.main()

    assert calls == [
        (("modal_2d_client.app:app",), {"host": "0.0.0.0", "port": 3212, "log_level": "info"})
    ]


def test_server_honors_environment_overrides(monkeypatch):
    calls = []
    monkeypatch.setenv("MODAL_2D_HOST", "127.0.0.1")
    monkeypatch.setenv("MODAL_2D_PORT", "4321")
    monkeypatch.setattr(server.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    server.main()

    assert calls == [
        (("modal_2d_client.app:app",), {"host": "127.0.0.1", "port": 4321, "log_level": "info"})
    ]


def test_server_accepts_arbitrary_host(monkeypatch):
    """不再限制绑定地址：容器与反向代理场景需要。"""
    calls = []
    monkeypatch.setenv("MODAL_2D_HOST", "0.0.0.0")
    monkeypatch.setattr(server.uvicorn, "run", lambda *args, **kwargs: calls.append((args, kwargs)))

    server.main()

    assert calls[0][1]["host"] == "0.0.0.0"
