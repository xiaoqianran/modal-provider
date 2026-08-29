from modal_gen.providers.loader import load_providers


def test_installed_provider_packages_are_discovered():
    providers = load_providers()
    assert [provider.id for provider in providers] == ["modal-2d", "modal-3d"]
