from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from modal_gen.ui.demo import DemoEngine, build_capability_snapshot, make_glb, make_png
from modal_gen.ui.server import DemoGateway, Handler

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------- demo
def test_synthetic_png_is_a_real_png() -> None:
    data = make_png(8, 8, 3)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(data) > 8


def test_synthetic_glb_is_a_real_glb() -> None:
    data = make_glb()
    assert data[:4] == b"glTF"
    declared = int.from_bytes(data[8:12], "little")
    assert declared == len(data)


def test_capability_snapshot_marks_unavailable_provider(tmp_path) -> None:
    snapshot = build_capability_snapshot(three_d_unavailable=True)
    statuses = {p["id"]: p["status"] for p in snapshot["providers"]}
    assert statuses["modal-2d"] == "available"
    assert statuses["modal-3d"] == "disabled"


def test_demo_engine_lists_jobs_and_artifacts() -> None:
    engine = DemoEngine()
    jobs = engine.list_jobs(status="all")
    assert jobs["total"] >= 3
    # each seeded job must carry the wire-level fields the UI renders
    for row in jobs["jobs"]:
        assert {"id", "provider", "operation", "status"} <= set(row)
    artifacts = engine.list_artifacts()
    assert artifacts, "demo must seed at least one artifact"


def test_demo_gateway_projects_artifacts_without_bytes() -> None:
    """Artifact rows must be JSON-serialisable (no raw _bytes leaking out)."""
    gateway = DemoGateway()
    payload = gateway.artifacts()
    json.dumps(payload)
    for item in payload["artifacts"]:
        assert "_bytes" not in item
        assert item["hash"].startswith("sha256:")


def test_demo_gateway_submits_and_cancels() -> None:
    gateway = DemoGateway()
    before = gateway.jobs()["total"]
    job = gateway.submit(
        "modal-2d", "modal-2d.image.text_to_image.v1", {"prompt": "x", "model": "sana-sprint-0.6b"}
    )
    assert job["status"] == "accepted"
    assert gateway.jobs()["total"] == before + 1
    cancelled = gateway.cancel(job["id"])
    assert cancelled["status"] == "cancel_requested"


def test_demo_gateway_scenario_toggles_3d() -> None:
    gateway = DemoGateway()
    gateway.set_scenario(three_d_unavailable=True)
    providers = {p["id"]: p["status"] for p in gateway.capabilities()["snapshot"]["providers"]}
    assert providers["modal-3d"] == "disabled"
    gateway.set_scenario(three_d_unavailable=False)
    providers = {p["id"]: p["status"] for p in gateway.capabilities()["snapshot"]["providers"]}
    assert providers["modal-3d"] == "available"


@pytest.mark.parametrize("mode_env", ["demo"])
def test_make_gateway_respects_mode(mode_env, monkeypatch) -> None:

    import modal_gen.ui.server as server

    monkeypatch.setattr(server, "_MODE", mode_env)
    assert isinstance(server.make_gateway(), DemoGateway)


# ------------------------------------------------------------------- server
@pytest.fixture()
def ui_server(monkeypatch):
    monkeypatch.setenv("MODAL_GEN_ALLOW_ANY_ORIGIN", "0")
    Handler.gateway = DemoGateway()
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    host, port = server.server_address[0], server.server_address[1]
    import threading

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://{host}:{port}"
    server.shutdown()
    server.server_close()


def _get(base: str, path: str):
    with urllib.request.urlopen(f"{base}/ui/api/{path}") as resp:  # noqa: S310 - loopback fixture
        return json.loads(resp.read())


@pytest.mark.parametrize("path", ["/", "/ui", "/ui/"])
def test_server_serves_index_html(ui_server: str, path: str) -> None:
    with urllib.request.urlopen(f"{ui_server}{path}") as resp:  # noqa: S310
        body = resp.read().decode()
    assert resp.status == 200
    assert "<title>modal-gen" in body


def test_server_serves_assets_with_js_mime(ui_server: str) -> None:
    for asset, expect in (("styles.css", "text/css"), ("app.js", "text/javascript")):
        with urllib.request.urlopen(f"{ui_server}/ui/assets/{asset}") as resp:  # noqa: S310
            assert resp.headers["Content-Type"].startswith(expect)
            assert resp.read()


def test_server_api_endpoints(ui_server: str) -> None:
    assert _get(ui_server, "bootstrap")["mode"] == "demo"
    assert _get(ui_server, "capabilities")["snapshot"]["providers"]
    assert _get(ui_server, "artifacts")["artifacts"]
    assert _get(ui_server, "deployments")["providers"][0]["status"] == "current"
    assert _get(ui_server, "jobs?status=all&page=1&page_size=25")["total"] >= 3


def test_server_streams_artifact_bytes(ui_server: str) -> None:
    artifact = _get(ui_server, "artifacts")["artifacts"][0]
    with urllib.request.urlopen(  # noqa: S310
        f"{ui_server}/ui/api/artifacts/{artifact['id']}/content"
    ) as resp:
        data = resp.read()
    assert resp.headers["Content-Type"].startswith(artifact["mime"])
    assert len(data) == artifact["bytes"]


def test_server_returns_404_for_unknown_artifact(ui_server: str) -> None:
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(f"{ui_server}/ui/api/artifacts/nope/content")  # noqa: S310
    assert exc.value.code == 404


# ------------------------------------------------------- network exposure
def test_ui_server_binds_all_interfaces_by_default(monkeypatch):
    import modal_gen.ui.server as ui_server

    monkeypatch.delenv("MODAL_GEN_UI_HOST", raising=False)
    assert ui_server.ui_host() == "0.0.0.0"
    monkeypatch.setenv("MODAL_GEN_UI_HOST", "127.0.0.1")
    assert ui_server.ui_host() == "127.0.0.1"


def test_ui_server_json_reflects_origin(ui_server: str) -> None:
    req = urllib.request.Request(  # noqa: S310
        f"{ui_server}/ui/api/bootstrap", headers={"Origin": "https://site.example"}
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        assert resp.headers["Access-Control-Allow-Origin"] == "https://site.example"
        assert resp.headers["Vary"] == "Origin"


def test_ui_server_wildcard_origin_when_enabled(monkeypatch) -> None:
    import modal_gen.ui.server as ui_server

    monkeypatch.setenv("MODAL_GEN_ALLOW_ANY_ORIGIN", "1")
    monkeypatch.setattr(ui_server, "_allow_any_origin", ui_server._allow_any_origin)
    assert ui_server._allow_any_origin() is True
    monkeypatch.delenv("MODAL_GEN_ALLOW_ANY_ORIGIN")
    assert ui_server._allow_any_origin() is True


def test_ui_server_supports_options_preflight(ui_server: str) -> None:
    req = urllib.request.Request(  # noqa: S310
        f"{ui_server}/ui/api/bootstrap",
        method="OPTIONS",
        headers={"Origin": "https://site.example"},
    )
    with urllib.request.urlopen(req) as resp:  # noqa: S310
        assert resp.status == 204
        assert resp.headers["Access-Control-Allow-Origin"] == "https://site.example"


def test_live_gateway_builds_current_connector_job_contract(monkeypatch) -> None:
    from modal_gen.identity import verify_request_identity
    from modal_gen.ui.server import LiveGateway

    gateway = LiveGateway()
    gateway.token = "session-token"
    gateway.session = {"clientIdentity": "agentscape"}
    snapshot = build_capability_snapshot()
    captured = {}

    def fake_req(method, path, *, json_body=None, headers=None, token=None, **kwargs):
        if path == "/v1/capabilities":
            return snapshot
        if path == "/connector/v1/jobs" and method == "POST":
            captured.update(json_body)
            return {"job": {"id": "job_01", "status": "accepted"}}
        raise AssertionError((method, path, headers, token))

    monkeypatch.setattr(gateway, "_req", fake_req)
    row = gateway.submit(
        "modal-2d",
        "modal-2d.image.text_to_image.v1",
        {"prompt": "test", "model": "sana-sprint-0.6b"},
    )
    assert row["id"] == "job_01"
    assert captured["outputRoles"] == ["primary-image"]
    assert captured["capabilityHash"] == snapshot["hash"]
    assert captured["operationVersion"] == "1"
    verify_request_identity(captured)


def test_modal_token_command_parser() -> None:
    import subprocess

    script = r"""
import { parseModalTokenCommand } from "./modal_gen/ui/assets/modal_credentials.js";
const cases = [
  ["modal token set --token-id ak-demo --token-secret as-demo", "ak-demo", "as-demo"],
  ["modal token set --token-id=ak-eq --token-secret=as-eq", "ak-eq", "as-eq"],
];
for (const [input, id, secret] of cases) {
  const parsed = parseModalTokenCommand(input);
  if (!parsed || parsed.tokenId !== id || parsed.tokenSecret !== secret) process.exit(1);
}
if (parseModalTokenCommand("modal token set --token-id only")) process.exit(2);
"""
    subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )


def test_connection_drawer_restores_state_after_connect_request() -> None:
    source = (PROJECT_ROOT / "modal_gen/ui/assets/views/view_connect.js").read_text(
        encoding="utf-8"
    )
    assert 'connectedNow ? "重新连接 Modal" : "连接 Modal"' in source
    assert "saveHf.disabled = !connectedNow" in source
    assert source.count("finally {\n      renderConnectionState();\n    }") >= 2
    assert 'status.textContent = "Modal 已连接。"' in source


def test_live_gateway_uses_longer_timeout_for_provider_connect(monkeypatch) -> None:
    from modal_gen.ui.server import LiveGateway

    gateway = LiveGateway()
    captured = {}

    def fake_req(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return {"providers": []}

    monkeypatch.setattr(gateway, "_req", fake_req)
    gateway.connect_providers("ak-demo", "as-demo")

    assert captured["method"] == "POST"
    assert captured["path"] == "/v1/providers/connect"
    assert captured["timeout"] == 30.0


def test_ui_shell_matches_provider_client_studio(ui_server: str) -> None:
    with urllib.request.urlopen(f"{ui_server}/") as resp:  # noqa: S310
        body = resp.read().decode()

    assert 'class="topbar"' in body
    assert 'class="brand"' in body
    assert 'id="open-settings"' in body
    assert 'id="nav"' in body
    assert 'class="rail"' not in body


def test_toast_resolves_its_host_before_append() -> None:
    import re
    import subprocess

    source = (PROJECT_ROOT / "modal_gen/ui/assets/app.js").read_text(encoding="utf-8")
    match = re.search(
        r'export function toast\(message, kind = ""\) \{.*?\n\}',
        source,
        re.DOTALL,
    )
    assert match is not None
    toast_source = match.group(0).replace("export function", "function", 1)
    script = f"""
const appended = [];
const host = {{ append(value) {{ appended.push(value); }} }};
globalThis.document = {{ getElementById(id) {{ return id === "toast-host" ? host : null; }} }};
globalThis.h = (tag, attrs, message) => ({{ tag, attrs, message, style: {{}}, remove() {{}} }});
globalThis.setTimeout = () => 0;
{toast_source}
toast("connected", "ok");
if (appended.length !== 1 || appended[0].message !== "connected") process.exit(1);
"""
    subprocess.run(
        ["node", "--input-type=module", "--eval", script],
        check=True,
        capture_output=True,
        text=True,
    )


def test_jobs_ui_keeps_latest_query_and_valid_first_page() -> None:
    source = (PROJECT_ROOT / "modal_gen/ui/assets/views/view_jobs.js").read_text(encoding="utf-8")

    assert "let refreshSeq = 0;" in source
    assert "const requestSeq = ++refreshSeq;" in source
    assert "if (requestSeq !== refreshSeq) return;" in source
    assert "disabled: page <= 1" in source
    assert "isTerminal(row.status) ? openJob(row) : onCancel(row)" in source


def test_dialog_ui_restores_focus_and_handles_escape() -> None:
    source = (PROJECT_ROOT / "modal_gen/ui/assets/app.js").read_text(encoding="utf-8")

    assert "const previousFocus = document.activeElement;" in source
    assert 'if (event.key === "Escape")' in source
    assert "previousFocus.focus()" in source
    assert "cancel.focus();" in source


def test_live_gateway_bypasses_environment_proxy(monkeypatch) -> None:
    import httpx

    from modal_gen.ui.server import LiveGateway

    captured = {}

    def fake_request(method, url, **kwargs):
        captured.update({"method": method, "url": url, **kwargs})
        request = httpx.Request(method, url)
        return httpx.Response(200, json={"ok": True}, request=request)

    monkeypatch.setattr(httpx, "request", fake_request)
    result = LiveGateway()._req("GET", "/health")

    assert result == {"ok": True}
    assert captured["trust_env"] is False


class _DisconnectingWriter:
    def __init__(self, exc: OSError) -> None:
        self.exc = exc

    def write(self, _data: bytes) -> None:
        raise self.exc


def test_ui_response_write_ignores_client_disconnects():
    from modal_gen.ui.server import Handler

    handler = object.__new__(Handler)
    for exc in (
        BrokenPipeError(),
        ConnectionAbortedError(),
        ConnectionResetError(),
    ):
        handler.wfile = _DisconnectingWriter(exc)
        handler._write_body(b"payload")


def test_demo_gateway_artifacts_are_paginated() -> None:
    gateway = DemoGateway()
    first = gateway.artifacts(page=1, page_size=1)
    second = gateway.artifacts(page=2, page_size=1)
    assert first["pageSize"] == 1
    assert first["total"] >= 1
    assert len(first["artifacts"]) == 1
    if first["total"] == 1:
        assert second["artifacts"] == []
    else:
        assert second["artifacts"][0]["id"] != first["artifacts"][0]["id"]


def test_live_gateway_capability_snapshot_uses_short_ui_cache(monkeypatch) -> None:
    from modal_gen.ui.server import LiveGateway

    gateway = LiveGateway()
    snapshot = build_capability_snapshot()
    calls = []

    def fake_req(method, path, **kwargs):
        calls.append((method, path))
        return snapshot

    monkeypatch.setattr(gateway, "_req", fake_req)
    assert gateway.capabilities()["cached"] is False
    assert gateway.capabilities()["cached"] is True
    assert gateway.capabilities(force=True)["cached"] is False
    assert calls == [("GET", "/v1/capabilities"), ("GET", "/v1/capabilities?refresh=1")]


def test_live_gateway_jobs_only_refreshes_visible_page(monkeypatch) -> None:
    from modal_gen.ui.server import LiveGateway

    gateway = LiveGateway()
    gateway.token = "session-token"
    rows = [
        {
            "id": f"job_{i}",
            "status": "running",
            "operation": "generate",
            "updatedAt": f"2026-08-31T00:00:0{i}Z",
            "model": {"id": "m"},
        }
        for i in range(4)
    ]
    detail_calls = []

    def fake_req(method, path, **kwargs):
        if path.startswith("/connector/v1/jobs?"):
            return {"jobs": [rows[2]], "total": len(rows)}
        detail_calls.append(path)
        job_id = path.rsplit("/", 1)[-1]
        return {"job": next(item for item in rows if item["id"] == job_id)}

    monkeypatch.setattr(gateway, "_req", fake_req)
    result = gateway.jobs(page=2, page_size=1)
    assert result["total"] == 4
    assert [item["id"] for item in result["jobs"]] == ["job_2"]
    assert detail_calls == ["/connector/v1/jobs/job_2"]


def test_live_gateway_artifacts_pages_without_remote_job_refresh(monkeypatch) -> None:
    from modal_gen.ui.server import LiveGateway

    gateway = LiveGateway()
    gateway.token = "session-token"
    artifact = {
        "id": "art_new",
        "role": "primary-image",
        "mime": "image/png",
        "bytes": 10,
        "hash": "sha256:a",
        "jobId": "job_new",
        "updatedAt": "2026-08-31T00:00:02Z",
        "model": "image-model",
    }
    calls = []

    def fake_req(method, path, **kwargs):
        calls.append(path)
        assert path.startswith("/connector/v1/artifacts?")
        return {"artifacts": [artifact], "total": 2}

    monkeypatch.setattr(gateway, "_req", fake_req)
    result = gateway.artifacts(page=1, page_size=1)
    assert result["total"] == 2
    assert result["artifacts"][0]["id"] == "art_new"
    assert result["artifacts"][0]["model"] == "image-model"
    assert len(calls) == 1


def test_generation_studio_ui_has_batch_prompt_and_lazy_glb_viewer() -> None:
    create_source = (PROJECT_ROOT / "modal_gen/ui/assets/views/view_create.js").read_text(
        encoding="utf-8"
    )
    artifact_source = (PROJECT_ROOT / "modal_gen/ui/assets/views/view_artifacts.js").read_text(
        encoding="utf-8"
    )
    index = (PROJECT_ROOT / "modal_gen/ui/assets/index.html").read_text(encoding="utf-8")

    assert "一行一个 Prompt" in create_source
    assert "parsePromptLines" in create_source
    submit_source = create_source.split("const onSubmit", 1)[1].split(
        "function renderSourcePicker", 1
    )[0]
    assert 'location.hash = "#/jobs"' not in submit_source
    assert "page_size=8" in create_source
    assert 'h("model-viewer"' in artifact_source
    assert 'removeAttribute("src")' in artifact_source
    assert "PAGE_SIZE = 12" in artifact_source
    assert (
        'import("https://ajax.googleapis.com/ajax/libs/model-viewer/4.3.1/model-viewer.min.js")'
        in artifact_source
    )
    assert "model-viewer/4.3.1/model-viewer.min.js" not in index


def test_ui_surfaces_deployed_but_blocked_models() -> None:
    connect = (PROJECT_ROOT / "modal_gen/ui/assets/views/view_connect.js").read_text(
        encoding="utf-8"
    )
    create = (PROJECT_ROOT / "modal_gen/ui/assets/views/view_create.js").read_text(encoding="utf-8")
    presenter = (PROJECT_ROOT / "modal_gen/ui/assets/runtime_presenter.js").read_text(
        encoding="utf-8"
    )

    assert "capabilityModels" in connect
    assert "runtime_presenter.js" in connect
    assert "unavailableProviderPanel" in create
    assert "runtime_presenter.js" in create
    assert 'return capability?.status === "available";' in presenter
    assert "已部署" in presenter
    assert "版本过旧" in presenter


def test_runtime_ui_exposes_explicit_global_deployment_modes() -> None:
    source = (PROJECT_ROOT / "modal_gen/ui/assets/views/view_connect.js").read_text(
        encoding="utf-8"
    )

    assert "仅部署缺失 Runtime" in source
    assert "重新部署全部 Runtime" in source
    assert "missingOnly: true" in source
    assert "force: false" in source
    assert "missingOnly: false" in source
    assert "force: true" in source
    assert 'strategy: "rolling"' in source
    assert 'app.status === "current"' in source


def test_live_gateway_submit_retries_timeout_with_same_identity(monkeypatch) -> None:
    from modal_gen.ui.server import LiveGateway

    gateway = LiveGateway()
    gateway.token = "session-token"
    snapshot = build_capability_snapshot()
    attempts = []

    def fake_req(method, path, **kwargs):
        if path == "/v1/capabilities":
            return snapshot
        if path == "/connector/v1/jobs" and method == "POST":
            attempts.append(kwargs)
            if len(attempts) == 1:
                raise RuntimeError("connector unreachable: timed out")
            return {"job": {"id": "job_retry", "status": "accepted"}}
        raise AssertionError((method, path, kwargs))

    monkeypatch.setattr(gateway, "_req", fake_req)
    row = gateway.submit(
        "modal-2d",
        "modal-2d.image.text_to_image.v1",
        {"prompt": "test", "model": "sana-sprint-0.6b"},
    )

    assert row["id"] == "job_retry"
    assert len(attempts) == 2
    assert attempts[0]["timeout"] == attempts[1]["timeout"] == 20.0
    assert attempts[0]["json_body"]["idempotencyKey"] == attempts[1]["json_body"]["idempotencyKey"]


def test_live_gateway_force_refresh_and_redeploy_are_forwarded(monkeypatch) -> None:
    from modal_gen.ui.server import LiveGateway

    gateway = LiveGateway()
    calls = []

    def fake_req(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return {"providers": []} if method == "GET" else {"job": {"id": "dep_1"}}

    monkeypatch.setattr(gateway, "_req", fake_req)
    gateway.deployments(force=True)
    gateway.deploy("modal-3d", "modal-3d-rembg", force=True, strategy="rolling")

    assert calls[0][1] == "/v1/deployments?refresh=1"
    assert calls[1][2]["json_body"] == {
        "provider": "modal-3d",
        "missingOnly": False,
        "force": True,
        "strategy": "rolling",
        "app": "modal-3d-rembg",
    }


def test_runtime_ui_exposes_resync_and_model_value_sync() -> None:
    connect = (PROJECT_ROOT / "modal_gen/ui/assets/views/view_connect.js").read_text(
        encoding="utf-8"
    )
    create = (PROJECT_ROOT / "modal_gen/ui/assets/views/view_create.js").read_text(encoding="utf-8")

    assert "重新同步状态" in connect
    assert 'apiGet("deployments?refresh=1")' in connect
    assert "loadCapabilities({ refresh: true })" in connect
    assert "loadCapabilities({ refresh: true })" in create
    assert "Runtime 状态校验失败" in create
    assert "values[key] = readFieldControl(ref.control, ref.spec)" in create
    assert "required && spec.enum.length === 1" in create


def test_live_gateway_active_job_refresh_is_bounded_and_surfaces_delay(monkeypatch) -> None:
    from modal_gen.ui.server import LiveGateway

    gateway = LiveGateway()
    gateway.token = "session-token"
    running = {
        "id": "job_running",
        "status": "running",
        "provider": "modal-3d",
        "operation": "modal-3d.asset.image_to_3d.v1",
    }
    calls = []

    def fake_req(method, path, **kwargs):
        calls.append((method, path, kwargs.get("timeout")))
        if path.startswith("/connector/v1/jobs?"):
            return {"jobs": [running], "total": 1}
        if path == "/connector/v1/jobs/job_running":
            raise RuntimeError("connector unreachable: timed out")
        raise AssertionError(path)

    monkeypatch.setattr(gateway, "_req", fake_req)
    result = gateway.jobs(page=1, page_size=25)
    assert result["jobs"][0]["status"] == "running"
    assert result["jobs"][0]["syncDelayed"] is True
    assert "timed out" in result["jobs"][0]["syncError"]
    assert calls[-1] == ("GET", "/connector/v1/jobs/job_running", 20.0)


def test_live_gateway_job_detail_uses_generation_timeout(monkeypatch) -> None:
    from modal_gen.ui.server import LiveGateway

    gateway = LiveGateway()
    gateway.token = "session-token"
    captured = {}

    def fake_req(method, path, **kwargs):
        captured.update({"method": method, "path": path, **kwargs})
        return {"job": {"id": "job_done", "status": "succeeded"}}

    monkeypatch.setattr(gateway, "_req", fake_req)
    result = gateway.job("job_done")
    assert result["status"] == "succeeded"
    assert captured["path"] == "/connector/v1/jobs/job_done"
    assert captured["timeout"] == 20.0


def test_jobs_ui_prevents_overlapping_auto_refresh_and_marks_sync_delay() -> None:
    source = (PROJECT_ROOT / "modal_gen/ui/assets/views/view_jobs.js").read_text(encoding="utf-8")
    assert "if (silent && activeRefreshes > 0) return;" in source
    assert "activeRefreshes = Math.max(0, activeRefreshes - 1);" in source
    assert "状态同步延迟" in source


def test_live_gateway_rebuilds_session_when_capability_hash_changes(monkeypatch) -> None:
    from modal_gen.ui.server import LiveGateway

    gateway = LiveGateway()
    gateway.token = "old-token"
    gateway.session_data = {"capabilityHash": "sha256:old"}
    calls = []

    def fake_session():
        calls.append(True)
        gateway.token = "new-token"
        gateway.session_data = {"capabilityHash": "sha256:new"}
        return {"status": "paired"}

    monkeypatch.setattr(gateway, "session", fake_session)
    gateway._ensure_session({"hash": "sha256:new"})

    assert calls == [True]
    assert gateway.token == "new-token"


def test_runtime_deploy_requires_huggingface_secret_in_ui():
    source = Path("modal_gen/ui/assets/views/view_connect.js").read_text(encoding="utf-8")
    assert 'apiGet("secrets/huggingface")' in source
    assert "请先保存 Hugging Face Token" in source
