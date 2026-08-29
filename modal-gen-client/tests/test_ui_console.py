from __future__ import annotations

import json
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from modal_gen.ui.demo import DemoEngine, build_capability_snapshot, make_glb, make_png
from modal_gen.ui.server import DemoGateway, Handler


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

    def fake_req(method, path, *, json_body=None, headers=None, token=None):
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
        cwd=".",
        capture_output=True,
        text=True,
    )


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
