from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from modal_world.backend import (
    BackendUnavailable,
    UnsupportedOperation,
    WorldBackend,
    WorldBackendError,
)
from modal_world.contracts import Artifact, Capability, Operation, WorldRequest, WorldResult

from .background_policy import write_background_protocol
from .preprocess import is_raw_image

FIRE3D_REVISION = "2368dd2f3909120cf90bbf8a17807abe9c41e600"
OFFICIAL_EXAMPLES = {
    "ithor": "iTHOR_FloorPlan312_physics",
    "imaginarium": "bedroom_01",
    "scannetpp": "09bced689e",
    "single_image": "003025",
}


class Fire3DBackend(WorldBackend):
    """Adapter for the official Fire3D release CLI.

    Single-image runs default to the observed-background repair policy. Prepared
    datasets remain accepted directly; JPG/PNG inputs are first converted into the
    same native single-image contract through the paper's Pi3 geometry path.
    """

    name = "fire3d"
    _capability = Capability(
        backend=name,
        operations=frozenset({Operation.RECONSTRUCT}),
        inputs=frozenset({"prepared_dataset", "image/jpeg", "image/png"}),
        outputs=frozenset(
            {
                "world_scene_glb",
                "object_meshes",
                "pbr_meshes",
                "perception",
                "oriented_boxes",
                "manifest",
            }
        ),
        notes=(
            "single-image background preserves observations; official policy remains selectable",
            "single_image_v1 expects aligned RGB + point-cloud release input",
            "raw JPG/PNG is prepared with Pi3 into the native ordered point-grid contract",
            "foreground objects are exported as independent canonical GLBs",
            "raw-image geometry uses the Pi3 single-camera reference frame; gravity is not invented",
        ),
    )

    @property
    def capability(self) -> Capability:
        return self._capability

    def run(self, request: WorldRequest) -> WorldResult:
        req = request.normalized()
        if req.operation is not Operation.RECONSTRUCT:
            raise UnsupportedOperation(f"unsupported Fire3D operation: {req.operation}")
        return self.reconstruct(req)

    def reconstruct(self, request: WorldRequest) -> WorldResult:
        if not request.input_path.exists():
            raise FileNotFoundError(request.input_path)
        request.output_dir.mkdir(parents=True, exist_ok=True)

        options = dict(request.options)
        root_value = options.get("fire3d_root") or os.environ.get("FIRE3D_ROOT")
        if not root_value:
            raise BackendUnavailable(
                "Fire3D requires options.fire3d_root or FIRE3D_ROOT pointing to the pinned checkout"
            )
        root = Path(str(root_value)).expanduser().resolve()
        if not (root / "fire3d" / "cli.py").is_file():
            raise BackendUnavailable(f"Fire3D checkout is incomplete: {root}")

        dataset = str(options.get("dataset", "single_image"))
        if dataset not in OFFICIAL_EXAMPLES:
            raise ValueError(f"unsupported Fire3D release dataset: {dataset}")
        raw_image = is_raw_image(request.input_path)
        input_kind = "raw_image" if raw_image else "prepared_dataset"
        preparation: dict[str, Any] | None = None
        requested_scene_id = options.get("scene_id")
        if raw_image:
            if dataset != "single_image":
                raise ValueError("raw JPG/PNG input is supported only for the single_image dataset")
            if options.get("data_root"):
                raise ValueError("data_root cannot be supplied for raw JPG/PNG input")
            from .pi3_preprocessor import (
                PI3_CONFIDENCE_THRESHOLD,
                PI3_EDGE_RTOL,
                PI3_PIXEL_LIMIT,
                PI3_SOURCE,
                prepare_raw_image,
                release_pi3_models,
            )

            try:
                prepared = prepare_raw_image(
                    request.input_path,
                    data_root=request.output_dir / "_prepared_input",
                    scene_id=str(requested_scene_id) if requested_scene_id else None,
                    pi3_root=Path(
                        str(options.get("pi3_root") or os.environ.get("PI3_ROOT") or PI3_SOURCE)
                    ),
                    device=str(options.get("pi3_device", "cuda")),
                    pixel_limit=int(options.get("pi3_pixel_limit", PI3_PIXEL_LIMIT)),
                    confidence_threshold=float(
                        options.get("pi3_confidence_threshold", PI3_CONFIDENCE_THRESHOLD)
                    ),
                    edge_rtol=float(options.get("pi3_edge_rtol", PI3_EDGE_RTOL)),
                    jpeg_quality=int(options.get("jpeg_quality", 95)),
                )
            finally:
                # FIRE3D runs in a child process and needs the full H100 budget.
                # Do not leave the 1B Pi3 model resident in the parent process.
                release_pi3_models()
            scene_id = prepared.scene_id
            data_root = prepared.data_root
            preparation = {
                "manifest": str(prepared.manifest_path),
                "dataset_root": str(prepared.dataset_root),
                "scene_dir": str(prepared.scene_dir),
                "valid_ratio": prepared.valid_ratio,
            }
        else:
            scene_id = str(requested_scene_id or OFFICIAL_EXAMPLES[dataset])
            data_root = Path(str(options.get("data_root") or request.input_path)).expanduser().resolve()
        python = str(options.get("python", sys.executable))
        skip_render = bool(options.get("skip_render", True))
        skip_existing = bool(options.get("skip_existing", False))
        gpu = str(options.get("gpu", "0"))
        background_policy = str(options.get(
            "background_policy", "observed_single_image" if dataset == "single_image" else "official"
        ))
        protocol_path = write_background_protocol(
            root, request.output_dir, dataset, background_policy
        )

        command = [
            python,
            "-m",
            "fire3d",
            "infer",
            "--dataset",
            dataset,
            "--scene-id",
            scene_id,
            "--data-root",
            str(data_root),
            "--output-root",
            str(request.output_dir),
            "--gpu",
            gpu,
        ]
        if protocol_path:
            command.extend(["--protocol", str(protocol_path.resolve())])
        if skip_render:
            command.append("--skip-render")
        if skip_existing:
            command.append("--skip-existing")

        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            item for item in (str(root), env.get("PYTHONPATH", "")) if item
        )
        extra_env = options.get("env", {})
        if not isinstance(extra_env, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in extra_env.items()
        ):
            raise ValueError("env must be a string-to-string mapping")
        env.update(extra_env)

        try:
            completed = subprocess.run(
                command,
                cwd=root,
                env=env,
                text=True,
                capture_output=True,
                check=False,
                timeout=float(options.get("timeout_s", 2 * 60 * 60)),
            )
        except FileNotFoundError as exc:
            raise BackendUnavailable(f"Fire3D python executable unavailable: {python}") from exc
        except subprocess.TimeoutExpired as exc:
            raise WorldBackendError("Fire3D reconstruction timed out") from exc

        if completed.returncode != 0:
            raise WorldBackendError(
                "Fire3D reconstruction failed with exit "
                f"{completed.returncode}: {completed.stderr[-6000:].strip()}"
            )

        summary = self._validate_official_result(request.output_dir, scene_id)
        artifacts = self._discover_artifacts(request.output_dir, scene_id)
        return WorldResult(
            backend=self.name,
            operation=Operation.RECONSTRUCT,
            artifacts=artifacts,
            metadata={
                "official_revision": FIRE3D_REVISION,
                "dataset": dataset,
                "input_kind": input_kind,
                "background_policy": background_policy,
                "scene_id": scene_id,
                "skip_render": skip_render,
                "preparation": preparation,
                "summary": summary,
                "artifact_count": len(artifacts),
                "stdout_tail": completed.stdout[-6000:],
            },
        )

    @staticmethod
    def _validate_official_result(root: Path, scene_id: str) -> dict[str, Any]:
        summary_path = root / "summary.json"
        recon_summary_path = root / "reconstruction" / scene_id / "inference_summary.json"
        scene_glb = (
            root
            / "reconstruction"
            / scene_id
            / "appearance"
            / "predicted_textured_world_scene.glb"
        )
        for path in (summary_path, recon_summary_path, scene_glb):
            if not path.is_file():
                raise WorldBackendError(f"Fire3D official output is incomplete; missing {path}")
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        recon_summary = json.loads(recon_summary_path.read_text(encoding="utf-8"))
        if recon_summary.get("status") != "complete":
            raise WorldBackendError(
                f"Fire3D reconstruction did not complete: {recon_summary.get('status')!r}"
            )
        return {
            "pipeline": summary,
            "reconstruction": recon_summary,
            "scene_glb": str(scene_glb),
        }

    @staticmethod
    def _discover_artifacts(root: Path, scene_id: str) -> tuple[Artifact, ...]:
        recon_root = root / "reconstruction" / scene_id
        scene_glb = recon_root / "appearance" / "predicted_textured_world_scene.glb"
        appearance_summary = recon_root / "appearance" / "appearance_summary.json"
        inference_summary = recon_root / "inference_summary.json"
        protocol = root / "resolved_protocol.json"
        summary = root / "summary.json"

        found: list[Artifact] = []
        for path in sorted(recon_root.rglob("canonical.glb")):
            found.append(
                Artifact(
                    kind="mesh",
                    path=path,
                    role="world-object",
                    media_type="model/gltf-binary",
                )
            )
        if scene_glb.is_file():
            found.append(
                Artifact(
                    kind="scene",
                    path=scene_glb,
                    role="world-mesh",
                    media_type="model/gltf-binary",
                )
            )
        for path, role in (
            (appearance_summary, "world-manifest"),
            (inference_summary, "world-reconstruction-summary"),
            (protocol, "world-protocol"),
            (summary, "world-run-summary"),
        ):
            if path.is_file():
                found.append(
                    Artifact(kind="metadata", path=path, role=role, media_type="application/json")
                )
        for path in sorted((root / "perception").rglob("oriented_bboxes.json")):
            found.append(
                Artifact(
                    kind="metadata",
                    path=path,
                    role="world-semantics",
                    media_type="application/json",
                )
            )
        return tuple(found)
