from __future__ import annotations

import hashlib
from pathlib import Path

from modal_gen.app import build_runtime
from modal_gen.providers.protocol import ProviderArtifact, ProviderJob
from modal_gen.storage import Store
from tests.test_connector_e2e import ORIGIN, Fake2DAdapter, make_request


class BatchAdapter(Fake2DAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.items = tuple(
            ProviderArtifact(
                id=f"image_{index}",
                role="primary-image",
                mime="image/png",
                bytes=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
            )
            for index, data in enumerate((b"\x89PNG\r\n\x1a\none", b"\x89PNG\r\n\x1a\ntwo"))
        )

    def get(self, provider_job_id):
        return ProviderJob(
            id=provider_job_id,
            status="succeeded",
            model="sana-sprint-0.6b",
            artifacts=self.items,
        )


def test_job_accepts_multiple_artifacts_with_same_role(tmp_path: Path):
    adapter = BatchAdapter()
    runtime = build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[adapter])
    snapshot = runtime.capabilities.snapshot()
    session = {
        "client_identity": "agentscape",
        "origin": ORIGIN,
        "capability_hash": snapshot["hash"],
        "capability_revision": snapshot["revision"],
    }
    job = runtime.jobs.submit(make_request(snapshot), session)
    finished = runtime.jobs.get(str(job["id"]), session)
    artifacts = finished["result"]["artifacts"]
    assert len(artifacts) == 2
    assert [item["role"] for item in artifacts] == ["primary-image", "primary-image"]
    assert artifacts[0]["id"] != artifacts[1]["id"]
