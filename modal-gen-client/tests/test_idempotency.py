from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from modal_gen.app import build_runtime
from modal_gen.storage import Store
from tests.test_connector_e2e import ORIGIN, SCOPES, Fake2DAdapter, make_request


class SlowAdapter(Fake2DAdapter):
    def submit(self, *, operation, inputs, profile, options):
        time.sleep(0.05)
        return super().submit(
            operation=operation,
            inputs=inputs,
            profile=profile,
            options=options,
        )


def test_concurrent_same_idempotency_dispatches_provider_once(tmp_path: Path):
    adapter = SlowAdapter()
    runtime = build_runtime(Store(tmp_path / "db.sqlite3"), adapters=[adapter])
    pairing = {
        "clientIdentity": "agentscape",
        "contractVersion": "1",
        "origin": ORIGIN,
        "scopes": SCOPES,
    }
    first = runtime.sessions.pair(pairing, request_origin=ORIGIN)
    runtime.sessions.approve(first["pairingId"])
    paired = runtime.sessions.pair(
        {**pairing, "pairingId": first["pairingId"]},
        request_origin=ORIGIN,
    )
    token = str(paired["token"])
    session = runtime.sessions.authorize(
        f"Bearer {token}",
        "jobs.submit",
        request_origin=ORIGIN,
    )
    snapshot = runtime.capabilities.get(str(session["capability_hash"]))
    assert snapshot is not None
    request = make_request(snapshot)

    with ThreadPoolExecutor(max_workers=2) as executor:
        jobs = list(executor.map(lambda _: runtime.jobs.submit(request, session), range(2)))

    assert jobs[0]["id"] == jobs[1]["id"]
    assert adapter.submit_count == 1
