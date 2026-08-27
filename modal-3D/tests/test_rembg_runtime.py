from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from modal_3d import rembg_gateway


class RemBgRuntimeContractTests(unittest.TestCase):
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
                patch.object(rembg_gateway, "WEIGHT_MANIFEST", manifest),
                patch.object(rembg_gateway, "MODEL_PATH", model),
                patch.object(rembg_gateway, "MODEL_BYTES", len(data)),
                patch.object(rembg_gateway, "MODEL_SHA256", digest),
            ):
                result = rembg_gateway._verify_weight_manifest()
            self.assertEqual(result["sha256"], digest)

    def test_tampered_weight_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            data = b"expected"
            model = Path(root) / "model.onnx"
            model.write_bytes(b"tampered")
            digest = hashlib.sha256(data).hexdigest()
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
                patch.object(rembg_gateway, "WEIGHT_MANIFEST", manifest),
                patch.object(rembg_gateway, "MODEL_PATH", model),
                patch.object(rembg_gateway, "MODEL_BYTES", len(b"tampered")),
                patch.object(rembg_gateway, "MODEL_SHA256", digest),
                self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"),
            ):
                rembg_gateway._verify_weight_manifest()

    def test_runtime_image_has_no_weight_download_step(self) -> None:
        source = Path(rembg_gateway.__file__).read_text(encoding="utf-8")
        self.assertNotIn("urlretrieve", source)
        self.assertNotIn(".run_commands(", source)
        self.assertIn('"rembg==2.0.81"', source)
        self.assertIn('"numpy==2.3.5"', source)
        self.assertIn('"scipy==1.16.3"', source)
        self.assertIn('"Pillow==12.1.0"', source)
        self.assertIn('volumes={"/weights": weights}', source)


if __name__ == "__main__":
    unittest.main()
