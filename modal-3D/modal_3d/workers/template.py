"""Rules shared by every GPU worker.

- one model family per image/volume
- weights prepared without a GPU
- exactly one GPU container per model
- one input at a time per container; overflow queues in Modal
- load once in @modal.enter, infer in @modal.method
"""

GPU = "L40S"
MAX_CONTAINERS = 1
