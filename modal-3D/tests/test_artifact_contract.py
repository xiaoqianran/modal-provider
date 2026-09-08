from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from modal_3d.common import (
    ARTIFACT_ROOT,
    generation_result,
    validate_glb,
    validate_glb_quality,
)


def glb_bytes(*, version: int = 2, declared_delta: int = 0, payload: bytes = b"payload") -> bytes:
    size = 12 + len(payload)
    return (
        b"glTF"
        + version.to_bytes(4, "little")
        + (size + declared_delta).to_bytes(4, "little")
        + payload
    )


def quality_glb_bytes(document: dict) -> bytes:
    payload = json.dumps(document, separators=(",", ":")).encode("utf-8")
    payload += b" " * ((4 - len(payload) % 4) % 4)
    chunk = len(payload).to_bytes(4, "little") + b"JSON" + payload
    size = 12 + len(chunk)
    return b"glTF" + (2).to_bytes(4, "little") + size.to_bytes(4, "little") + chunk


class ArtifactContractTests(unittest.TestCase):
    def test_serialized_adapter_root_is_platform_neutral(self) -> None:
        self.assertIsInstance(ARTIFACT_ROOT, str)
        self.assertEqual(ARTIFACT_ROOT, "/artifacts")

    def _write(self, data: bytes) -> Path:
        with tempfile.NamedTemporaryFile(suffix=".glb", delete=False) as temp:
            temp.write(data)
            path = Path(temp.name)
        self.addCleanup(path.unlink, missing_ok=True)
        return path

    def test_valid_glb_returns_integrity_metadata(self) -> None:
        data = glb_bytes()
        result = validate_glb(self._write(data), len(data))
        self.assertEqual(result["bytes"], len(data))
        self.assertEqual(result["glb_version"], 2)
        self.assertEqual(result["sha256"], hashlib.sha256(data).hexdigest())

    def test_rejects_worker_volume_size_mismatch(self) -> None:
        data = glb_bytes()
        with self.assertRaisesRegex(ValueError, "byte count mismatch"):
            validate_glb(self._write(data), len(data) + 1)

    def test_rejects_glb_v1(self) -> None:
        data = glb_bytes(version=1)
        with self.assertRaisesRegex(ValueError, "version 2"):
            validate_glb(self._write(data), len(data))

    def test_rejects_declared_length_mismatch(self) -> None:
        data = glb_bytes(declared_delta=4)
        with self.assertRaisesRegex(ValueError, "declared length"):
            validate_glb(self._write(data), len(data))

    def test_vertex_color_guard_accepts_colored_geometry(self) -> None:
        data = quality_glb_bytes(
            {"meshes": [{"primitives": [{"attributes": {"POSITION": 0, "COLOR_0": 1}}]}]}
        )
        result = validate_glb_quality(self._write(data), "vertex_color")
        self.assertTrue(result["has_vertex_color"])

    def test_vertex_color_guard_rejects_uncolored_geometry(self) -> None:
        data = quality_glb_bytes(
            {"meshes": [{"primitives": [{"attributes": {"POSITION": 0}}]}]}
        )
        with self.assertRaisesRegex(ValueError, "COLOR_0"):
            validate_glb_quality(self._write(data), "vertex_color")

    def test_pbr_guard_accepts_webp_extension_textures(self) -> None:
        data = quality_glb_bytes(
            {
                "meshes": [
                    {
                        "primitives": [
                            {"attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "material": 0}
                        ]
                    }
                ],
                "materials": [
                    {
                        "pbrMetallicRoughness": {
                            "baseColorTexture": {"index": 0},
                            "metallicRoughnessTexture": {"index": 1},
                        }
                    }
                ],
                "textures": [
                    {"extensions": {"EXT_texture_webp": {"source": 0}}},
                    {"extensions": {"EXT_texture_webp": {"source": 1}}},
                ],
                "images": [
                    {"mimeType": "image/webp", "bufferView": 0},
                    {"mimeType": "image/webp", "bufferView": 1},
                ],
                "bufferViews": [{"byteLength": 128}, {"byteLength": 128}],
            }
        )
        result = validate_glb_quality(self._write(data), "pbr_textured")
        self.assertTrue(result["has_base_color_texture"])
        self.assertTrue(result["has_metallic_roughness_texture"])

    def test_pbr_guard_rejects_missing_metallic_roughness_texture(self) -> None:
        data = quality_glb_bytes(
            {
                "meshes": [
                    {
                        "primitives": [
                            {"attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "material": 0}
                        ]
                    }
                ],
                "materials": [
                    {"pbrMetallicRoughness": {"baseColorTexture": {"index": 0}}}
                ],
                "textures": [{"source": 0}],
                "images": [{"mimeType": "image/png", "bufferView": 0}],
                "bufferViews": [{"byteLength": 128}],
            }
        )
        with self.assertRaisesRegex(ValueError, "metallic/roughness"):
            validate_glb_quality(self._write(data), "pbr_textured")

    def test_vertex_color_guard_rejects_partially_uncolored_geometry(self) -> None:
        data = quality_glb_bytes(
            {
                "meshes": [
                    {
                        "primitives": [
                            {"attributes": {"POSITION": 0, "COLOR_0": 1}},
                            {"attributes": {"POSITION": 2}},
                        ]
                    }
                ]
            }
        )
        with self.assertRaisesRegex(ValueError, "missing COLOR_0"):
            validate_glb_quality(self._write(data), "vertex_color")

    def test_pbr_guard_requires_embedded_texture_bytes(self) -> None:
        data = quality_glb_bytes(
            {
                "meshes": [
                    {
                        "primitives": [
                            {"attributes": {"POSITION": 0, "TEXCOORD_0": 1}, "material": 0}
                        ]
                    }
                ],
                "materials": [
                    {
                        "pbrMetallicRoughness": {
                            "baseColorTexture": {"index": 0},
                            "metallicRoughnessTexture": {"index": 1},
                        }
                    }
                ],
                "textures": [{"source": 0}, {"source": 1}],
                "images": [
                    {"mimeType": "image/png", "uri": "external-base.png"},
                    {"mimeType": "image/png", "uri": "external-mr.png"},
                ],
            }
        )
        with self.assertRaisesRegex(ValueError, "embedded base-color"):
            validate_glb_quality(self._write(data), "pbr_textured")

    def test_generation_result_exposes_verified_artifact_metadata(self) -> None:
        artifact = {
            "path": "results/test.glb",
            "bytes": 123,
            "sha256": "a" * 64,
            "mime": "model/gltf-binary",
            "glb_version": 2,
        }
        result = generation_result(
            "test",
            {"model": "test", "artifact": "results/test.glb", "glb_bytes": 123, "source_faces": 9},
            artifact,
        )
        self.assertEqual(result["artifact"], artifact)
        self.assertEqual(result["metrics"], {"source_faces": 9})


if __name__ == "__main__":
    unittest.main()
