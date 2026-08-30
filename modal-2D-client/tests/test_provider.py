

def test_provider_connect_only_validates_modal_session(monkeypatch):
    from modal_2d_client import modal_session
    from modal_2d_client.provider import Modal2DProvider

    state = {"connected": False}
    monkeypatch.setattr(modal_session, "connect", lambda *_: state.__setitem__("connected", True))
    monkeypatch.setattr(modal_session, "connected", lambda: state["connected"])

    def unexpected_refresh(**_):
        raise AssertionError("connect must not refresh remote capabilities")

    monkeypatch.setattr("modal_2d_client.provider.capabilities.document", unexpected_refresh)
    result = Modal2DProvider().connect("id", "secret")

    assert result == {"connected": True, "managed": True}
    assert state["connected"] is True


def test_provider_descriptor_uses_cached_capability_only(monkeypatch):
    from modal_2d_client.provider import Modal2DProvider

    def cached(*, refresh_remote=True):
        assert refresh_remote is False
        return {"models": [{"id": "sana-sprint-1.6b"}]}

    monkeypatch.setattr("modal_2d_client.provider.capabilities.document", cached)
    descriptor = Modal2DProvider().descriptor()
    assert descriptor["status"] == "available"


def test_descriptor_refreshes_once_when_connected_cache_is_empty(monkeypatch, capability_doc):
    from modal_2d_client.modal_session import NotConnectedError
    from modal_2d_client.provider import Modal2DProvider
    calls = []

    def document(*, refresh_remote=True):
        calls.append(refresh_remote)
        if refresh_remote:
            return capability_doc
        raise NotConnectedError("cache empty")

    monkeypatch.setattr("modal_2d_client.provider.capabilities.document", document)
    monkeypatch.setattr("modal_2d_client.provider.modal_session.connected", lambda: True)

    descriptor = Modal2DProvider().descriptor()

    assert calls == [False, True]
    assert descriptor["status"] == "available"
    assert descriptor["health"] == "healthy"


def test_descriptor_does_not_refresh_when_disconnected_cache_is_empty(monkeypatch):
    from modal_2d_client.modal_session import NotConnectedError
    from modal_2d_client.provider import Modal2DProvider
    calls = []

    def document(*, refresh_remote=True):
        calls.append(refresh_remote)
        raise NotConnectedError("cache empty")

    monkeypatch.setattr("modal_2d_client.provider.capabilities.document", document)
    monkeypatch.setattr("modal_2d_client.provider.modal_session.connected", lambda: False)

    descriptor = Modal2DProvider().descriptor()

    assert calls == [False]
    assert descriptor["status"] == "disabled"
    assert descriptor["health"] == "unavailable"
