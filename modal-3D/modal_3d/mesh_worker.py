"""Stable Modal deployment entrypoint for the mesh CPU worker.

The implementation lives in workers.mesh; retain this module because published
DeploymentManifest entries use ``modal_3d.mesh_worker``.
"""
from .workers.mesh import Model, app, artifacts, image

__all__ = ["Model", "app", "artifacts", "image"]
