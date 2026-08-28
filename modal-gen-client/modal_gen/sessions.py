from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from .capabilities import CapabilityRegistry, iso
from .constants import (
    CLIENT_IDENTITY,
    CONTRACT_VERSION,
    SESSION_PATH,
    SESSION_SCOPES,
    allow_any_origin,
)
from .errors import ConnectorError
from .storage import Store


class SessionService:
    def __init__(self, store: Store, capabilities: CapabilityRegistry) -> None:
        self.store = store
        self.capabilities = capabilities

    def pair(
        self,
        payload: dict[str, object],
        *,
        request_origin: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, object]:
        current = now or datetime.now(UTC)
        client_identity = str(payload.get("clientIdentity") or "").strip()
        contract_version = str(payload.get("contractVersion") or "").strip()
        origin = normalize_origin(payload.get("origin"))
        scopes = normalize_scopes(payload.get("scopes"))
        if client_identity != CLIENT_IDENTITY:
            raise ConnectorError(
                "CONNECTOR_CLIENT_MISMATCH", "Connector client identity 不兼容", 409
            )
        if contract_version != CONTRACT_VERSION:
            raise ConnectorError(
                "CONNECTOR_CONTRACT_MISMATCH", "Connector contract version 不兼容", 409
            )
        if not allow_any_origin() and request_origin and normalize_origin(request_origin) != origin:
            raise ConnectorError(
                "CONNECTOR_ORIGIN_MISMATCH", "HTTP Origin 与 pairing origin 不一致", 403
            )

        pairing_id = str(payload.get("pairingId") or "").strip()
        if not pairing_id:
            pairing_id = f"pair_{uuid.uuid4().hex}"
            self.store.create_pairing(
                {
                    "id": pairing_id,
                    "client_identity": client_identity,
                    "origin": origin,
                    "scopes": scopes,
                    "status": "pending",
                    "created_at": iso(current),
                    "expires_at": iso(current + timedelta(minutes=5)),
                }
            )
            return self._approval_required(pairing_id)

        pairing = self.store.get_pairing(pairing_id)
        if not pairing:
            raise ConnectorError("CONNECTOR_PAIRING_INVALID", "Pairing 不存在", 404)
        if _expired(str(pairing["expires_at"]), current):
            raise ConnectorError("CONNECTOR_PAIRING_EXPIRED", "Pairing 已过期", 410)
        if (
            pairing["client_identity"] != client_identity
            or pairing["origin"] != origin
            or pairing["scopes"] != scopes
        ):
            raise ConnectorError("CONNECTOR_PAIRING_MISMATCH", "Pairing 请求身份发生变化", 409)
        if pairing["status"] == "pending":
            return self._approval_required(pairing_id)
        if pairing["status"] != "approved":
            raise ConnectorError("CONNECTOR_PAIRING_INVALID", "Pairing 已失效", 409)

        snapshot = self.capabilities.snapshot(now=current)
        token = secrets.token_urlsafe(32)
        token_id = f"session_{uuid.uuid4().hex}"
        expires = current + timedelta(minutes=15)
        self.store.create_session(
            {
                "token_id": token_id,
                "token_hash": hashlib.sha256(token.encode()).hexdigest(),
                "client_identity": client_identity,
                "origin": origin,
                "scopes": scopes,
                "issued_at": iso(current),
                "expires_at": iso(expires),
                "capability_revision": snapshot["revision"],
                "capability_hash": snapshot["hash"],
            }
        )
        self.store.set_pairing_status(pairing_id, "consumed")
        return {
            "status": "paired",
            "token": token,
            "session": {
                "connector": self.capabilities.connector,
                "contractVersion": CONTRACT_VERSION,
                "clientIdentity": client_identity,
                "tokenId": token_id,
                "scopes": scopes,
                "issuedAt": iso(current),
                "expiresAt": iso(expires),
                "allowedOrigins": [origin],
                "capabilityRevision": snapshot["revision"],
                "capabilityHash": snapshot["hash"],
                "revokeEndpoint": SESSION_PATH,
            },
        }

    def approve(self, pairing_id: str, *, now: datetime | None = None) -> dict[str, object]:
        pairing = self.store.get_pairing(pairing_id)
        if not pairing:
            raise ConnectorError("CONNECTOR_PAIRING_INVALID", "Pairing 不存在", 404)
        if _expired(str(pairing["expires_at"]), now or datetime.now(UTC)):
            raise ConnectorError("CONNECTOR_PAIRING_EXPIRED", "Pairing 已过期", 410)
        if pairing["status"] != "pending":
            raise ConnectorError("CONNECTOR_PAIRING_INVALID", "Pairing 当前不可批准", 409)
        self.store.set_pairing_status(pairing_id, "approved")
        return {**pairing, "status": "approved"}

    def authorize(
        self,
        authorization: str | None,
        scope: str | None,
        *,
        request_origin: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, object]:
        value = str(authorization or "")
        if not value.startswith("Bearer "):
            raise ConnectorError("CONNECTION_REQUIRED", "Connector session required", 401)
        token = value[7:].strip()
        if not token:
            raise ConnectorError("CONNECTION_REQUIRED", "Connector session required", 401)
        session = self.store.get_session_by_hash(hashlib.sha256(token.encode()).hexdigest())
        if not session or session["revoked"]:
            raise ConnectorError("CONNECTION_REQUIRED", "Connector session 无效", 401)
        if _expired(str(session["expires_at"]), now or datetime.now(UTC)):
            raise ConnectorError("CONNECTION_REQUIRED", "Connector session 已过期", 401)
        if (
            not allow_any_origin()
            and request_origin
            and normalize_origin(request_origin) != session["origin"]
        ):
            raise ConnectorError(
                "CONNECTOR_ORIGIN_MISMATCH", "Connector session origin 不匹配", 403
            )
        if scope is not None and scope not in session["scopes"]:
            raise ConnectorError(
                "CONNECTOR_SCOPE_REQUIRED", f"Connector session 缺少 scope: {scope}", 403
            )
        return session

    def revoke(
        self,
        authorization: str | None,
        *,
        request_origin: str | None = None,
    ) -> dict[str, object]:
        session = self.authorize(authorization, None, request_origin=request_origin)
        self.store.revoke_session(str(session["token_id"]))
        return {"status": "revoked"}

    def _approval_required(self, pairing_id: str) -> dict[str, object]:
        return {
            "status": "approval_required",
            "pairingId": pairing_id,
            "contractVersion": CONTRACT_VERSION,
            "connector": self.capabilities.connector,
        }


def normalize_origin(value: object) -> str:
    parsed = urlsplit(str(value or "").strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ConnectorError(
            "CONNECTOR_ORIGIN_REQUIRED", "Pairing origin 必须是 http/https origin", 422
        )
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ConnectorError("CONNECTOR_ORIGIN_REQUIRED", "Pairing origin 必须是裸 origin", 422)
    default_port = (parsed.scheme == "http" and parsed.port == 80) or (
        parsed.scheme == "https" and parsed.port == 443
    )
    host = parsed.hostname
    if ":" in host:
        host = f"[{host}]"
    port = "" if parsed.port is None or default_port else f":{parsed.port}"
    return f"{parsed.scheme}://{host}{port}"


def normalize_scopes(value: object) -> list[str]:
    if not isinstance(value, list):
        raise ConnectorError("CONNECTOR_SCOPE_INVALID", "Pairing scopes 必须是数组", 422)
    scopes = list(
        dict.fromkeys(str(item or "").strip() for item in value if str(item or "").strip())
    )
    if not scopes:
        raise ConnectorError("CONNECTOR_SCOPE_INVALID", "Pairing scopes 不能为空", 422)
    invalid = [scope for scope in scopes if scope not in SESSION_SCOPES]
    if invalid:
        raise ConnectorError("CONNECTOR_SCOPE_INVALID", "Pairing 请求了不允许的 scope", 422)
    return scopes


def _expired(value: str, now: datetime) -> bool:
    return datetime.fromisoformat(value.replace("Z", "+00:00")) <= now.astimezone(UTC)
