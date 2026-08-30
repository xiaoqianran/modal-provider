from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path, PurePosixPath
from unittest.mock import patch

from modal_3d import rembg_worker


class RemBgWorkerContractTests(unittest.TestCase):
    def test_runtime_paths_are_posix_safe_for_windows_deploy(self) -> None:
        self.assertIsInstance(rembg_worker.WEIGHT_ROOT, PurePosixPath)
        self.assertIsInstance(rembg_worker.MODEL_PATH, PurePosixPath)
        self.assertIsInstance(rembg_worker.WEIGHT_MANIFEST, PurePosixPath)
        self.assertIsInstance(rembg_worker.ARTIFACT_ROOT, PurePosixPath)
        self.assertEqual(str(rembg_worker.WEIGHT_ROOT), "/weights/rembg")
        self.assertEqual(str(rembg_worker.ARTIFACT_ROOT), "/artifacts")

    def test_weight_manifest_and_file_are_verified(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            data = b"pinned-birefnet-weight"
            model = Path(root) / "models" / "birefnet-general-lite" / "birefnet-general-lite.onnx"
            model.parent.mkdir(parents=True)
            model.write_bytes(data)
            digest = hashlib.sha256(data).hexdigest()
            manifest = Path(root) / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "model": "birefnet-general-lite",
                        "path": str(model),
                        "bytes": len(data),
                        "sha256": digest,
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(rembg_worker, "WEIGHT_MANIFEST", manifest),
                patch.object(rembg_worker, "MODEL_PATH", model),
                patch.object(rembg_worker, "MODEL_BYTES", len(data)),
                patch.object(rembg_worker, "MODEL_SHA256", digest),
            ):
                result = rembg_worker._verify_weight_manifest()
            self.assertEqual(result["sha256"], digest)

    def test_tampered_weight_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            expected = b"expected"
            model = Path(root) / "model.onnx"
            model.write_bytes(b"tampered")
            digest = hashlib.sha256(expected).hexdigest()
            manifest = Path(root) / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "model": "birefnet-general-lite",
                        "path": str(model),
                        "bytes": len(b"tampered"),
                        "sha256": digest,
                    }
                ),
                encoding="utf-8",
            )
            with (
                patch.object(rembg_worker, "WEIGHT_MANIFEST", manifest),
                patch.object(rembg_worker, "MODEL_PATH", model),
                patch.object(rembg_worker, "MODEL_BYTES", len(b"tampered")),
                patch.object(rembg_worker, "MODEL_SHA256", digest),
                self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"),
            ):
                rembg_worker._verify_weight_manifest()

    def test_app_is_gpu_worker_only(self) -> None:
        source = Path(rembg_worker.__file__).read_text(encoding="utf-8")
        self.assertIn('gpu="T4"', source)
        self.assertIn("max_containers=1", source)
        self.assertIn("def process(self, data: bytes)", source)
        self.assertIn("def prepare(self, source_path: str)", source)
        self.assertIn("rel.parts[2] != source_sha256[:2]", source)
        self.assertIn("def sync_weights()", source)
        self.assertNotIn("@modal.asgi_app", source)
        self.assertNotIn("def condition(", source)
        self.assertNotIn("@modal.asgi_app", source)
        self.assertNotIn("source-inputs", source)
        self.assertNotIn("@modal.concurrent", source)


if __name__ == "__main__":
    unittest.main()
