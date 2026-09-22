from __future__ import annotations

import json
import math
import os
import shutil
import tempfile
import time
from pathlib import Path

import modal

from .common import ARTIFACT_VOLUME
from .operation_runner import validate_file
from .operations import (
    MIMES,
    RESULT_CONTRACT,
    confined,
    digest_file,
    options_for,
    request_key,
    revision_for,
    validate_descriptor,
    validate_input_names,
)

APP_NAME = "modal-3d-pose"

app = modal.App(APP_NAME)
artifacts = modal.Volume.from_name(ARTIFACT_VOLUME, create_if_missing=True)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("libgl1", "libglib2.0-0", "libx11-6", "libxi6", "libxxf86vm1")
    .uv_pip_install("bpy==4.2.0", "mathutils==3.3.0", uv_version="0.12.5")
    .apt_install(
        "libxrender1",
        "libxfixes3",
        "libxcursor1",
        "libxinerama1",
        "libxrandr2",
        "libxkbcommon0",
        "libsm6",
        "libice6",
    )
    .run_commands("python -c \"import bpy; print('bpy', bpy.app.version_string)\"")
)

_MIXAMO = {
    "left_upper_arm": "mixamorig:LeftArm",
    "right_upper_arm": "mixamorig:RightArm",
}
_VROID = {
    "left_upper_arm": "J_Bip_L_UpperArm",
    "right_upper_arm": "J_Bip_R_UpperArm",
}


def _chain_depth(bone) -> int:
    children = list(bone.children)
    return 1 + max((_chain_depth(child) for child in children), default=0)


def _tokenrig_mapping(armature) -> dict[str, str] | None:
    bones = list(armature.data.bones)
    token_bones = [
        bone
        for bone in bones
        if bone.name.startswith("bone_") and bone.name[5:].isdigit()
    ]
    if len(token_bones) < 20 or len(token_bones) * 4 < len(bones) * 3:
        return None

    candidates: list[tuple[int, float, object, object]] = []
    for parent in token_bones:
        branches = sorted(
            list(parent.children),
            key=_chain_depth,
            reverse=True,
        )
        long_branches = [branch for branch in branches if _chain_depth(branch) >= 4]
        if len(long_branches) < 2:
            continue
        first, second = long_branches[:2]
        first_x = float(first.head_local.x)
        second_x = float(second.head_local.x)
        if first_x * second_x >= 0 or min(abs(first_x), abs(second_x)) < 1e-4:
            continue
        score = _chain_depth(first) + _chain_depth(second)
        spread = abs(first_x - second_x)
        candidates.append((score, spread, first, second))

    if not candidates:
        return None

    _, _, first, second = max(candidates, key=lambda row: (row[0], row[1]))
    left = first if float(first.head_local.x) > float(second.head_local.x) else second
    right = second if left is first else first
    return {
        "left_upper_arm": left.name,
        "right_upper_arm": right.name,
    }


def _profile(armature, requested: str) -> tuple[str, dict[str, str]]:
    names = {bone.name for bone in armature.pose.bones}
    named_profiles = {
        "mixamo": _MIXAMO,
        "vroid": _VROID,
    }
    if requested in named_profiles:
        mapping = named_profiles[requested]
        if all(name in names for name in mapping.values()):
            return requested, mapping
    elif requested == "tokenrig":
        mapping = _tokenrig_mapping(armature)
        if mapping is not None:
            return "tokenrig", mapping
    elif requested == "auto":
        for profile, mapping in named_profiles.items():
            if all(name in names for name in mapping.values()):
                return profile, mapping
        mapping = _tokenrig_mapping(armature)
        if mapping is not None:
            return "tokenrig", mapping

    raise ValueError(
        "unsupported skeleton for pose: expected Mixamo, VRoid, or TokenRig upper-arm semantics"
    )


def _load_glb(path: Path):
    import bpy

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=str(path), import_pack_images=True)
    armatures = [obj for obj in bpy.context.scene.objects if obj.type == "ARMATURE"]
    if len(armatures) != 1:
        raise ValueError(f"pose requires exactly one armature, found {len(armatures)}")
    return armatures[0]


def _set_pose(armature, preset: str, mapping: dict[str, str]) -> dict:
    from mathutils import Vector

    for bone in armature.pose.bones:
        bone.rotation_mode = "QUATERNION"
        bone.rotation_quaternion.identity()

    if preset == "rest":
        return {"arm_angle_deg": None}

    # TokenRig/character datasets use Y-up meshes after glTF import into Blender.
    # Set upper-arm directions in armature space. T pose is horizontal; A pose is
    # 35 degrees downward from horizontal.
    z = 0.0 if preset == "t_pose" else -math.sin(math.radians(35.0))
    x = math.cos(math.radians(35.0)) if preset == "a_pose" else 1.0
    targets = {
        "left_upper_arm": Vector((x, 0.0, z)).normalized(),
        "right_upper_arm": Vector((-x, 0.0, z)).normalized(),
    }
    for semantic, target in targets.items():
        bone = armature.pose.bones[mapping[semantic]]
        rest = bone.bone.vector.normalized()
        bone.rotation_quaternion = rest.rotation_difference(target)

    return {"arm_angle_deg": 0.0 if preset == "t_pose" else 35.0}


def _export(path: Path) -> None:
    import bpy

    bpy.context.scene.frame_set(0)
    bpy.ops.export_scene.gltf(
        filepath=str(path),
        export_format="GLB",
        export_animations=False,
        export_yup=True,
    )


def _descriptor(path: Path, role: str, destination: Path, root: Path) -> dict:
    mime = MIMES[path.suffix]
    validate_file(
        path,
        mime,
        glb_mode="posed" if mime == MIMES[".glb"] else "static",
    )
    digest = digest_file(path)
    return {
        "id": f"art_{digest}",
        "role": role,
        "mime": mime,
        "mediaType": mime,
        "bytes": path.stat().st_size,
        "sha256": digest,
        "digest": f"sha256:{digest}",
        "filename": path.name,
        "path": (destination / path.name).relative_to(root).as_posix(),
    }


@app.cls(
    image=image,
    volumes={"/artifacts": artifacts},
    cpu=4,
    memory=8192,
    min_containers=0,
    max_containers=1,
    scaledown_window=120,
    timeout=15 * 60,
)
class Model:
    @modal.method()
    def run_job(self, request: dict, options: dict | None = None) -> dict:
        started = time.monotonic()
        if not isinstance(request, dict) or request.get("operation") != "pose":
            raise ValueError("pose worker only supports pose")

        inputs = validate_input_names("pose", request.get("inputs"))
        normalized = options_for("pose", options)
        root = Path("/artifacts").resolve()
        artifacts.reload()

        source_desc = validate_descriptor(inputs["asset"])
        if source_desc["mime"] != MIMES[".glb"]:
            raise ValueError("pose input must be a GLB")
        source = confined(root, source_desc["path"])
        validate_file(source, MIMES[".glb"], glb_mode="rigged")
        if source.stat().st_size != source_desc["bytes"] or digest_file(source) != source_desc["sha256"]:
            raise ValueError("pose input integrity mismatch")

        key = request_key("pose", {"asset": source_desc}, normalized)
        destination = root / "operations" / "pose" / key
        manifest = destination / "result.json"
        if manifest.is_file():
            result = json.loads(manifest.read_text(encoding="utf-8"))
            for desc in result["artifacts"]:
                cached = confined(root, desc["path"])
                validate_file(
                    cached,
                    desc["mime"],
                    glb_mode="posed" if desc["mime"] == MIMES[".glb"] else "static",
                )
                if digest_file(cached) != desc["sha256"]:
                    raise ValueError("cached pose artifact corrupted")
            return {**result, "cache_hit": True}

        with tempfile.TemporaryDirectory(prefix="pose-") as temporary:
            work = Path(temporary)
            armature = _load_glb(source)
            profile, mapping = _profile(armature, normalized["skeleton_profile"])
            pose_metrics = _set_pose(armature, normalized["preset"], mapping)
            output = work / "posed.glb"
            _export(output)
            validate_file(output, MIMES[".glb"], glb_mode="posed")

            report = {
                "schema": "modal-3d.pose-report.v1",
                "preset": normalized["preset"],
                "skeleton_profile": profile,
                "armature": armature.name,
                "bones": len(armature.pose.bones),
                **pose_metrics,
            }
            report_path = work / "pose-report.json"
            report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
            quality_path = work / "quality-report.json"
            quality_path.write_text(
                json.dumps(
                    {
                        "schema": "modal-3d.quality-report.v1",
                        "operation": "pose",
                        "skeleton_profile": profile,
                        "bones": len(armature.pose.bones),
                        "skin_preserved": True,
                        "animation_tracks": 0,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            descriptors = [
                _descriptor(output, "primary-glb", destination, root),
                _descriptor(report_path, "pose-report", destination, root),
                _descriptor(quality_path, "quality-report", destination, root),
            ]
            result = {
                "contract": RESULT_CONTRACT,
                "operation": "pose",
                "revision": revision_for("pose"),
                "request_key": key,
                "inputs": {"asset": source_desc},
                "options": normalized,
                "artifacts": descriptors,
                "metrics": report,
                "timing": {"total_s": time.monotonic() - started},
                "cache_hit": False,
            }

            destination.mkdir(parents=True, exist_ok=True)
            for desc in descriptors:
                shutil.copyfile(work / desc["filename"], destination / desc["filename"])
            pending = destination / "result.pending"
            pending.write_text(json.dumps(result, indent=2), encoding="utf-8")
            os.replace(pending, manifest)
            artifacts.commit()
            return result
