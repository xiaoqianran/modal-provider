from __future__ import annotations

GATEWAY_APP = "modal-3d-gateway"
GATEWAY_SUBMIT = "submit"
CAPABILITIES_FUNCTION = "capabilities"
ARTIFACTS_VOLUME = "modal-3d-artifacts"
CONTRACT = "modal-3d.capabilities.v2"
OPERATION = "modal-3d.asset.image_to_3d.v1"
CAPABILITY_KIND = "asset3d.generate"
OUTPUT_ROLE = "primary-glb"
OUTPUT_MIME = "model/gltf-binary"
SOURCE_ROLE = "source_image"
SOURCE_MEDIA_TYPES = ("image/png", "image/jpeg", "image/webp")
SOURCE_MAX_BYTES = 20 * 1024 * 1024
SOURCE_PATH_PREFIX = "source-inputs/"
JOB_TRANSPORT = "modal.FunctionCall"
