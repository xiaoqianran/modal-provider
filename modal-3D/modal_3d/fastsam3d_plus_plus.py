"""Stable Modal deployment module; implementation in workers.fastsam3d."""
from .workers.fastsam3d import *
from .workers.fastsam3d import (  # noqa: F401
    Model,
    _asset_policy,
    app,
)

