
from pathlib import Path
from time import perf_counter

import modal

from ..constants import ARTIFACT_VOLUME, MODELS_VOLUME
from ..models import model_spec
from .common import generate_many, generate_one

APP_NAME = "modal-2d-z-image-turbo"
MODEL_ID = "z-image-turbo"
MODEL_ROOT = Path("/models")
ARTIFACT_ROOT = Path("/artifacts")

app = modal.App(APP_NAME)
models = modal.Volume.from_name(MODELS_VOLUME, create_if_missing=True)
artifacts = modal.Volume.from_name(ARTIFACT_VOLUME, create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .uv_pip_install(
        "accelerate>=1.2,<2",
        "diffusers>=0.36,<1",
        "pillow>=11,<13",
        "safetensors>=0.5,<1",
        "sentencepiece>=0.2,<1",
        "torch>=2.7,<3",
        "torchvision>=0.22,<1",
        "transformers>=4.51,<5",
    )
    .add_local_python_source("modal_2d")
)


def _load(model_id: str, root: Path):
    import torch
    from diffusers import ZImagePipeline

    spec = model_spec(model_id)
    if spec.runtime != "z-image":
        raise ValueError(f"{model_id} is not a Z-Image model")
    pipe = ZImagePipeline.from_pretrained(
        str(root / model_id),
        torch_dtype=torch.bfloat16,
        low_cpu_mem_usage=False,
        local_files_only=True,
    )
    pipe.to("cuda")
    return pipe


def _infer(pipe, request: dict[str, object]):
    import torch

    generator = torch.Generator(device="cuda").manual_seed(int(request["seed"]))
    return pipe(
        prompt=str(request["prompt"]),
        width=int(request["width"]),
        height=int(request["height"]),
        num_inference_steps=int(request["steps"]),
        guidance_scale=float(request["guidance"]),
        generator=generator,
    ).images[0]


@app.cls(
    image=image,
    gpu="L40S",
    timeout=20 * 60,
    max_containers=1,
    scaledown_window=300,
    retries=modal.Retries(max_retries=2, backoff_coefficient=2.0),
    volumes={str(MODEL_ROOT): models, str(ARTIFACT_ROOT): artifacts},
)
class Model:
    model_id: str = modal.parameter(default=MODEL_ID)

    @modal.enter()
    def load(self) -> None:
        if self.model_id != MODEL_ID:
            raise ValueError(f"unsupported worker model: {self.model_id}")
        started = perf_counter()
        models.reload()
        self.runtime = _load(self.model_id, MODEL_ROOT)
        self.worker_load_ms = round((perf_counter() - started) * 1000, 3)
        self.batch_calls = 0

    @modal.method()
    def generate(self, payload: dict[str, object]) -> dict[str, object]:
        descriptor = generate_one(
            self.runtime,
            payload,
            model_id=self.model_id,
            infer=_infer,
            artifact_root=ARTIFACT_ROOT,
        )
        artifacts.commit()
        return {"model": self.model_id, "artifact": descriptor}

    @modal.method()
    def generate_batch(self, payload: dict[str, object]) -> dict[str, object]:
        descriptors, timing = generate_many(
            self.runtime,
            payload,
            model_id=self.model_id,
            infer=_infer,
            artifact_root=ARTIFACT_ROOT,
            worker_load_ms=self.worker_load_ms,
            worker_reused=self.batch_calls > 0,
        )
        artifacts.commit()
        self.batch_calls += 1
        return {"model": self.model_id, "artifacts": descriptors, "timing": timing}
