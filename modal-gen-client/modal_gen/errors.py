from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ConnectorError(RuntimeError):
    code: str
    message: str
    status: int = 400

    def __str__(self) -> str:
        return self.message

    def payload(self) -> dict[str, object]:
        return {"code": self.code, "message": self.message}


class ProviderError(ConnectorError):
    pass
