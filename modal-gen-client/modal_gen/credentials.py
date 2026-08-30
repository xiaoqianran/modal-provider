from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

_DEFAULT_PATH = Path(__file__).resolve().parents[1] / ".secrets" / "modal.json"


@dataclass(frozen=True, slots=True)
class ModalCredentials:
    token_id: str
    token_secret: str


class CredentialStore:
    """Persist local Modal credentials outside version control."""

    def __init__(self, path: Path | None = None) -> None:
        configured = os.environ.get("MODAL_GEN_CREDENTIALS_FILE", "").strip()
        self.path = path or (Path(configured).expanduser() if configured else _DEFAULT_PATH)

    def load(self) -> ModalCredentials | None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None
        if not isinstance(payload, dict):
            return None
        token_id = payload.get("tokenId")
        token_secret = payload.get("tokenSecret")
        if not isinstance(token_id, str) or not isinstance(token_secret, str):
            return None
        token_id = token_id.strip()
        token_secret = token_secret.strip()
        if not token_id or not token_secret:
            return None
        return ModalCredentials(token_id=token_id, token_secret=token_secret)

    def save(self, token_id: str, token_secret: str) -> None:
        token_id = token_id.strip()
        token_secret = token_secret.strip()
        if not token_id or not token_secret:
            raise ValueError("Modal credentials cannot be empty")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=".modal-", suffix=".tmp", dir=self.path.parent, text=True
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(
                    {"tokenId": token_id, "tokenSecret": token_secret},
                    handle,
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                pass
            os.replace(temp_path, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
