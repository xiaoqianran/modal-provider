"""Explicit local development auth or verified Cloudflare Access user identity."""

from __future__ import annotations

import hashlib
import hmac
import os

import jwt
from fastapi import Request

from ..errors import ConnectorError


class StudioAuth:
    def __init__(self):
        self.mode = os.getenv("STUDIO_AUTH_MODE", "access")
        self.token = os.getenv("STUDIO_DEV_TOKEN", "")
        self.issuer = os.getenv("STUDIO_ACCESS_ISSUER", "").rstrip("/")
        self.audience = os.getenv("STUDIO_ACCESS_AUD", "")
        self.edge_secret = os.getenv("STUDIO_EDGE_SECRET", "")
        self.origins = set(filter(None, os.getenv("STUDIO_ALLOWED_ORIGINS", "").split(",")))
        if self.mode == "development":
            if len(self.token) < 24:
                raise ValueError("STUDIO_DEV_TOKEN must contain at least 24 characters")
            self.keys = None
        elif self.mode == "access":
            if not self.issuer.startswith("https://") or not self.audience:
                raise ValueError("Configure STUDIO_ACCESS_ISSUER and STUDIO_ACCESS_AUD")
            if len(self.edge_secret) < 32 or not self.origins:
                raise ValueError("Configure STUDIO_EDGE_SECRET and STUDIO_ALLOWED_ORIGINS")
            self.keys = jwt.PyJWKClient(f"{self.issuer}/cdn-cgi/access/certs")
        else:
            raise ValueError("STUDIO_AUTH_MODE must be access or development")

    def owner(self, request: Request) -> str:
        # API is same-origin. Reject cross-site browser mutations, including cookie CSRF.
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if request.headers.get("sec-fetch-site") == "cross-site":
                raise ConnectorError("STUDIO_ORIGIN", "Cross-site request rejected", 403)
            if origin and origin not in self.origins:
                raise ConnectorError("STUDIO_ORIGIN", "Origin is not allowed", 403)
        if self.mode == "development":
            if not hmac.compare_digest(
                request.headers.get("authorization", ""), f"Bearer {self.token}"
            ):
                raise ConnectorError("STUDIO_AUTH", "Studio authentication required", 401)
            return "studio-local-user"
        if not hmac.compare_digest(
            request.headers.get("x-studio-edge-secret", ""), self.edge_secret
        ):
            raise ConnectorError("STUDIO_AUTH", "Untrusted gateway", 401)
        try:
            token = request.headers.get("cf-access-jwt-assertion", "")
            key = self.keys.get_signing_key_from_jwt(token)
            claims = jwt.decode(
                token,
                key.key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
                options={"require": ["exp", "iat", "sub", "iss", "aud"]},
            )
            subject = claims["sub"]
            if not isinstance(subject, str) or not subject or not claims.get("email"):
                raise ValueError("Interactive user identity required")
        except (jwt.PyJWTError, ValueError) as exc:
            raise ConnectorError("STUDIO_AUTH", "Invalid Access identity", 401) from exc
        return "user_" + hashlib.sha256(f"{self.issuer}:{subject}".encode()).hexdigest()
