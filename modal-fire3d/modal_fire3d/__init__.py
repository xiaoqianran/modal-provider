"""FIRE3D integration. Importing this package never constructs a Modal image."""

__all__ = ["Fire3DBackend"]


def __getattr__(name):
    # The deployed app needs only this package. Shared local service contracts
    # must not be imported while Modal hydrates the GPU/CPU functions.
    if name == "Fire3DBackend":
        from .backend import Fire3DBackend

        return Fire3DBackend
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
