from __future__ import annotations

from typing import Any

ARTIFACT_VOLUME_NAME = "modal-build-artifacts"

HYWORLD2_ARTIFACT_BUNDLES: tuple[dict[str, Any], ...] = (
    {"tag": "hyworld2-hy-native-py311-cu128-torch271-sm120-v1", "archive_sha256": "094e611679e02135e7f4e746d63554145d960aa52c3392ab5db8e1a6bc69f87a", "public_release": False},
    {"tag": "hyworld2-oss-native-py311-cu128-torch271-sm120-v1", "archive_sha256": "2c6b787925dbbbd7df389d77d548db2639f18113705686586bf85ca63902a746", "public_release": True},
    {"tag": "hyworld2-oss-source-py311-v1", "archive_sha256": "c294c84b2645a5105fe911e519927f016956c73058c5e8a97acea375a4ac94b6", "public_release": False},
    {"tag": "hyworld2-flash-attn-py311-cu128-torch271-sm120-v1", "archive_sha256": "7653177eb13c6056066f72cd27c1e3f540ada13d9d6dbf65e5657930e7522952", "public_release": True},
)

HYWORLD2_STAGE2_H100_ARTIFACT_BUNDLES: tuple[dict[str, Any], ...] = (
    {"tag": "hyworld2-hy-native-py311-cu128-torch271-sm90-v1", "archive_sha256": "e6f8459e025e51f9e6e7b4796a2d92d46dd33396c868d1b039423de31025f2f1", "public_release": False},
    {"tag": "hyworld2-oss-native-py311-cu128-torch271-sm90-v1", "archive_sha256": "3fe4262b29c3d0833b1cd9ada29925f7a54fccd856e879888b849c29f650bad5", "public_release": True},
    {"tag": "hyworld2-flash-attn-py311-cu128-torch271-sm90-v1", "archive_sha256": "fe0aa7c0c08df04b472b9557170272f9f8aed2c23f162b6d6ecd50cfab9ef5ab", "public_release": True},
)

HYWORLD2_STAGE3_H100_ARTIFACT_BUNDLES: tuple[dict[str, Any], ...] = (
    {"tag": "hyworld2-stage3-native-py311-cu128-torch271-sm90-v1", "archive_sha256": "1b95fa8ef2531ee97ac14648528b816650059a4a7a086a5c3901fd69859ab794", "public_release": True},
    {"tag": "hyworld2-flash-attn-py311-cu128-torch271-sm90-v1", "archive_sha256": "fe0aa7c0c08df04b472b9557170272f9f8aed2c23f162b6d6ecd50cfab9ef5ab", "public_release": True},
)

HYWORLD2_STAGE5_H100_ARTIFACT_BUNDLES: tuple[dict[str, Any], ...] = (
    {"tag": "hyworld2-hy-native-py311-cu128-torch271-sm90-v1", "archive_sha256": "e6f8459e025e51f9e6e7b4796a2d92d46dd33396c868d1b039423de31025f2f1", "public_release": False},
    {"tag": "hyworld2-oss-native-py311-cu128-torch271-sm90-v1", "archive_sha256": "3fe4262b29c3d0833b1cd9ada29925f7a54fccd856e879888b849c29f650bad5", "public_release": True},
)

_RECOVERY_MODULE = {
    "hyworld2-hy-native-py311-cu128-torch271-sm120-v1": "integrations.hyworld2.build.hyworld2_hy_native_sm120",
    "hyworld2-oss-native-py311-cu128-torch271-sm120-v1": "integrations.hyworld2.restore",
    "hyworld2-oss-source-py311-v1": "integrations.hyworld2.build.hyworld2_oss_source_wheels",
    "hyworld2-flash-attn-py311-cu128-torch271-sm120-v1": "integrations.hyworld2.restore",
    "hyworld2-hy-native-py311-cu128-torch271-sm90-v1": "integrations.hyworld2.build.hyworld2_hy_native_sm90",
    "hyworld2-oss-native-py311-cu128-torch271-sm90-v1": "integrations.hyworld2.build.hyworld2_oss_native_sm90",
    "hyworld2-flash-attn-py311-cu128-torch271-sm90-v1": "integrations.hyworld2.restore",
    "hyworld2-stage3-native-py311-cu128-torch271-sm90-v1": "integrations.hyworld2.restore",
}


def all_artifact_bundles() -> tuple[dict[str, Any], ...]:
    rows: dict[str, dict[str, Any]] = {}
    for group in (
        HYWORLD2_ARTIFACT_BUNDLES,
        HYWORLD2_STAGE2_H100_ARTIFACT_BUNDLES,
        HYWORLD2_STAGE3_H100_ARTIFACT_BUNDLES,
        HYWORLD2_STAGE5_H100_ARTIFACT_BUNDLES,
    ):
        for bundle in group:
            tag = str(bundle["tag"])
            existing = rows.get(tag)
            if existing is not None and existing != bundle:
                raise RuntimeError(f"conflicting HYWorld2 bundle definition: {tag}")
            rows[tag] = dict(bundle)
    return tuple(rows.values())


def deployment_prerequisites() -> list[dict[str, object]]:
    """Deployment prerequisites needed before importing any HYWorld2 Modal app module."""
    result: list[dict[str, object]] = []
    for bundle in all_artifact_bundles():
        tag = str(bundle["tag"])
        sha = str(bundle["archive_sha256"])
        module = _RECOVERY_MODULE[tag]
        if module.endswith(".restore"):
            prepare = {"module": module, "function": "restore_public_bundle", "arguments": [tag, sha]}
        else:
            prepare = {"module": module, "function": "build"}
        result.append(
            {
                "volume": ARTIFACT_VOLUME_NAME,
                "requiredPaths": [
                    f"{tag}.wheels.zip",
                    f"{tag}.manifest.json",
                    f"{tag}.wheels.zip.sha256",
                ],
                "prepare": [prepare],
            }
        )
    return result
