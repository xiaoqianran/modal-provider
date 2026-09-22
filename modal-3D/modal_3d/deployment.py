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
                "app": "modal-3d-mesh",
                "module": "modal_3d.mesh_worker",
                "kind": "worker",
                "revision": revision,
                "weightless": True,
                "weights": [],
            },
            {
                "app": "modal-3d-p3sam",
                "secrets": ["huggingface"],
                "module": "modal_3d.p3sam_worker",
                "kind": "worker",
                "models": ["segment_parts"],
                "revision": revision,
                "weights": _weights(
                    "modal-3d-p3sam-weights",
                    ["p3sam/p3sam.safetensors", "sonata/sonata.pth"],
                ),
            },
            {
                "app": "modal-3d-xpart",
                "secrets": ["huggingface"],
                "module": "modal_3d.xpart_worker",
                "kind": "worker",
                "models": ["complete_parts"],
                "revision": revision,
                "weights": _weights(
                    "modal-3d-xpart-weights",
                    [
                        "tencent/Hunyuan3D-Part/model/model.safetensors",
                        "tencent/Hunyuan3D-Part/conditioner/conditioner.safetensors",
                        "tencent/Hunyuan3D-Part/shapevae/shapevae.safetensors",
                        "tencent/Hunyuan3D-Part/scheduler/config.json",
                    ],
                ),
            },
            {
                "app": "modal-3d-hunyuan-paint",
                "module": "modal_3d.hunyuan_paint_worker",
                "kind": "worker",
                "models": ["texture_generate"],
                "revision": revision,
                "weights": _weights(
                    "modal-3d-hunyuan-paint-weights",
                    [
                        "Hunyuan3D-2.1/hunyuan3d-paintpbr-v2-1/model_index.json",
                        "RealESRGAN_x4plus.pth",
                    ],
                ),
            },
            {
                "app": "modal-3d-hunyuan2mv",
                "module": "modal_3d.hunyuan2mv_worker",
                "kind": "worker",
                "models": ["multiview_to_3d"],
                "revision": revision,
                "weights": _weights(
                    "modal-3d-hunyuan2mv-weights",
                    [
                        "Hunyuan3D-2mv/hunyuan3d-dit-v2-mv/config.yaml",
                        "Hunyuan3D-2mv/hunyuan3d-dit-v2-mv/model.fp16.safetensors",
                    ],
                ),
            },
            {
                "app": "modal-3d-tokenrig",
                "module": "modal_3d.tokenrig_worker",
                "kind": "worker",
                "models": ["rig"],
                "revision": revision,
                "weights": _weights(
                    "modal-3d-tokenrig-weights",
                    [
                        "tokenrig/experiments/skin_vae_2_10_32768/last.ckpt",
                        "tokenrig/experiments/articulation_xl_quantization_256_token_4/grpo_1400.ckpt",
                        "tokenrig/models/Qwen3-0.6B/config.json",
                    ],
                ),
            },
            {
                "app": "modal-3d-pose",
                "module": "modal_3d.pose_worker",
                "kind": "worker",
                "models": ["pose"],
                "revision": revision,
                "weightless": True,
                "weights": [],
            },
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
                "secrets": ["huggingface"],
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
                "secrets": ["huggingface"],
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
                "secrets": ["huggingface"],
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
                "secrets": ["huggingface"],
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
