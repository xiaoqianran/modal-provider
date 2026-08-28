from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from modal_3d.common import ARTIFACT_ROOT, generation_result, validate_glb


def glb_bytes(*, version: int = 2, declared_delta: int = 0, payload: bytes = b"payload") -> bytes:
    size = 12 + len(payload)
    return b"glTF" + version.to_bytes(4, "little") + (size + declared_delta).to_bytes(4, "little") + payload


class ArtifactContractTests(unittest.TestCase):
    def test_serialized_adapter_root_is_platform_neutral(self) -> None:
        self.assertIsInstance(ARTIFACT_ROOT, str)
        self.assertEqual(ARTIFACT_ROOT, "/artifacts")

    def _write(self, data: bytes) -> Path:
        temp = tempfile.NamedTemporaryFile(suffix=".glb", delete=False)
        temp.write(data)
        temp.close()
        self.addCleanup(Path(temp.name).unlink, missing_ok=True)
        return Path(temp.name)

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
