from __future__ import annotations

CONTRACT = "modal-3d.capabilities.v3"
OPERATION = "modal-3d.asset.image_to_3d.v1"
CAPABILITY_KIND = "asset3d.generate"
OUTPUT_ROLE = "primary-glb"
OUTPUT_MIME = "model/gltf-binary"
ARTIFACTS_VOLUME = "modal-3d-artifacts"
JOB_TRANSPORT = "modal.FunctionCall"

# The client prepares the final canonical RGBA locally and uploads it here.
# Modal never preprocesses: there is no source-inputs/ conditioning path.
CLIENT_INPUT_PREFIX = "client-inputs/"
CANONICAL_SIZE = 1024

SOURCE_ROLE = "source_image"
SOURCE_MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp")
SOURCE_MAX_BYTES = 20 * 1024 * 1024
