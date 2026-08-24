"""Rules shared by every GPU worker.

- one model family per image/volume
- weights prepared without a GPU
- exactly one GPU container per model
- one input at a time per container; overflow queues in Modal
- load once in @modal.enter, infer in @modal.method
- declare one CAPABILITY with worker_capability(...)
- expose Model.warmup() without synthetic input
- finish with: generate, warmup, register = register_worker_entrypoint(...)
- deploy through scripts/deploy-worker.ps1 so registration follows deployment
"""

GPU = "L40S"
MAX_CONTAINERS = 1
