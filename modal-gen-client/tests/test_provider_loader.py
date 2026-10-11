import pytest

from modal_gen.providers.loader import load_providers


def test_installed_provider_packages_are_discovered():
    providers = load_providers()
    assert [provider.id for provider in providers] == ["modal-2d", "modal-3d", "modal-world"]


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


def test_loader_preserves_queued_and_unknown_operation_jobs():
    from modal_gen.providers.loader import LibraryProviderAdapter

    adapter = LibraryProviderAdapter(BrokenConnectionProvider())
    for state in ("queued", "submission_unknown", "running"):
        normalized = adapter._job({"id": "op_a", "status": state, "artifacts": []})
        assert normalized.status == state


def test_connector_job_transition_accepts_recovery_and_processing_kind():
    from modal_gen.jobs import JobService, _job_kind, _stage

    JobService._assert_transition("accepted", "queued")
    JobService._assert_transition("accepted", "submission_unknown")
    JobService._assert_transition("submission_unknown", "running")
    assert _stage("submission_unknown") == "recovery"
    assert _job_kind("modal-3d.asset.retopology.v1") == "asset-processing"
    assert _job_kind("modal-3d.asset.image_to_3d.v1") == "generation"
