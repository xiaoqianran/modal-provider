from __future__ import annotations

import os
import secrets


def default_session_token() -> str | None:
    """Return the configured local session token, or None when auth is off.

    Mirrors the sidecar's original opt-in behaviour: requests are only guarded
    when ``MODAL_3D_CLIENT_TOKEN`` is explicitly set. When unset, every caller
    (including the bundled web UI) may use the API without a session header.
    """
    value = os.environ.get("MODAL_3D_CLIENT_TOKEN", "").strip()
    return value or None


def session_token_matches(provided: str, expected: str) -> bool:
    return secrets.compare_digest(provided.encode(), expected.encode())


def session_header() -> dict[str, str]:
    token = default_session_token()
    if not token:
        return {}
    return {"X-Modal-3D-Session": token}
