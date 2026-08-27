import copy

import pytest

from modal_2d_client.contracts import (
    ContractError,
    normalize_request,
    validate_artifact,
    validate_capabilities,
)


def test_capabilities_accept_stable_provider_contract(capability_doc):
    assert validate_capabilities(capability_doc)["operation"] == "modal-2d.image.text_to_image.v1"


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("contract",), "v2"),
        (("generation", "submit_function"), "other"),
        (("generation", "artifact_volume"), "wrong-volume"),
        (("kind",), "other.kind"),
        (("artifact", "lossless"), False),
        (("models", 0, "width"), 512),
        (("models", 0, "steps"), 1),
        (("models", 0, "profiles"), [{"id": "fast", "steps": 1, "guidance": 4.5}]),
    ],
)
def test_capabilities_fail_closed_on_contract_drift(capability_doc, path, value):
    document = copy.deepcopy(capability_doc)
    target = document
    for part in path[:-1]:
        target = target[part]
    target[path[-1]] = value
    with pytest.raises(ContractError):
        validate_capabilities(document)


def test_request_is_minimal_and_rejects_unknown_fields():
    assert normalize_request({"prompt": "  hello  "}) == {
        "prompt": "hello",
        "model": "sana-sprint-1.6b",
        "seed": 42,
    }
    with pytest.raises(ContractError, match="unknown"):
        normalize_request({"prompt": "x", "internal": "secret"})


def test_artifact_descriptor_is_strict(png_artifact):
    _, descriptor = png_artifact
    assert validate_artifact(descriptor)["id"] == "art_abc"
    broken = dict(descriptor, sha256="bad")
    with pytest.raises(ContractError, match="sha256"):
        validate_artifact(broken)
    with pytest.raises(ContractError, match="digest"):
        validate_artifact(dict(descriptor, digest="sha256:bad"))
    with pytest.raises(ContractError, match="remote_path"):
        validate_artifact(dict(descriptor, remote_path="../escape.png"))


def test_request_rejects_steps_override():
    with pytest.raises(ContractError, match="unknown generation fields"):
        normalize_request({"prompt": "x", "steps": 2})
