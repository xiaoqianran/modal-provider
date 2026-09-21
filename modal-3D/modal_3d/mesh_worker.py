"""Independent CPU compute service for mesh, QuadriFlow, xatlas and Cycles baking."""
import modal

from .common import ARTIFACT_VOLUME
from .operation_runner import run_operation_job
from .operations import REVISION

app = modal.App("modal-3d-mesh")
image = (modal.Image.debian_slim(python_version="3.11")
         .apt_install("libgl1", "libegl1", "libxrender1", "libxi6", "libxfixes3", "libxkbcommon0", "libsm6")
         .pip_install("bpy==4.2.0", "numpy==1.26.4", "xatlas==0.0.9", "Pillow==11.3.0")
         .add_local_python_source("modal_3d"))
artifacts = modal.Volume.from_name(ARTIFACT_VOLUME, create_if_missing=True)


@app.cls(image=image, cpu=4, memory=16384, timeout=3600, max_containers=1,
         min_containers=0, scaledown_window=60, volumes={"/artifacts": artifacts})
class Model:
    @modal.method()
    def identity(self):
        return {"revision": REVISION, "operations": "mesh/uv/bake", "resource": "cpu"}

    @modal.method()
    def run_job(self, request: dict, options: dict | None = None):
        return run_operation_job(artifacts, request["operation"], request["inputs"], options)
