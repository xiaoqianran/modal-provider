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
    """Opt-in relaxation of the origin boundary.

    The Connector normally pins every request to the Origin that was paired,
    which is what stops an arbitrary site from driving a local session that
    owns generation jobs and artifact bytes. Setting `MODAL_GEN_ALLOW_ANY_ORIGIN`
    turns CORS into `*` and stops rejecting cross-origin requests.

    Only enable it on a trusted network.
    """
    import os

    value = os.environ.get(_ANY_ORIGIN_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "on", "*"}
