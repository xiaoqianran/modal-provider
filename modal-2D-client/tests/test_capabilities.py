import pytest

from modal_2d_client import capabilities
from modal_2d_client.contracts import ContractError


def test_capability_is_loaded_locally_without_modal_call(monkeypatch, capability_doc):
    monkeypatch.setattr(capabilities, "_cache", None)
    monkeypatch.setattr(capabilities, "capabilities_document", lambda: capability_doc)
    assert capabilities.document()["contract"] == "modal-2d.generation.v2"
    capabilities.ensure_model("sana-sprint-1.6b")
    assert capabilities.worker_route("sana-sprint-1.6b") == (
        "modal-2d-sana-sprint",
        "Model",
        "generate",
        "generate_batch",
    )
    with pytest.raises(ContractError, match="unsupported model"):
        capabilities.ensure_model("unknown-model")


def test_cached_local_capability_is_reused(monkeypatch, capability_doc):
    monkeypatch.setattr(capabilities, "_cache", capability_doc)
    monkeypatch.setattr(
        capabilities,
        "capabilities_document",
        lambda: pytest.fail("cached local capability should be reused"),
    )
    assert capabilities.document(refresh_remote=False) is capability_doc
