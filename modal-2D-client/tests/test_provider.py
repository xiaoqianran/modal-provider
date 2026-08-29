import pytest
import pytest


def test_provider_connect_rolls_back_when_capability_refresh_fails(monkeypatch):
    from modal_2d_client import modal_session
    from modal_2d_client.provider import Modal2DProvider

    state = {"connected": False}
    monkeypatch.setattr(modal_session, "connect", lambda *_: state.__setitem__("connected", True))
    monkeypatch.setattr(modal_session, "disconnect", lambda: state.__setitem__("connected", False))
    monkeypatch.setattr(modal_session, "connected", lambda: state["connected"])

    def fail_refresh(*, refresh_remote=True):
        assert refresh_remote is True
        raise RuntimeError("remote capability unavailable")

    monkeypatch.setattr("modal_2d_client.provider.capabilities.document", fail_refresh)
    with pytest.raises(RuntimeError, match="remote capability unavailable"):
        Modal2DProvider().connect("id", "secret")
    assert state["connected"] is False


def test_provider_descriptor_uses_cached_capability_only(monkeypatch):
    from modal_2d_client.provider import Modal2DProvider

    def cached(*, refresh_remote=True):
        assert refresh_remote is False
        return {"models": [{"id": "sana-sprint-1.6b"}]}

    monkeypatch.setattr("modal_2d_client.provider.capabilities.document", cached)
    descriptor = Modal2DProvider().descriptor()
    assert descriptor["status"] == "available"
