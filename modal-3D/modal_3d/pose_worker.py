"""Stable Modal deployment entrypoint for pose."""
from .workers.pose import *
from .workers.pose import Model, app  # noqa: F401

