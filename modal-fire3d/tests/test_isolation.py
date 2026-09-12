import json
import subprocess
import sys

from modal_world import deployment as hy_deployment

from modal_fire3d import deployment as fire_deployment


def test_fire3d_service_does_not_import_hyworld2_or_construct_gpu_images():
    result = subprocess.run(
        [sys.executable, "-c", """
import json
import sys
import modal_fire3d.service
import modal_fire3d.deployment
print(json.dumps(sorted(sys.modules)))
"""],
        check=True, capture_output=True, text=True,
    )
    modules = json.loads(result.stdout)
    assert not any("hyworld2" in name for name in modules)
    assert "modal_world.providers" not in modules
    assert "modal_world.deployment" not in modules
    assert "modal_fire3d.runtime" not in modules
    assert "torch" not in modules


def test_manifests_have_separate_targets_and_artifact_builders():
    target, = fire_deployment.deployment_manifest()["targets"]
    assert target["module"] == "modal_fire3d.app"
    assert target["app"] == "modal-world-fire3d"
    assert target["models"] == ["fire3d"]
    assert len(target["prerequisites"]) == 2
    for spec in target["prerequisites"]:
        assert spec["requiredPaths"][0].startswith("fire3d-")
        assert [call["function"] for call in spec["prepare"]] == ["build", "smoke"]
        assert all(call["module"].startswith("integrations.fire3d.") for call in spec["prepare"])
    assert all(
        item["models"] == ["hyworld2"]
        for item in hy_deployment.deployment_manifest()["targets"]
    )


def test_cloud_app_imports_without_local_world_contract_package():
    subprocess.run(
        [sys.executable, "-c", """
import importlib.abc
import sys
class NoWorldPackage(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == 'modal_world' or fullname.startswith('modal_world.'):
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0, NoWorldPackage())
import modal_fire3d.app
assert modal_fire3d.app.app.name == 'modal-world-fire3d'
"""],
        check=True, capture_output=True, text=True,
    )


def test_runtime_revisions_do_not_cross_model_boundaries(tmp_path, monkeypatch):
    fire_root = tmp_path / "modal_fire3d"
    hy_root = tmp_path / "modal_world"
    fire_root.mkdir()
    hy_root.mkdir()
    fire_source = fire_root / "runtime.py"
    hy_source = hy_root / "hyworld2_runtime.py"
    fire_source.write_text("VERSION = 1\n")
    hy_source.write_text("VERSION = 1\n")
    monkeypatch.setattr(fire_deployment, "__file__", str(fire_root / "deployment.py"))
    monkeypatch.setattr(hy_deployment, "__file__", str(hy_root / "deployment.py"))
    fire_before = fire_deployment.runtime_revision()
    hy_before = hy_deployment.runtime_revision()
    fire_source.write_text("VERSION = 2\n")
    assert fire_deployment.runtime_revision() != fire_before
    assert hy_deployment.runtime_revision() == hy_before
    fire_after = fire_deployment.runtime_revision()
    hy_source.write_text("VERSION = 2\n")
    assert hy_deployment.runtime_revision() != hy_before
    assert fire_deployment.runtime_revision() == fire_after
