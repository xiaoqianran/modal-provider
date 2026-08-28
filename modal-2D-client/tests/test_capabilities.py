import pytest

from modal_2d_client import capabilities
from modal_2d_client.contracts import ContractError


def test_ensure_model_never_refreshes_remote_on_generation_hot_path(monkeypatch):
    monkeypatch.setattr(capabilities, "_cache", None)
    monkeypatch.setattr(
        capabilities,
        "refresh",
        lambda: pytest.fail("ensure_model must not call remote capabilities"),
    )

    capabilities.ensure_model("sana-sprint-1.6b")
    capabilities.ensure_model("sana-sprint-0.6b")
    with pytest.raises(ContractError, match="unsupported model"):
        capabilities.ensure_model("unknown-model")
