from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from modal_world.contracts import Operation, WorldRequest
from PIL import Image

from modal_fire3d.backend import Fire3DBackend
from modal_fire3d.preprocess import (
    CAMERA_SCHEMA,
    PREPROCESS_SCHEMA,
    Pi3Prediction,
    PreparedDataset,
    build_fire3d_point_grid,
    materialize_prepared_dataset,
    recover_pinhole_intrinsics,
)


def _synthetic_prediction(height: int = 56, width: int = 70) -> Pi3Prediction:
    yy, xx = np.indices((height, width), dtype=np.float32)
    fx = 62.0
    fy = 64.0
    cx = (width - 1) / 2
    cy = (height - 1) / 2
    depth = 2.0 + xx * 0.002 + yy * 0.001
    points = np.stack(
        [
            (xx - cx) / fx * depth,
            (yy - cy) / fy * depth,
            depth,
        ],
        axis=-1,
    ).astype(np.float32)
    return Pi3Prediction(
        local_points=points,
        confidence=np.ones((height, width), dtype=np.float32),
        edge_mask=np.zeros((height, width), dtype=bool),
        model_input_size=(height, width),
        model_id="synthetic/Pi3",
        model_revision="test-revision",
        camera_pose=np.eye(4, dtype=np.float64),
    )


def _read_ply_vertex_count(path: Path) -> tuple[int, np.ndarray]:
    payload = path.read_bytes()
    header, body = payload.split(b"end_header\n", 1)
    count_line = next(line for line in header.splitlines() if line.startswith(b"element vertex "))
    count = int(count_line.split()[-1])
    points = np.frombuffer(body, dtype="<f4").reshape(count, 3)
    return count, points


def test_recover_pinhole_intrinsics_from_pi3_local_points():
    prediction = _synthetic_prediction()
    k = recover_pinhole_intrinsics(prediction.local_points)
    assert k[0, 0] == pytest.approx(62.0, abs=1e-3)
    assert k[1, 1] == pytest.approx(64.0, abs=1e-3)
    assert k[0, 2] == pytest.approx((70 - 1) / 2, abs=1e-3)
    assert k[1, 2] == pytest.approx((56 - 1) / 2, abs=1e-3)


def test_build_fire3d_grid_keeps_exact_half_resolution_and_nan_invalids():
    prediction = _synthetic_prediction()
    confidence = prediction.confidence.copy()
    confidence[:, :12] = 0.0
    prediction = Pi3Prediction(
        local_points=prediction.local_points,
        confidence=confidence,
        edge_mask=prediction.edge_mask,
        model_input_size=prediction.model_input_size,
        model_id=prediction.model_id,
        model_revision=prediction.model_revision,
    )
    grid, valid, k_native = build_fire3d_point_grid(
        prediction,
        native_size=(101, 133),
        confidence_threshold=0.1,
    )
    assert grid.shape == (50, 66, 3)
    assert valid.shape == (50, 66)
    assert np.isnan(grid[~valid]).all()
    assert np.isfinite(grid[valid]).all()
    assert 0.0 < valid.mean() < 1.0
    assert np.isfinite(k_native).all()


def test_materialize_png_as_fire3d_single_image_dataset(tmp_path: Path):
    source = tmp_path / "source.png"
    rgba = Image.new("RGBA", (133, 101), (10, 20, 30, 128))
    rgba.save(source)

    prepared = materialize_prepared_dataset(
        source,
        _synthetic_prediction(),
        data_root=tmp_path / "prepared",
        scene_id="scene123",
    )
    scene = prepared.scene_dir
    assert scene == tmp_path / "prepared/single_image/data/scene123"
    assert (scene / "rgb.jpeg").is_file()
    assert Image.open(scene / "rgb.jpeg").size == (133, 101)
    assert (prepared.dataset_root / "single_image_valid.txt").read_text().strip() == "scene123"

    vertex_count, points = _read_ply_vertex_count(scene / "aligned_pcd.ply")
    assert vertex_count == (101 // 2) * (133 // 2)
    assert points.shape == (3300, 3)
    assert np.isfinite(points).all()

    camera = json.loads((scene / "camera.json").read_text(encoding="utf-8"))
    assert camera["schema"] == CAMERA_SCHEMA
    assert camera["native"]["width"] == 133
    assert camera["native"]["height"] == 101
    assert camera["reconstruction"]["width"] % 32 == 0
    assert camera["reconstruction"]["height"] % 32 == 0

    manifest = json.loads(prepared.manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema"] == PREPROCESS_SCHEMA
    assert manifest["geometry"]["vertex_count"] == 3300
    assert manifest["geometry"]["ordered_row_major"] is True
    assert manifest["source"]["alpha_composited_on_white"] is True
    assert manifest["coordinate_contract"]["ground_alignment_verified"] is False
    assert prepared.valid_ratio == 1.0


def test_backend_raw_image_path_prepares_then_runs_same_fire3d_contract(tmp_path, monkeypatch):
    from modal_fire3d import pi3_preprocessor

    source = tmp_path / "source.jpg"
    Image.new("RGB", (96, 80), (20, 40, 60)).save(source)
    fire3d_root = tmp_path / "Fire3D"
    (fire3d_root / "fire3d").mkdir(parents=True)
    (fire3d_root / "fire3d/cli.py").write_text("# test\n", encoding="utf-8")
    output = tmp_path / "out"

    def fake_prepare(image_path, *, data_root, scene_id=None, **_kwargs):
        assert image_path == source.resolve()
        resolved_scene = scene_id or "rawscene"
        dataset_root = data_root / "single_image"
        scene_dir = dataset_root / "data" / resolved_scene
        scene_dir.mkdir(parents=True)
        manifest = scene_dir / "preprocess.json"
        manifest.write_text("{}", encoding="utf-8")
        return PreparedDataset(
            data_root=data_root,
            dataset_root=dataset_root,
            scene_dir=scene_dir,
            scene_id=resolved_scene,
            manifest_path=manifest,
            valid_ratio=0.9,
        )

    monkeypatch.setattr(pi3_preprocessor, "prepare_raw_image", fake_prepare)
    monkeypatch.setattr(pi3_preprocessor, "release_pi3_models", lambda: None)

    captured: dict[str, object] = {}

    def fake_run(command, **_kwargs):
        captured["command"] = command
        scene_id = "rawscene"
        recon = output / "reconstruction" / scene_id
        (recon / "appearance/objects/0001").mkdir(parents=True)
        (recon / "appearance/predicted_textured_world_scene.glb").write_bytes(b"glb")
        (recon / "appearance/objects/0001/canonical.glb").write_bytes(b"obj")
        (recon / "appearance/appearance_summary.json").write_text("{}", encoding="utf-8")
        (recon / "inference_summary.json").write_text(
            json.dumps({"status": "complete"}), encoding="utf-8"
        )
        (output / "summary.json").write_text("{}", encoding="utf-8")
        (output / "resolved_protocol.json").write_text("{}", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr("modal_fire3d.backend.subprocess.run", fake_run)
    result = Fire3DBackend().run(
        WorldRequest(
            operation=Operation.RECONSTRUCT,
            input_path=source,
            output_dir=output,
            options={
                "fire3d_root": str(fire3d_root),
                "background_policy": "official",
            },
        )
    )

    command = captured["command"]
    data_root_index = command.index("--data-root") + 1
    assert Path(command[data_root_index]) == (output / "_prepared_input").resolve()
    assert result.metadata["input_kind"] == "raw_image"
    assert result.metadata["scene_id"] == "rawscene"
    assert result.metadata["preparation"]["valid_ratio"] == 0.9
    assert any(artifact.role == "world-mesh" for artifact in result.artifacts)

