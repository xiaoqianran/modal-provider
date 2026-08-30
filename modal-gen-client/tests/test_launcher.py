from __future__ import annotations


def test_launcher_starts_ui_thread_then_connector(monkeypatch):
    from modal_gen import launcher, server
    from modal_gen.ui import server as ui_server

    calls = []

    class Thread:
        def __init__(self, *, target, name, daemon):
            calls.append(("thread", target, name, daemon))
            self.target = target

        def start(self):
            calls.append(("start",))

    monkeypatch.setattr(launcher.threading, "Thread", Thread)
    monkeypatch.setattr(server, "main", lambda: calls.append(("connector",)))
    monkeypatch.setattr(ui_server, "main", lambda: calls.append(("ui",)))
    monkeypatch.delenv("MODAL_GEN_CONNECTOR_URL", raising=False)
    monkeypatch.setenv("MODAL_GEN_PORT", "49123")

    launcher.main()

    assert calls[0][0] == "thread"
    assert calls[0][2:] == ("modal-gen-ui", True)
    assert calls[1] == ("start",)
    assert calls[2] == ("connector",)
    assert launcher.os.environ["MODAL_GEN_CONNECTOR_URL"] == "http://127.0.0.1:49123"
