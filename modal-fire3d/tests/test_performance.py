from pathlib import Path

import pytest

from modal_fire3d.performance import build_background_command, validate_run_id
from modal_fire3d.runtime import prepare_runtime_cache


def _write_source_log(tmp_path: Path) -> Path:
    path = tmp_path / "reconstruction_batch.log"
    path.write_text(
        "python geometry.py --batch-scenes old.json --output-root old-out "
        "--object-selection all --resume-existing --no-model-cache "
        "--shape-decode-resolution 512 --no-appearance-detailed-profile "
        "--background-room-box-prior\n",
        encoding="utf-8",
    )
    return path


def test_optimized_background_command_enables_cache_and_profile(tmp_path):
    command = build_background_command(
        _write_source_log(tmp_path),
        python="python3",
        runner=Path("runner.py"),
        source_manifest=Path("source.json"),
        output_root=Path("target"),
        policy="no_room_filter",
        decode_resolution=384,
        detailed_profile=True,
        model_cache=True,
    )
    assert command[:2] == ["python3", "runner.py"]
    assert command[command.index("--batch-scenes") + 1] == "source.json"
    assert command[command.index("--output-root") + 1] == "target"
    assert command[command.index("--object-selection") + 1] == "background"
    assert command[command.index("--shape-decode-resolution") + 1] == "384"
    assert "--no-resume-existing" in command
    assert "--model-cache" in command
    assert "--appearance-detailed-profile" in command
    assert "--no-background-room-box-prior" in command
    assert "--no-model-cache" not in command


def test_baseline_background_command_preserves_no_cache(tmp_path):
    command = build_background_command(
        _write_source_log(tmp_path),
        python="python3",
        runner=Path("runner.py"),
        source_manifest=Path("source.json"),
        output_root=Path("target"),
        policy="official",
        model_cache=False,
    )
    assert "--no-model-cache" in command
    assert "--background-room-box-prior" in command
    assert "--no-background-room-box-prior" not in command


@pytest.mark.parametrize("resolution", [0, 127, 129, 544])
def test_reject_invalid_decode_resolution(tmp_path, resolution):
    with pytest.raises(ValueError, match="decode_resolution"):
        build_background_command(
            _write_source_log(tmp_path),
            python="python3",
            runner=Path("runner.py"),
            source_manifest=Path("source.json"),
            output_root=Path("target"),
            policy="official",
            decode_resolution=resolution,
        )


def test_run_identifier_contract():
    assert validate_run_id("bg-384_v1") == "bg-384_v1"
    for value in ("", "../escape", "含中文"):
        with pytest.raises(ValueError, match="invalid run"):
            validate_run_id(value)


def test_prepare_runtime_cache_uses_one_root(tmp_path, monkeypatch):
    for name in (
        "TORCH_HOME",
        "CUDA_CACHE_PATH",
        "TORCH_EXTENSIONS_DIR",
        "TORCHINDUCTOR_CACHE_DIR",
        "TRITON_CACHE_DIR",
        "FLEX_GEMM_AUTOTUNE_CACHE_PATH",
    ):
        monkeypatch.delenv(name, raising=False)
    paths = prepare_runtime_cache(str(tmp_path))
    assert paths["TORCH_HOME"] == str(tmp_path / "torch")
    assert paths["FLEX_GEMM_AUTOTUNE_CACHE_PATH"] == str(
        tmp_path / "flex-gemm" / "autotune_cache.json"
    )
    assert (tmp_path / "flex-gemm").is_dir()


def test_background_worker_snapshots_models_without_reloading_open_runtime_cache():
    source = Path("modal_fire3d/background_app.py").read_text(encoding="utf-8")
    assert "enable_memory_snapshot=True" in source
    assert 'experimental_options={"enable_gpu_snapshot": True}' in source
    assert "@modal.enter(snap=True)" in source
    assert "preload_model_cache(command[2:])" in source
    restore = source[source.index("def load_after_restore") : source.index("@modal.method()", source.index("def load_after_restore"))]
    assert "outputs.reload()" in restore
    assert "runtime_cache.reload()" not in restore
