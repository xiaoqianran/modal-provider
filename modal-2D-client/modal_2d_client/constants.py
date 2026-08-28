APP_NAME = "modal-2d"
CONTRACT = "modal-2d.generation.v1"
OPERATION = "modal-2d.image.text_to_image.v1"
# 生成热路径直接打到 GPU Worker，中间没有 CPU 中转 Function。
WORKER_CLASS = "SanaSprintWorker"
GENERATE_METHOD = "generate"
BATCH_GENERATE_METHOD = "generate_batch"
MAX_BATCH_SIZE = 8
CAPABILITIES_FUNCTION = "capabilities"
ARTIFACT_FUNCTION = "read_artifact"
ARTIFACT_VOLUME = "modal-2d-artifacts"
JOB_TRANSPORT = "modal-function-call"
ARTIFACT_ROLE = "primary-image"
ARTIFACT_MIME = "image/png"
SUPPORTED_MODELS = ("sana-sprint-0.6b", "sana-sprint-1.6b")
DEFAULT_MODEL = "sana-sprint-1.6b"
MAX_PROMPT_CHARS = 4000
MAX_SEED = 2**32 - 1
