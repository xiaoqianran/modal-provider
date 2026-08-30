import sys
from pathlib import Path
from time import perf_counter

import modal

from ..constants import ARTIFACT_VOLUME, MODELS_VOLUME
from ..models import model_spec
from .common import generate_many, generate_one

MODEL_ID = "hidream-o1-image"
SPEC = model_spec(MODEL_ID)
APP_NAME = SPEC.worker_app
MODEL_ROOT = Path("/models")
ARTIFACT_ROOT = Path("/artifacts")
HIDREAM_SOURCE = "/opt/hidream-o1"
HIDREAM_SOURCE_REVISION = "2c2d29ff729e48f33e41f49edfdbd81d5ac103b4"
FLASH_PATCH = (
    'sed -i "s/\\"use_flash_attn\\": True/'
    '\\"use_flash_attn\\": False/" '
    f"{HIDREAM_SOURCE}/models/pipeline.py"
)

app = modal.App(APP_NAME)
models = modal.Volume.from_name(MODELS_VOLUME, create_if_missing=True)
artifacts = modal.Volume.from_name(ARTIFACT_VOLUME, create_if_missing=True)
image = (
    modal.Image.debian_slim(python_version="3.12")
    .apt_install("git")
    .uv_pip_install(
        "accelerate>=1.2,<2",
        "diffusers>=0.36,<1",
        "einops>=0.8,<1",
        "numpy>=2,<3",
        "pillow>=11,<13",
        "scipy>=1.15,<2",
        "torch>=2.10,<3",
        "torchvision>=0.25,<1",
        "transformers==4.57.1",
    )
    .run_commands(
        f"git clone https://github.com/HiDream-ai/HiDream-O1-Image.git {HIDREAM_SOURCE}",
        f"git -C {HIDREAM_SOURCE} checkout {HIDREAM_SOURCE_REVISION}",
        FLASH_PATCH,
    )
    .env({"PYTHONPATH": HIDREAM_SOURCE})
    .add_local_python_source("modal_2d")
)


def _load(model_id: str, root: Path):
    import torch
    from transformers import AutoProcessor

    spec = model_spec(model_id)
    if spec.runtime != "hidream-o1":
        raise ValueError(f"{model_id} is not a HiDream-O1 model")
    if HIDREAM_SOURCE not in sys.path:
        sys.path.insert(0, HIDREAM_SOURCE)
    from inference import add_special_tokens, get_tokenizer
    from models.pipeline import generate_image
    from models.qwen3_vl_transformers import Qwen3VLForConditionalGeneration

    path = str(root / model_id)
    processor = AutoProcessor.from_pretrained(path, local_files_only=True)
    model = Qwen3VLForConditionalGeneration.from_pretrained(
        path,
        torch_dtype=torch.bfloat16,
        device_map="cuda",
        local_files_only=True,
    ).eval()
    add_special_tokens(get_tokenizer(processor))
    return model, processor, generate_image


def _infer(runtime, request: dict[str, object]):
    model, processor, generate_image = runtime
    image = generate_image(
        model=model,
        processor=processor,
        prompt=str(request["prompt"]),
        ref_image_paths=[],
        height=int(request["height"]),
        width=int(request["width"]),
        num_inference_steps=int(request["steps"]),
        guidance_scale=float(request["guidance"]),
        shift=3.0,
        timesteps_list=None,
        scheduler_name="default",
        seed=int(request["seed"]),
    )
    expected = (int(request["width"]), int(request["height"]))
    if image.size != expected:
        from PIL import Image

        image = image.resize(expected, Image.Resampling.LANCZOS)
    return image


@app.cls(
    image=image,
    gpu=SPEC.gpu,
    timeout=30 * 60,
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
