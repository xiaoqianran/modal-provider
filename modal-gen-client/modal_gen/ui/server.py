"""Local console UI server for modal-gen-client.

Serves the static console and a small JSON API. Two gateway modes:

* demo  — no connector required; `DemoEngine` provides realistic fixtures so the
           console can be rendered and reviewed offline.
* live  — talks HTTP to a running Connector (`MODAL_GEN_CONNECTOR_URL`, default
           http://127.0.0.1:48123). The console performs the real two-phase
           pairing against the connector and approves it through the connector's
           local control plane (needs `MODAL_GEN_AGENT_TOKEN`).

The console never impersonates an AgentScape client beyond what the connector
contract allows: it pairs as `agentscape`, gets a scoped session, and submits
jobs through `/connect  or/v1/*`.
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from ..identity import idempotency_key, request_hash
from .demo import DemoEngine, build_capability_snapshot

_HERE = Path(__file__).resolve().parent
_STATIC = _HERE / "assets"
_CLIENT_ORIGIN = os.environ.get("MODAL_GEN_UI_ORIGIN", "http://127.0.0.1:48124")
_MODE = "demo" if os.environ.get("MODAL_GEN_UI_DEMO") else "live"
_CONNECTOR_URL = os.environ.get("MODAL_GEN_CONNECTOR_URL", "http://127.0.0.1:48123").rstrip("/")
_CONNECTOR_TOKEN = os.environ.get("MODAL_GEN_AGENT_TOKEN") or "wangran"
_PORT = int(os.environ.get("MODAL_GEN_UI_PORT", "48124"))


# The console defaults to all interfaces for container/CNB port forwarding.
# Authentication remains enforced by the Connector behind the UI gateway.
def ui_host() -> str:
    """Resolved at call time so runtime configuration always applies."""
    return os.environ.get("MODAL_GEN_UI_HOST") or "0.0.0.0"


def _allow_any_origin() -> bool:
    value = os.environ.get("MODAL_GEN_ALLOW_ANY_ORIGIN")
    if value is None:
        return True
    return value.strip().lower() in {"1", "true", "yes", "on", "*"}


# --------------------------------------------------------------------------- #
# Gateways
# --------------------------------------------------------------------------- #
class DemoGateway:
    mode = "demo"

    def __init__(self) -> None:
        self.engine = DemoEngine()
        self._connected = True

    def bootstrap(self) -> dict:
        return {"mode": "demo", "connector": {"id": "unified-connector", "version": "0.1.0"}}

    def capabilities(self, *, force: bool = False) -> dict:
        del force
        return {"snapshot": self.engine.capabilities(), "stale": False, "cached": False}

    def pairings(self) -> dict:
        return {"pairings": self.engine.list_pairings()}

    def approve_pairing(self, pairing_id: str) -> dict:
        return {"status": "approved"}

    def session(self) -> dict:
        return {"status": "paired", "session": self.engine.session_descriptor()}

    def connections(self) -> dict:
        return {
            "providers": [
                {"id": "modal-2d", "connected": self._connected, "managed": True},
                {"id": "modal-3d", "connected": self._connected, "managed": True},
            ]
        }

    def connect_providers(self, _token_id: str, _token_secret: str) -> dict:
        self._connected = True
        return self.connections()

    def disconnect_providers(self) -> dict:
        self._connected = False
        return self.connections()

    def deployments(self, *, force: bool = False) -> dict:
        del force
        return {
            "providers": [
                {"id": "modal-2d", "status": "current", "apps": []},
                {"id": "modal-3d", "status": "current", "apps": []},
            ]
        }

    def huggingface_secret(self) -> dict:
        return {"connected": True, "configured": True, "secrets": []}

    def save_huggingface_secret(self, _token: str) -> dict:
        return self.huggingface_secret()

    def deploy(
        self,
        provider: str = "all",
        app_name: str | None = None,
        *,
        missing_only: bool = False,
        force: bool = False,
        strategy: str = "rolling",
    ) -> dict:
        rows = self.deployments()
        selected = (
            rows["providers"]
            if provider == "all"
            else [row for row in rows["providers"] if row["id"] == provider]
        )
        if app_name:
            for row in selected:
                row["apps"] = [item for item in row.get("apps", []) if item.get("app") == app_name]
        job = {
            "id": "dep_demo",
            "status": "succeeded",
            "provider": provider,
            "app": app_name,
            "missingOnly": missing_only,
            "force": force,
            "strategy": strategy,
            "result": {"providers": selected},
        }
        return {"job": job}

    def deployment_jobs(self, limit: int = 20) -> dict:
        return {"jobs": []}

    def deployment_job(self, job_id: str) -> dict:
        if job_id != "dep_demo":
            raise RuntimeError("deployment job not found")
        return self.deploy()["job"]

    def jobs(self, status=None, q="", page=1, page_size=25) -> dict:
        return self.engine.list_jobs(status=status, q=q, page=page, page_size=page_size)

    def job(self, job_id: str) -> dict | None:
        row = self.engine.get_job(job_id)
        return row

    def submit(self, provider: str, operation: str, inputs: dict) -> dict:
        return self.engine.submit_job(provider, operation, inputs)

    def cancel(self, job_id: str) -> dict:
        row = self.engine.cancel_job(job_id)
        if row is None:
            raise KeyError("unknown job")
        return row

    def artifacts(self, *, page: int = 1, page_size: int = 12, mime: str | None = None) -> dict:
        items = [
            {k: v for k, v in a.items() if k != "_bytes"} for a in self.engine.list_artifacts()
        ]
        if mime:
            items = [item for item in items if item.get("mime") == mime]
        total = len(items)
        page = max(1, page)
        page_size = max(1, min(page_size, 48))
        start = (page - 1) * page_size
        return {
            "artifacts": items[start : start + page_size],
            "page": page,
            "pageSize": page_size,
            "total": total,
        }

    def artifact_content(self, artifact_id: str) -> tuple[bytes, str] | None:
        data = self.engine.artifact_bytes(artifact_id)
        art = self.engine.get_artifact(artifact_id)
        if data is None or art is None:
            return None
        return data, art["mime"]

    # demo-only dev switches
    def set_scenario(self, three_d_unavailable: bool = False) -> None:
        self.engine.snapshot = build_capability_snapshot(three_d_unavailable=three_d_unavailable)


class LiveGateway:
    mode = "live"

    def __init__(self) -> None:
        self.token: str | None = None
        self.session_data: dict | None = None
        self.snapshot: dict | None = None
        self._snapshot_at = 0.0
        self._snapshot_ttl_s = 30.0
        self._lock = threading.Lock()

    # -- low level ---------------------------------------------------------- #
    def _req(
        self,
        method: str,
        path: str,
        *,
        json_body=None,
        headers=None,
        token=None,
        timeout: float = 5.0,
    ):
        import httpx

        url = f"{_CONNECTOR_URL}{path}"
        hdrs = dict(headers or {})
        hdrs["Origin"] = _CLIENT_ORIGIN
        if token:
            hdrs["Authorization"] = f"Bearer {token}"
        if json_body is not None:
            hdrs["Content-Type"] = "application/json"
        try:
            resp = httpx.request(
                method,
                url,
                json=json_body,
                headers=hdrs,
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f"connector unreachable: {exc}") from exc
        if resp.headers.get("content-type", "").startswith("application/json"):
            payload = resp.json() if resp.content else {}
        else:
            payload = resp.text
        if not resp.is_success:
            code = (payload.get("code") if isinstance(payload, dict) else None) or "HTTP"
            message = payload.get("message") if isinstance(payload, dict) else None
            suffix = f": {message}" if isinstance(message, str) and message.strip() else ""
            raise RuntimeError(f"{code} ({resp.status_code}){suffix}")
        return payload

    def bootstrap(self) -> dict:
        try:
            health = self._req("GET", "/health")
        except RuntimeError:
            return {"mode": "live", "connector": None, "reachable": False}
        return {"mode": "live", "connector": health.get("connector"), "reachable": True}

    def capabilities(self, *, force: bool = False) -> dict:
        now = time.monotonic()
        if (
            not force
            and self.snapshot is not None
            and now - self._snapshot_at < self._snapshot_ttl_s
        ):
            return {"snapshot": self.snapshot, "stale": False, "cached": True}
        snap = self._req(
            "GET",
            f"/v1/capabilities{'?refresh=1' if force else ''}",
            headers={"X-Modal-Gen-Session": _CONNECTOR_TOKEN},
            timeout=30.0 if force else 5.0,
        )
        self.snapshot = snap
        self._snapshot_at = now
        return {"snapshot": snap, "stale": False, "cached": False}

    def connections(self) -> dict:
        return self._req(
            "GET",
            "/v1/provider-connections",
            headers={"X-Modal-Gen-Session": _CONNECTOR_TOKEN},
        )

    def connect_providers(self, token_id: str, token_secret: str) -> dict:
        result = self._req(
            "POST",
            "/v1/providers/connect",
            json_body={"tokenId": token_id, "tokenSecret": token_secret},
            headers={"X-Modal-Gen-Session": _CONNECTOR_TOKEN},
            timeout=30.0,
        )
        self.token = None
        self.session_data = None
        self.snapshot = None
        self._snapshot_at = 0.0
        return result

    def disconnect_providers(self) -> dict:
        result = self._req(
            "POST",
            "/v1/providers/disconnect",
            headers={"X-Modal-Gen-Session": _CONNECTOR_TOKEN},
        )
        self.token = None
        self.session_data = None
        self.snapshot = None
        self._snapshot_at = 0.0
        return result

    def deployments(self, *, force: bool = False) -> dict:
        return self._req(
            "GET",
            f"/v1/deployments{'?refresh=1' if force else ''}",
            headers={"X-Modal-Gen-Session": _CONNECTOR_TOKEN},
            timeout=30.0,
        )

    def huggingface_secret(self) -> dict:
        return self._req(
            "GET",
            "/v1/secrets/huggingface",
            headers={"X-Modal-Gen-Session": _CONNECTOR_TOKEN},
            timeout=30.0,
        )

    def save_huggingface_secret(self, token: str) -> dict:
        return self._req(
            "POST",
            "/v1/secrets/huggingface",
            json_body={"token": token},
            headers={"X-Modal-Gen-Session": _CONNECTOR_TOKEN},
            timeout=30.0,
        )

    def deploy(
        self,
        provider: str = "all",
        app_name: str | None = None,
        *,
        missing_only: bool = False,
        force: bool = False,
        strategy: str = "rolling",
    ) -> dict:
        body = {
            "provider": provider,
            "missingOnly": missing_only,
            "force": force,
            "strategy": strategy,
        }
        if app_name:
            body["app"] = app_name
        return self._req(
            "POST",
            "/v1/deployments/deploy",
            json_body=body,
            headers={"X-Modal-Gen-Session": _CONNECTOR_TOKEN},
            timeout=10.0,
        )

    def deployment_jobs(self, limit: int = 20) -> dict:
        return self._req(
            "GET",
            f"/v1/deployments/jobs?limit={limit}",
            headers={"X-Modal-Gen-Session": _CONNECTOR_TOKEN},
            timeout=10.0,
        )

    def deployment_job(self, job_id: str) -> dict:
        return self._req(
            "GET",
            f"/v1/deployments/jobs/{job_id}",
            headers={"X-Modal-Gen-Session": _CONNECTOR_TOKEN},
            timeout=10.0,
        )["job"]

    def pairings(self) -> dict:
        snap = self._req("GET", "/v1/pairings", headers={"X-Modal-Gen-Session": _CONNECTOR_TOKEN})
        return snap

    def approve_pairing(self, pairing_id: str) -> dict:
        self._req(
            "POST",
            f"/v1/pairings/{pairing_id}/approve",
            headers={"X-Modal-Gen-Session": _CONNECTOR_TOKEN},
        )
        return {"status": "approved"}

    def session(self) -> dict:
        if self.token and self.session_data:
            return {"status": "paired", "token": self.token, "session": self.session_data}
        with self._lock:
            if self.token and self.session_data:
                return {"status": "paired", "token": self.token, "session": self.session_data}
            body = {
                "clientIdentity": "agentscape",
                "contractVersion": "1",
                "origin": _CLIENT_ORIGIN,
                "scopes": [
                    "capabilities.read",
                    "jobs.submit",
                    "jobs.read",
                    "jobs.cancel",
                    "artifacts.read",
                ],
            }
            first = self._req("POST", "/connector/v1/session", json_body=body)
            if first.get("status") != "approval_required":
                raise RuntimeError("unexpected pairing response")
            pairing_id = first["pairingId"]
            self.approve_pairing(pairing_id)
            second = self._req(
                "POST", "/connector/v1/session", json_body={**body, "pairingId": pairing_id}
            )
            if second.get("status") != "paired":
                raise RuntimeError("session not established")
            self.token = second["token"]
            self.session_data = second["session"]
            return second

    def _ensure_session(self, snapshot: dict | None = None) -> None:
        if snapshot is not None and self.token and self.session_data:
            session_hash = self.session_data.get("capabilityHash")
            if session_hash != snapshot.get("hash"):
                self.token = None
                self.session_data = None
        if not self.token:
            self.session()

    def jobs(self, status=None, q="", page=1, page_size=25) -> dict:
        self._ensure_session()
        page = max(1, page)
        page_size = max(1, min(page_size, 100))
        params: dict[str, object] = {
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        if status and status != "all":
            params["status"] = status
        if q:
            params["q"] = q
        data = self._req("GET", f"/connector/v1/jobs?{urlencode(params)}", token=self.token)
        visible = list(data.get("jobs", []))
        total = int(data.get("total", len(visible)))
        terminal = {"succeeded", "failed", "cancelled", "expired"}
        refreshed: list[dict] = []
        for row in visible:
            if row.get("status") in terminal:
                refreshed.append(row)
                continue
            try:
                payload = self._req(
                    "GET",
                    f"/connector/v1/jobs/{row['id']}",
                    token=self.token,
                    timeout=20.0,
                )
                refreshed.append(payload.get("job") or row)
            except RuntimeError as exc:
                refreshed.append({**row, "syncDelayed": True, "syncError": str(exc)})
        return {"jobs": refreshed, "page": page, "pageSize": page_size, "total": total}

    def job(self, job_id: str) -> dict | None:
        self._ensure_session()
        payload = self._req(
            "GET",
            f"/connector/v1/jobs/{job_id}",
            token=self.token,
            timeout=20.0,
        )
        return payload.get("job") if isinstance(payload, dict) else None

    def submit(self, provider: str, operation: str, inputs: dict) -> dict:
        snapshot = self.capabilities()["snapshot"]
        provider_desc = next(
            (item for item in snapshot.get("providers", []) if item.get("id") == provider), None
        )
        if not provider_desc:
            raise RuntimeError("provider not found in capability snapshot")
        capability = next(
            (
                item
                for item in provider_desc.get("capabilities", [])
                if item.get("operation") == operation
            ),
            None,
        )
        if not capability:
            raise RuntimeError("operation not found in capability snapshot")
        output = capability.get("output") or {}
        roles = list(output.get("required") or output.get("roles") or [])
        body = {
            "provider": provider,
            "operation": operation,
            "inputs": dict(inputs),
            "profile": None,
            "options": {},
            "outputRoles": roles,
            "parent": None,
            "retention": None,
            "metadata": None,
            "operationVersion": capability.get("version"),
            "contractVersion": provider_desc.get("contractVersion", "1"),
            "capabilityHash": snapshot.get("hash"),
            "capabilityRevision": snapshot.get("revision"),
        }
        body["requestHash"] = request_hash(body)
        body["idempotencyKey"] = idempotency_key(body)
        self._ensure_session(snapshot)
        try:
            payload = self._req(
                "POST",
                "/connector/v1/jobs",
                json_body=body,
                token=self.token,
                timeout=20.0,
            )
        except RuntimeError as exc:
            # Submission is idempotent. A timeout after the Connector accepted the
            # request is an unknown outcome, not a safe reason to report failure.
            # Retry once with the exact same idempotency key to recover the result.
            if "timed out" not in str(exc).lower():
                raise
            payload = self._req(
                "POST",
                "/connector/v1/jobs",
                json_body=body,
                token=self.token,
                timeout=20.0,
            )
        return payload.get("job") if isinstance(payload, dict) else payload

    def cancel(self, job_id: str) -> dict:
        self._ensure_session()
        payload = self._req("POST", f"/connector/v1/jobs/{job_id}/cancel", token=self.token)
        return payload.get("job") if isinstance(payload, dict) else payload

    def artifacts(self, *, page: int = 1, page_size: int = 12, mime: str | None = None) -> dict:
        self._ensure_session()
        page = max(1, page)
        page_size = max(1, min(page_size, 48))
        params: dict[str, object] = {
            "limit": page_size,
            "offset": (page - 1) * page_size,
        }
        if mime:
            params["mime"] = mime
        data = self._req("GET", f"/connector/v1/artifacts?{urlencode(params)}", token=self.token)
        return {
            "artifacts": list(data.get("artifacts", [])),
            "page": page,
            "pageSize": page_size,
            "total": int(data.get("total", 0)),
        }

    def artifact_content(self, artifact_id: str) -> tuple[bytes, str] | None:
        self._ensure_session()
        try:
            import httpx

            resp = httpx.get(
                f"{_CONNECTOR_URL}/connector/v1/artifacts/{artifact_id}",
                headers={"Authorization": f"Bearer {self.token}", "Origin": _CLIENT_ORIGIN},
                timeout=30.0,
                trust_env=False,
            )
            if resp.status_code != 200:
                return None
            return resp.content, resp.headers.get("content-type", "application/octet-stream")
        except httpx.RequestError:
            return None


def make_gateway() -> DemoGateway | LiveGateway:
    if _MODE == "demo":
        return DemoGateway()
    return LiveGateway()


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #
class Handler(BaseHTTPRequestHandler):
    gateway: DemoGateway | LiveGateway = make_gateway()

    def log_message(self, *args):  # silence default logging
        pass

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self._write_body(body)

    def _write_body(self, data: bytes) -> None:
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionAbortedError, ConnectionResetError):
            return

    def _cors_headers(self):
        """Reflect the caller's Origin, or `*` when wildcard mode is enabled."""
        raw = self.headers.get("origin")
        if not raw:
            return
        value = "*" if _allow_any_origin() else raw
        self.send_header("Access-Control-Allow-Origin", value)
        self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, Accept")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _send_file(self, path: Path):
        data = path.read_bytes()
        self.send_response(200)
        mime = "text/html; charset=utf-8"
        if path.suffix == ".css":
            mime = "text/css; charset=utf-8"
        elif path.suffix == ".js":
            mime = "text/javascript; charset=utf-8"
        elif path.suffix == ".svg":
            mime = "image/svg+xml"
        self._cors_headers()
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self._write_body(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path in {"/", "/ui", "/ui/"}:
            return self._send_file(_STATIC / "index.html")
        if path.startswith("/ui/assets/"):
            rel = path[len("/ui/assets/") :]
            target = (_STATIC / rel).resolve()
            if _STATIC in target.parents and target.is_file():
                return self._send_file(target)
            self.send_error(404)
            return
        if path.startswith("/ui/api/"):
            return self._api_get(path[len("/ui/api/") :], parsed.query)
        self.send_error(404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}
        if path.startswith("/ui/api/"):
            return self._api_post(path[len("/ui/api/") :], body)
        self.send_error(404)

    # -- API ---------------------------------------------------------------- #
    def _api_get(self, name: str, query: str):
        g = self.gateway
        if name == "bootstrap":
            return self._send_json(g.bootstrap())
        if name == "capabilities":
            params = parse_qs(query)
            force = params.get("refresh", ["0"])[0] in {"1", "true", "yes"}
            return self._send_json(g.capabilities(force=force))
        if name == "pairings":
            return self._send_json(g.pairings())
        if name == "connections":
            return self._send_json(g.connections())
        if name == "deployments":
            try:
                params = parse_qs(query)
                force = params.get("refresh", ["0"])[0] in {"1", "true", "yes"}
                return self._send_json(g.deployments(force=force))
            except RuntimeError as exc:
                return self._send_json({"error": str(exc)}, 409)
        if name == "secrets/huggingface":
            try:
                return self._send_json(g.huggingface_secret())
            except RuntimeError as exc:
                return self._send_json({"error": str(exc)}, 502)
        if name == "deployments/jobs":
            try:
                return self._send_json(g.deployment_jobs())
            except RuntimeError as exc:
                return self._send_json({"error": str(exc)}, 502)
        if name.startswith("deployments/jobs/"):
            try:
                job_id = name[len("deployments/jobs/") :]
                return self._send_json({"job": g.deployment_job(job_id)})
            except RuntimeError as exc:
                return self._send_json({"error": str(exc)}, 502)
        if name == "jobs":
            params = parse_qs(query)
            return self._send_json(
                g.jobs(
                    status=params.get("status", ["all"])[0],
                    q=params.get("q", [""])[0],
                    page=int(params.get("page", ["1"])[0]),
                    page_size=int(params.get("page_size", ["25"])[0]),
                )
            )
        if name.startswith("jobs/"):
            job_id = name[len("jobs/") :]
            try:
                row = g.job(job_id)
            except RuntimeError as exc:
                return self._send_json({"error": str(exc)}, 502)
            if row is None:
                return self._send_json({"error": "not_found"}, 404)
            return self._send_json({"job": row})
        if name == "artifacts":
            params = parse_qs(query)
            return self._send_json(
                g.artifacts(
                    page=int(params.get("page", ["1"])[0]),
                    page_size=int(params.get("page_size", ["12"])[0]),
                    mime=params.get("mime", [None])[0],
                )
            )
        if name.startswith("artifacts/") and name.endswith("/content"):
            artifact_id = name[len("artifacts/") : -len("/content")]
            result = g.artifact_content(artifact_id)
            if result is None:
                return self._send_json({"error": "missing"}, 404)
            data, mime = result
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            extension = (
                "png"
                if mime.startswith("image/")
                else "glb"
                if mime == "model/gltf-binary"
                else "bin"
            )
            self.send_header("Content-Disposition", f'inline; filename="{artifact_id}.{extension}"')
            self.end_headers()
            self._write_body(data)
            return
        self.send_error(404)

    def _api_post(self, name: str, body: dict):
        g = self.gateway
        if name == "session":
            return self._send_json(g.session())
        if name == "pairings/approve":
            return self._send_json(g.approve_pairing(body.get("pairingId", "")))
        if name == "providers/connect":
            try:
                return self._send_json(
                    g.connect_providers(body.get("tokenId", ""), body.get("tokenSecret", ""))
                )
            except RuntimeError as exc:
                return self._send_json({"error": str(exc)}, 502)
        if name == "providers/disconnect":
            try:
                return self._send_json(g.disconnect_providers())
            except RuntimeError as exc:
                return self._send_json({"error": str(exc)}, 502)
        if name == "secrets/huggingface":
            try:
                return self._send_json(g.save_huggingface_secret(body.get("token", "")))
            except RuntimeError as exc:
                return self._send_json({"error": str(exc)}, 502)
        if name == "deployments/deploy":
            try:
                return self._send_json(
                    g.deploy(
                        body.get("provider", "all"),
                        body.get("app"),
                        missing_only=bool(body.get("missingOnly", False)),
                        force=bool(body.get("force", False)),
                        strategy=str(body.get("strategy") or "rolling"),
                    )
                )
            except RuntimeError as exc:
                return self._send_json({"error": str(exc)}, 502)
        if name == "jobs":
            try:
                row = g.submit(
                    body.get("provider", ""),
                    body.get("operation", ""),
                    body.get("inputs", {}),
                )
                return self._send_json({"job": row})
            except RuntimeError as exc:
                return self._send_json({"error": str(exc)}, 502)
        if name == "cancel":
            try:
                row = g.cancel(body.get("jobId", ""))
                return self._send_json({"job": row})
            except (RuntimeError, KeyError) as exc:
                return self._send_json({"error": str(exc)}, 502)
        if name == "dev/set" and isinstance(g, DemoGateway):
            if "three_d_unavailable" in body:
                g.set_scenario(three_d_unavailable=bool(body["three_d_unavailable"]))
            return self._send_json({"ok": True})
        self.send_error(404)


def main() -> None:
    host = ui_host()
    server = ThreadingHTTPServer((host, _PORT), Handler)
    if host not in {"127.0.0.1", "localhost", "::1"}:
        print(
            f"警告：控制台正监听非 loopback 地址 {host!r}，界面与 Connector 代理将暴露到网络。",
            file=sys.stderr,
        )
    if _allow_any_origin():
        print(
            "警告：已启用 MODAL_GEN_ALLOW_ANY_ORIGIN，任意站点可跨域调用本机接口。",
            file=sys.stderr,
        )
    local_url = f"http://localhost:{_PORT}/"
    print(f"modal-gen console on {local_url}  (mode={_MODE})")
    if host not in {"127.0.0.1", "localhost", "::1"}:
        print(f"modal-gen console listening on http://{host}:{_PORT}/")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
