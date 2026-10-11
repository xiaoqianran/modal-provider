from collections.abc import Mapping
from dataclasses import dataclass

CONTRACT = "modal-example.echo.v1"


@dataclass(frozen=True, slots=True)
class EchoRequest:
    text: str


def normalize_request(request: Mapping[str, object]) -> EchoRequest:
    if not isinstance(request, Mapping) or set(request) != {"text"}:
        raise ValueError("expected only text")
    text = request["text"]
    if not isinstance(text, str) or not 1 <= len(text.strip()) <= 1000:
        raise ValueError("text must contain 1..1000 characters")
    return EchoRequest(text=text.strip())


def validate_request(request: Mapping[str, object]) -> None:
    normalize_request(request)
