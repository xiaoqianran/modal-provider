APP_NAME = "modal-2d"
CONTRACT = "modal-2d.generation.v2"
OPERATION = "modal-2d.image.text_to_image.v1"
MAX_BATCH_SIZE = 8
CAPABILITIES_FUNCTION = "capabilities"
ARTIFACT_FUNCTION = "read_artifact"
ARTIFACT_VOLUME = "modal-2d-artifacts"
JOB_TRANSPORT = "modal.FunctionCall"
ARTIFACT_ROLE = "primary-image"
ARTIFACT_MIME = "image/png"
DEFAULT_MODEL = "sana-sprint-1.6b"
MAX_PROMPT_CHARS = 4000
MAX_SEED = 2**32 - 1
WORKERS: dict[str, tuple[str, str, str, str]] = {
    "sana-sprint-0.6b": ("modal-2d-sana-sprint", "Model", "generate", "generate_batch"),
    "sana-sprint-1.6b": ("modal-2d-sana-sprint", "Model", "generate", "generate_batch"),
    "qwen-image-2512": ("modal-2d-qwen-image-2512", "Model", "generate", "generate_batch"),
    "z-image-turbo": ("modal-2d-z-image-turbo", "Model", "generate", "generate_batch"),
    "hidream-o1-image": ("modal-2d-hidream-o1", "Model", "generate", "generate_batch"),
}
SUPPORTED_MODELS = tuple(WORKERS)
