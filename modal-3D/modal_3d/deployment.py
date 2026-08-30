from __future__ import annotations

import hashlib
from pathlib import Path


def _weights(volume: str, required_paths: list[str]) -> list[dict[str, object]]:
    return [
        {
            "volume": volume,
            "requiredPaths": required_paths,
            "prepare": [{"function": "sync_weights"}],
        }
    ]


def runtime_revision() -> str:
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return f"sha256-{digest.hexdigest()[:32]}"


def deployment_manifest() -> dict[str, object]:
    revision = runtime_revision()
    return {
        "provider": "modal-3d",
        "targets": [
            {
                "app": "modal-3d-rembg",
                "module": "modal_3d.rembg_worker",
                "kind": "preprocess",
                "required": True,
                "revision": revision,
                "weights": _weights(
                    "modal-3d-birefnet-weights",
                    [
                        "rembg/manifest.json",
                        "rembg/models/birefnet-general-lite/birefnet-general-lite.onnx",
                    ],
                ),
            },
            {
                "app": "modal-3d-fastsam3d",
                "module": "modal_3d.fastsam3d_plus_plus",
                "kind": "worker",
                "models": ["fastsam3d-plus-plus"],
                "revision": revision,
                "weights": _weights(
                    "modal-3d-fastsam3d-weights",
                    ["sam3d/checkpoints/pipeline.fast.yaml"],
                ),
            },
            {
                "app": "modal-3d-hunyuan",
                "module": "modal_3d.hunyuan2_1_plus_plus",
                "kind": "worker",
                "models": ["hunyuan2.1-plus-plus"],
                "revision": revision,
                "weights": _weights(
                    "modal-3d-hunyuan21-weights",
                    ["RealESRGAN_x4plus.pth"],
                ),
            },
            {
                "app": "modal-3d-hermit-trellis2-plus-plus",
                "module": "modal_3d.hermit_trellis2_plus_plus",
                "kind": "worker",
                "models": ["hermit-trellis2-plus-plus"],
                "revision": revision,
                "weights": _weights(
                    "modal-3d-trellis2-weights",
                    ["TRELLIS.2-4B/pipeline.modal.json"],
                ),
            },
            {
                "app": "modal-3d-pixal3d",
                "module": "modal_3d.pixal3d",
                "kind": "worker",
                "models": ["pixal3d"],
                "revision": revision,
                "weights": _weights(
                    "modal-3d-pixal3d-weights",
                    ["torch/hub/checkpoints/naf_release.pth"],
                ),
            },
        ],
    }
