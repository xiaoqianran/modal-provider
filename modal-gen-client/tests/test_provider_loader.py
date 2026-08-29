import pytest

from modal_gen.providers.loader import load_providers


def test_installed_provider_packages_are_discovered():
    providers = load_providers()
    assert [provider.id for provider in providers] == ["modal-2d", "modal-3d"]


class BrokenConnectionProvider:
    id = "broken"

    def descriptor(self):
        return {"id": self.id}

    def unavailable_descriptor(self):
        return {"id": self.id}

    def connection_status(self):
        return {"connected": False, "managed": True}

    def connect(self, token_id, token_secret):
        raise ValueError("credential contents must stay private")

    def disconnect(self):
        return {"connected": False, "managed": True}


def test_connection_error_exposes_type_but_not_provider_message():
    from modal_gen.errors import ProviderError
    from modal_gen.providers.loader import LibraryProviderAdapter

    adapter = LibraryProviderAdapter(BrokenConnectionProvider())
    with pytest.raises(ProviderError) as captured:
        adapter.connect("id-value", "secret-value")

    assert captured.value.code == "PROVIDER_CONNECTION_FAILED"
    assert "ValueError" in str(captured.value)
    assert "credential contents" not in str(captured.value)
    assert "secret-value" not in str(captured.value)
