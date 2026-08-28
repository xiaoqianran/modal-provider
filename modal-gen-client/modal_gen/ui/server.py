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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .demo import DemoEngine, build_capability_snapshot

_HERE = Path(__file__).resolve().parent
_STATIC = _HERE / "assets"
_CLIENT_ORIGIN = os.environ.get("MODAL_GEN_UI_ORIGIN", "http://127.0.0.1:48124")
_MODE = "demo" if os.environ.get("MODAL_GEN_UI_DEMO") else "live"
_CONNECTOR_URL = os.environ.get("MODAL_GEN_CONNECTOR_URL", "http://127.0.0.1:48123").rstrip("/")
_CONNECTOR_TOKEN = os.environ.get("MODAL_GEN_AGENT_TOKEN", "")
_PORT = int(os.environ.get("MODAL_GEN_UI_PORT", "48124"))


# The console is loopback-only by default; it proxies a Connector that owns
# pairing approvals, session tokens and artifact bytes. Set MODAL_GEN_UI_HOST
# to expose it, and MODAL_GEN_ALLOW_ANY_ORIGIN=1 to allow any browser origin.
def ui_host() -> str:
    """Resolved at call time so runtime configuration always applies."""
    return os.environ.get("MODAL_GEN_UI_HOST") or "127.0.0.1"


def _allow_any_origin() -> bool:
    return os.environ.get("MODAL_GEN_ALLOW_ANY_ORIGIN", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
        "*",
    }


# --------------------------------------------------------------------------- #
# Gateways
# --------------------------------------------------------------------------- #
class DemoGateway:
    mode = "demo"

    def __init__(self) -> None:
        self.engine = DemoEngine()

    def bootstrap(self) -> dict:
        return {"mode": "demo", "connector": {"id": "unified-connector", "version": "0.1.0"}}

    def capabilities(self) -> dict:
        return {"snapshot": self.engine.capabilities(), "stale": False}

    def pairings(self) -> dict:
        return {"pairings": self.engine.list_pairings()}

    def approve_pairing(self, pairing_id: str) -> dict:
        return {"status": "approved"}

    def session(self) -> dict:
        return {"status": "paired", "session": self.engine.session_descriptor()}

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

    def artifacts(self) -> dict:
        items = [
            {k: v for k, v in a.items() if k != "_bytes"} for a in self.engine.list_artifacts()
        ]
        return {"artifacts": items}

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
        self.session: dict | None = None
        self._lock = threading.Lock()

    # -- low level ---------------------------------------------------------- #
    def _req(self, method: str, path: str, *, json_body=None, headers=None, token=None):
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
                method, url, json=json_body, headers=hdrs, timeout=5.0, follow_redirects=False
            )
        except httpx.RequestError as exc:
            raise RuntimeError(f"connector unreachable: {exc}") from exc
        if resp.headers.get("content-type", "").startswith("application/json"):
            payload = resp.json() if resp.content else {}
        else:
            payload = resp.text
        if not resp.is_success:
            code = (payload.get("code") if isinstance(payload, dict) else None) or "HTTP"
            raise RuntimeError(f"{code} ({resp.status_code})")
        return payload

    def bootstrap(self) -> dict:
        try:
            health = self._req("GET", "/health")
        except RuntimeError:
            return {"mode": "live", "connector": None, "reachable": False}
        return {"mode": "live", "connector": health.get("connector"), "reachable": True}

    def capabilities(self) -> dict:
        snap = self._req("GET", "/connector/v1/capabilities", token=self.token)
        return {"snapshot": snap, "stale": False}

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
        # two-phase pairing: request, approve via control plane, complete
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
        self.session = second["session"]
        return second

    def jobs(self, status=None, q="", page=1, page_size=25) -> dict:
        url = "/connector/v1/jobs"
        data = self._req("GET", url, token=self.token)
        rows = data.get("jobs", [])
        # filter/sort/paginate client-side for simplicity
        if status and status != "all":
            rows = [r for r in rows if r.get("status") == status]
        if q:
            needle = q.lower()
            rows = [
                r
                for r in rows
                if needle in r["id"].lower() or needle in str(r.get("operation") or "").lower()
            ]
        rows.sort(key=lambda r: str(r.get("updatedAt") or ""), reverse=True)
        total = len(rows)
        start = (page - 1) * page_size
        return {"jobs": rows[start : start + page_size], "page": page, "total": total}

    def job(self, job_id: str) -> dict | None:
        try:
            return self._req("GET", f"/connector/v1/jobs/{job_id}", token=self.token)
        except RuntimeError:
            return None

    def submit(self, provider: str, operation: str, inputs: dict) -> dict:
        body = {
            "provider": provider,
            "operation": operation,
            "inputs": inputs,
            "profile": inputs.get("profile"),
            "options": {},
            "outputRoles": ["primary-image"] if provider == "modal-2d" else ["primary-glb"],
        }
        return self._req("POST", "/connector/v1/jobs", json_body=body, token=self.token)

    def cancel(self, job_id: str) -> dict:
        return self._req("POST", f"/connector/v1/jobs/{job_id}/cancel", token=self.token)

    def artifacts(self) -> dict:
        # derive from jobs' result.artifacts (connector exposes per artifact content)
        seen: dict[str, dict] = {}
        rows = self.jobs(page_size=200).get("jobs", [])
        for job in rows:
            for art in (job.get("result") or {}).get("artifacts", []):
                seen[art["id"]] = {**art, "jobId": job["id"]}
        return {"artifacts": list(seen.values())}

    def artifact_content(self, artifact_id: str) -> tuple[bytes, str] | None:
        try:
            import httpx

            resp = httpx.get(
                f"{_CONNECTOR_URL}/connector/v1/artifacts/{artifact_id}",
                headers={"Authorization": f"Bearer {self.token}", "Origin": _CLIENT_ORIGIN},
                timeout=30.0,
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
        self.wfile.write(body)

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
        self.wfile.write(data)

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        if path == "/ui/" or path == "/ui":
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
            return self._send_json(g.capabilities())
        if name == "pairings":
            return self._send_json(g.pairings())
        if name == "jobs":
            params = dict(p.split("=") for p in query.split("&") if "=" in p)
            return self._send_json(
                g.jobs(
                    status=params.get("status", "all"),
                    q=params.get("q", ""),
                    page=int(params.get("page", "1")),
                    page_size=int(params.get("page_size", "25")),
                )
            )
        if name.startswith("jobs/"):
            job_id = name[len("jobs/") :]
            row = g.job(job_id)
            if row is None:
                return self._send_json({"error": "not_found"}, 404)
            return self._send_json({"job": row})
        if name == "artifacts":
            return self._send_json(g.artifacts())
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
            self.send_header("Content-Disposition", f'attachment; filename="{artifact_id}.bin"')
            self.end_headers()
            self.wfile.write(data)
            return
        self.send_error(404)

    def _api_post(self, name: str, body: dict):
        g = self.gateway
        if name == "session":
            return self._send_json(g.session())
        if name == "pairings/approve":
            return self._send_json(g.approve_pairing(body.get("pairingId", "")))
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
    print(f"modal-gen console on http://{host}:{_PORT}/ui/  (mode={_MODE})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
