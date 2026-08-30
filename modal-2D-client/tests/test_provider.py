def test_provider_descriptor_uses_local_capability_when_connected(monkeypatch):
    from modal_2d_client.provider import Modal2DProvider

    def local(*, refresh_remote=True):
        assert refresh_remote is False
        return {"models": [{"id": "sana-sprint-1.6b"}]}

    monkeypatch.setattr("modal_2d_client.provider.capabilities.document", local)
    monkeypatch.setattr("modal_2d_client.provider.modal_session.connected", lambda: True)
    descriptor = Modal2DProvider().descriptor()
    assert descriptor["status"] == "available"
    assert descriptor["health"] == "healthy"


def test_provider_descriptor_is_disabled_without_modal_connection(monkeypatch):
    from modal_2d_client.provider import Modal2DProvider

    monkeypatch.setattr(
        "modal_2d_client.provider.capabilities.document",
        lambda **_kwargs: {"models": [{"id": "sana-sprint-1.6b"}]},
    )
    monkeypatch.setattr("modal_2d_client.provider.modal_session.connected", lambda: False)
    descriptor = Modal2DProvider().descriptor()
    assert descriptor["status"] == "disabled"
    assert descriptor["health"] == "unavailable"


def test_provider_descriptor_never_requests_remote_capability(monkeypatch):
    from modal_2d_client.provider import Modal2DProvider

    calls = []

    def local(*, refresh_remote=True):
        calls.append(refresh_remote)
        return {"models": [{"id": "sana-sprint-1.6b"}]}

    monkeypatch.setattr("modal_2d_client.provider.capabilities.document", local)
    monkeypatch.setattr("modal_2d_client.provider.modal_session.connected", lambda: True)
    Modal2DProvider().descriptor()
    assert calls == [False]
