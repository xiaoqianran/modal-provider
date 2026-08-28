"""Rules shared by every GPU worker.

- one model family per image/volume
- weights prepared without a GPU
- exactly one GPU container per model
- one input at a time per container; overflow queues in Modal
- load once in @modal.enter, infer in @modal.method
- declare one CAPABILITY with worker_capability(...), including
  generation_entrypoint={"kind": "class_method", "class_name": "Model",
  "method_name": "generate_job"}
- expose Model.warmup() without synthetic input
- expose Model.generate_job(input_path, options) as the only submission
  entrypoint; it reads /artifacts/client-inputs/, validates the canonical
  PNG, calls the model, validates the GLB, and returns generation_result()
- no CPU adapter function: the client spawns Model.generate_job directly
- register the app/class/method triple in router.WORKERS
- deploy through scripts/deploy-worker.ps1
"""

GPU = "L40S"
MAX_CONTAINERS = 1
