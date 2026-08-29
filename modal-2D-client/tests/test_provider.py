

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
