import pytest

from modal_2d_client import capabilities
from modal_2d_client.contracts import ContractError
from modal_2d_client.modal_session import NotConnectedError


def test_hot_path_uses_only_cached_capability(capability_doc, monkeypatch):
    monkeypatch.setattr(capabilities, "_cache", capability_doc)
    monkeypatch.setattr(
        capabilities,
        "refresh",
        lambda: pytest.fail("generation hot path must not refresh capabilities"),
    )

    capabilities.ensure_model("sana-sprint-1.6b")
    assert capabilities.worker_route("sana-sprint-1.6b") == (
        "modal-2d-sana-sprint",
        "Model",
        "generate",
        "generate_batch",
    )
    with pytest.raises(ContractError, match="unsupported model"):
        capabilities.ensure_model("unknown-model")


def test_hot_path_fails_closed_without_capability_cache(monkeypatch):
    monkeypatch.setattr(capabilities, "_cache", None)
    with pytest.raises(NotConnectedError, match="capability"):
        capabilities.ensure_model("sana-sprint-1.6b")
