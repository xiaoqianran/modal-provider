import re
from dataclasses import dataclass
from hashlib import sha256

ROLES = {"primary-text": "text/plain"}


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    role: str
    media_type: str
    sha256: str
    size_bytes: int

    def __post_init__(self):
        if ROLES.get(self.role) != self.media_type:
            raise ValueError("invalid artifact role/MIME")
        if not isinstance(self.sha256, str) or not re.fullmatch(
            r"[0-9a-f]{64}", self.sha256
        ):
            raise ValueError("invalid SHA-256")
        if type(self.size_bytes) is not int or self.size_bytes < 0:
            raise ValueError("invalid artifact size")


def describe_artifact(content: bytes) -> ArtifactSpec:
    return ArtifactSpec(
        "primary-text", "text/plain", sha256(content).hexdigest(), len(content)
    )


def validate_artifact(spec: ArtifactSpec, content: bytes) -> None:
    if len(content) != spec.size_bytes or sha256(content).hexdigest() != spec.sha256:
        raise ValueError("artifact integrity mismatch")
