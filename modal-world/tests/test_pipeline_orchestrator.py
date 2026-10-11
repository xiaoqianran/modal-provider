"""CPU-only behavior checks: all Modal/GPU boundaries are faked."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from modal_world.pipelines.orchestrator import PipelineDependencies, run_stages


@pytest.mark.parametrize("merged,legacy", [(True, False), (False, True)])
@pytest.mark.parametrize("job_id", ["case000", "new-job"])
def test_stage_order_force_timeouts_and_fallback(merged, legacy, job_id):
    calls = []

    def record(name):
        def invoke(*args, **kwargs):
            calls.append((name, args, kwargs))
            return name
        return invoke

    nav = SimpleNamespace(generate_nav=record("nav"), render=record("render"))
    stereo = SimpleNamespace(generate=record("stereo"))
    stage45 = SimpleNamespace(remote=record("stage45"))

    def spawn(method, **kwargs):
        return method(**kwargs)

    deps = PipelineDependencies(
        ensure_static_cache=record("cache"),
        worldnav_factory=lambda: nav, stage0=record("stage0"),
        spawn_worker=spawn, reload_volume=record("reload"),
        resolve_target=lambda job: "/worldgen/jobs/" + job,
        sanitize_semantics=record("sanitize"), commit_volume=record("commit"),
        worldstereo_factory=lambda: stereo, stage45_factory=lambda: stage45,
        stage4=record("stage4"), stage5=record("stage5"),
        runtime_compile=record("compile"),
    )
    stages = run_stages(
        job_id=job_id, prompt="landscape", source_name="input.png",
        seed=7, force=True, steps=100, merge_stage45=merged, deps=deps,
    )
    expected = ["cache", "stage0", "nav", "reload"]
    if job_id != "case000":
        expected.extend(["sanitize", "commit"])
    expected.extend(["render", "stereo"] + (["stage45"] if merged else ["stage4", "stage5"]) + ["compile"])
    assert [name for name, _, _ in calls] == expected
    assert ("stage45" in stages) == merged
    assert ("stage4" in stages and "stage5" in stages) == legacy
    assert [x[2]["wait_timeout_s"] for x in calls if x[0] in ("nav", "render", "stereo")] == [1800, 1800, 2700]
    for name, _, kwargs in calls:
        if name in ("stage0", "nav", "render", "stereo", "stage45", "stage4", "stage5", "compile"):
            assert kwargs["force"] is True
    assert calls[1][2]["prompt"] == "landscape"
    assert calls[1][2]["seed"] == 7


def test_failed_stage_stops_downstream_execution():
    from dataclasses import fields

    calls = []
    def fail(**kwargs):
        raise RuntimeError("stage0 failed")
    deps = {field.name: (lambda *a, **k: None) for field in fields(PipelineDependencies)}
    deps["ensure_static_cache"] = lambda: calls.append("cache")
    deps["stage0"] = fail
    with pytest.raises(RuntimeError, match="stage0 failed"):
        run_stages(job_id="case000", prompt="landscape", source_name="x.png", seed=7,
                   force=False, steps=8000, merge_stage45=True, deps=PipelineDependencies(**deps))
    assert calls == ["cache"]
