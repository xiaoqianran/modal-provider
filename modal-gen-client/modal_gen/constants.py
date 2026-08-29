CONNECTOR_ID = "unified-connector"
CONNECTOR_VERSION = "0.1.0"
CONTRACT_VERSION = "1"
CLIENT_IDENTITY = "agentscape"
SESSION_PATH = "/connector/v1/session"
SESSION_SCOPES = (
    "capabilities.read",
    "jobs.submit",
    "jobs.read",
    "jobs.cancel",
    "artifacts.read",
)

MODAL_2D_PROVIDER = "modal-2d"
MODAL_2D_OPERATION = "modal-2d.image.text_to_image.v1"
MODAL_2D_OUTPUT_ROLE = "primary-image"

MODAL_3D_PROVIDER = "modal-3d"
MODAL_3D_OPERATION = "modal-3d.asset.image_to_3d.v1"
MODAL_3D_SOURCE_ROLE = "primary-image"
MODAL_3D_OUTPUT_ROLE = "primary-glb"

_ANY_ORIGIN_ENV = "MODAL_GEN_ALLOW_ANY_ORIGIN"


def allow_any_origin() -> bool:
    """Whether browser requests may come from any Origin.

    Defaults to enabled for container/CNB deployments. Set
    `MODAL_GEN_ALLOW_ANY_ORIGIN=0` to restore strict paired-Origin enforcement.
    Authentication remains required in either mode.
    """
    import os

    value = os.environ.get(_ANY_ORIGIN_ENV)
    if value is None:
        return True
    return value.strip().lower() in {"1", "true", "yes", "on", "*"}
