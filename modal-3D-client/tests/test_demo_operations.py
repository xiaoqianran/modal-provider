from __future__ import annotations

import time

from fastapi.testclient import TestClient

from modal_3d_client.app import create_app
from modal_3d_client.demo import DemoJobService


def _wait(client: TestClient, job_id: str, timeout: float = 2.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/v1/jobs/{job_id}")
        assert response.status_code == 200
        job = response.json()
        if job["status"] in {"succeeded", "failed", "cancelled"}:
            return job
        time.sleep(0.03)
    raise AssertionError(f"timed out waiting for {job_id}")


def test_demo_asset_operations_end_to_end() -> None:
    service = DemoJobService()
    client = TestClient(create_app(service))

    operations = client.get("/v1/operations")
    assert operations.status_code == 200
    ids = {row["id"] for row in operations.json()["operations"]}
    assert {"segment_parts", "filter_parts", "complete_parts", "texture_generate"} <= ids

    generated = client.post(
        "/v1/jobs",
        files={"file": ("source.png", b"demo-source", "image/png")},
        data={
            "model": "fastsam3d-plus-plus",
            "profile": "recommended",
            "seed": "42",
            "job_id": "job_demo_asset",
        },
    )
    assert generated.status_code == 200
    assert _wait(client, "job_demo_asset")["status"] == "succeeded"

    segmented = client.post(
        "/v1/operations/jobs",
        json={
            "operation": "segment_parts",
            "inputs": {"asset": {"job_id": "job_demo_asset", "role": "primary-glb"}},
            "options": {},
            "job_id": "op_demo_segment",
        },
    )
    assert segmented.status_code == 200
    segment_job = _wait(client, "op_demo_segment")
    assert segment_job["status"] == "succeeded"
    assert {row["role"] for row in segment_job["result"]["artifacts"]} == {
        "primary-glb",
        "parts-manifest",
        "face-labels",
        "quality-report",
    }

    manifest = client.get("/v1/jobs/op_demo_segment/artifact?role=parts-manifest")
    assert manifest.status_code == 200
    assert manifest.json()["role"] == "parts-manifest"

    segmentation_inputs = {
        "asset": {"job_id": "op_demo_segment", "role": "primary-glb"},
        "parts_manifest": {"job_id": "op_demo_segment", "role": "parts-manifest"},
        "face_labels": {"job_id": "op_demo_segment", "role": "face-labels"},
    }
    filtered = client.post(
        "/v1/operations/jobs",
        json={
            "operation": "filter_parts",
            "inputs": segmentation_inputs,
            "options": {"part_indices": [0, 1], "mode": "keep"},
            "job_id": "op_demo_filter",
        },
    )
    assert filtered.status_code == 200
    assert _wait(client, "op_demo_filter")["status"] == "succeeded"

    completed = client.post(
        "/v1/operations/jobs",
        json={
            "operation": "complete_parts",
            "inputs": segmentation_inputs,
            "options": {
                "part_index": 0,
                "seed": 42,
                "num_inference_steps": 10,
                "octree_resolution": 256,
            },
            "job_id": "op_demo_complete",
        },
    )
    assert completed.status_code == 200
    assert _wait(client, "op_demo_complete")["status"] == "succeeded"

    reference = client.post(
        "/v1/assets",
        files={"file": ("reference.png", b"demo-reference-png", "image/png")},
    )
    assert reference.status_code == 200

    textured = client.post(
        "/v1/operations/jobs",
        json={
            "operation": "texture_generate",
            "inputs": {
                "asset": {"job_id": "op_demo_filter", "role": "primary-glb"},
                "reference_image": {"artifact_id": reference.json()["id"]},
            },
            "options": {"preserve_geometry": True},
            "job_id": "op_demo_texture",
        },
    )
    assert textured.status_code == 200
    texture_job = _wait(client, "op_demo_texture")
    assert texture_job["status"] == "succeeded"

    primary = client.get("/v1/jobs/op_demo_texture/artifact?role=primary-glb")
    assert primary.status_code == 200
    assert primary.content.startswith(b"glTF")

    listed = client.get("/v1/jobs?limit=20")
    assert listed.status_code == 200
    listed_ids = {row["id"] for row in listed.json()["jobs"]}
    assert {"job_demo_asset", "op_demo_segment", "op_demo_filter", "op_demo_complete", "op_demo_texture"} <= listed_ids
