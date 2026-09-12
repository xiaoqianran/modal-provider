import json
from types import SimpleNamespace

import pytest
from modal_world.contracts import Operation, WorldRequest

from modal_fire3d.backend import Fire3DBackend
from modal_fire3d.background_policy import write_background_protocol


@pytest.fixture
def checkout(tmp_path):
    root = tmp_path / "upstream"
    source = root / "configs/inference/fire3d_single_image_v1.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({
        "name": "fire3d_single_image_v1",
        "perception": {"threshold": 0.2},
        "reconstruction": {
            "background": {"room_box_prior": True, "distance": 0.12},
            "flow": {"seed": 20260717},
        },
    }))
    (root / "fire3d").mkdir()
    (root / "fire3d/cli.py").touch()
    return root, source


def test_repair_changes_only_background_runtime_parameter(checkout, tmp_path):
    root, source = checkout
    original = source.read_bytes()
    path = write_background_protocol(root, tmp_path / "out", "single_image", "observed_single_image")
    repaired = json.loads(path.read_text())
    expected = json.loads(original)
    assert repaired["perception"] == expected["perception"]
    expected["reconstruction"]["background"]["room_box_prior"] = False
    assert repaired["reconstruction"] == expected["reconstruction"]
    assert repaired["status"] == "local_repair"
    assert source.read_bytes() == original


def test_official_does_not_write_protocol(tmp_path):
    assert write_background_protocol(tmp_path, tmp_path / "out", "single_image", "official") is None
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("dataset,policy", [("ithor", "observed_single_image"), ("single_image", "typo")])
def test_reject_invalid_policy(tmp_path, dataset, policy):
    with pytest.raises(ValueError):
        write_background_protocol(tmp_path, tmp_path / "out", dataset, policy)


def test_reject_stale_reconstruction(checkout, tmp_path):
    output = tmp_path / "out"
    (output / "reconstruction").mkdir(parents=True)
    with pytest.raises(FileExistsError, match="fresh"):
        write_background_protocol(checkout[0], output, "single_image", "observed_single_image")


@pytest.mark.parametrize("policy", [None, "official"])
def test_backend_passes_selected_protocol(checkout, tmp_path, monkeypatch, policy):
    seen = []

    def run(command, **kwargs):
        seen.append(command)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("modal_fire3d.backend.subprocess.run", run)
    monkeypatch.setattr(Fire3DBackend, "_validate_official_result", staticmethod(lambda *args: {}))
    monkeypatch.setattr(Fire3DBackend, "_discover_artifacts", staticmethod(lambda *args: ()))
    options = {"fire3d_root": str(checkout[0])}
    if policy:
        options["background_policy"] = policy
    result = Fire3DBackend().run(WorldRequest(
        operation=Operation.RECONSTRUCT, input_path=tmp_path,
        output_dir=tmp_path / "out", options=options,
    ))
    assert ("--protocol" in seen[0]) == (policy is None)
    assert result.metadata["background_policy"] == (policy or "observed_single_image")
