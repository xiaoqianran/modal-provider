import pytest

from modal_2d.benchmark import (
    artifact_stats,
    canonical_gpu_name,
    parse_batches,
    parse_gpu_rates,
    run_record,
)


def test_parse_batches():
    assert parse_batches("1,2,4,8") == (1, 2, 4, 8)
    with pytest.raises(ValueError, match="unique"):
        parse_batches("1,1")
    with pytest.raises(ValueError, match=r"\[1, 8\]"):
        parse_batches("16")


def test_parse_gpu_rates():
    assert canonical_gpu_name("NVIDIA L40S") == "L40S"
    assert canonical_gpu_name("NVIDIA RTX PRO 6000 Blackwell Server Edition") == "RTX-PRO-6000"
    assert parse_gpu_rates(["NVIDIA L40S=1.5", "RTX PRO 6000=2.5"]) == {
        "L40S": 1.5,
        "RTX-PRO-6000": 2.5,
    }
    with pytest.raises(ValueError):
        parse_gpu_rates(["L40S"])


def test_artifact_stats():
    assert artifact_stats([{"bytes": 100}, {"bytes": 300}]) == {
        "count": 2,
        "totalBytes": 400,
        "meanBytes": 200.0,
        "bytes": [100, 300],
    }


def test_run_record_includes_gpu_time_memory_and_optional_cost():
    result = {
        "artifacts": [{"bytes": 1024}, {"bytes": 2048}],
        "timing": {
            "worker_reused": False,
            "worker_load_ms": 1000.0,
            "batch_total_ms": 2000.0,
            "gpu": "L40S",
            "peak_allocated_gb": 12.5,
            "peak_reserved_gb": 13.0,
            "items": [{"seed": 1}, {"seed": 2}],
        },
    }
    record = run_record(result, batch=2, e2e_ms=2500.0, gpu_rates={"L40S": 3.6})
    assert record["e2ePerImageMs"] == 1250.0
    assert record["gpuClass"] == "L40S"
    assert record["gpuSeconds"] == 3.0
    assert record["estimatedGpuCostUsd"] == pytest.approx(0.003)
    assert record["estimatedGpuCostPerImageUsd"] == pytest.approx(0.0015)
    assert record["artifacts"]["totalBytes"] == 3072
    assert record["timing"]["peak_allocated_gb"] == 12.5


def test_run_record_rejects_incomplete_batch():
    with pytest.raises(RuntimeError, match="artifacts"):
        run_record(
            {"artifacts": [{"bytes": 1}], "timing": {"items": [{"seed": 1}]}},
            batch=2,
            e2e_ms=1.0,
            gpu_rates={},
        )
