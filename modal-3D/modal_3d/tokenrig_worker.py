"""Stable Modal deployment entrypoint for tokenrig."""
from .workers.tokenrig import *
from .workers.tokenrig import Model, app  # noqa: F401

