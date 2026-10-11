"""Stable metadata-only entrypoint for WorldGen stage discovery."""
from .stages import Stage, list_stages, validate_stage_modules

__all__ = ["Stage", "list_stages", "validate_stage_modules"]
