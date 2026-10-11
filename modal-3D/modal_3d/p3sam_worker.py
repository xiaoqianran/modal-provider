"""Stable Modal deployment entrypoint; implementation in workers.p3sam."""
from .workers.p3sam import *
from .workers.p3sam import Model, app  # noqa: F401
