"""Reference shape for every model worker.

Each concrete worker gets its own Image and Volume because CUDA/native dependencies differ.
Weights are populated by a CPU-only download function, then read locally by the GPU worker.
"""

import modal


def worker_app(name: str, image: modal.Image, volume: modal.Volume, load_model, run_model):
    app = modal.App(name)

    @app.function(
        image=image,
        gpu="L40S",
        volumes={"/models": volume},
        max_containers=1,
        scaledown_window=60,
        timeout=1800,
    )
    def generate(input_path: str, options: dict):
        # Concrete modules replace this closure with a modal.Cls so model loading happens once
        # per warm container via @modal.enter(). This template only fixes the public contract.
        model = load_model("/models")
        return run_model(model, input_path, options)

    return app, generate
