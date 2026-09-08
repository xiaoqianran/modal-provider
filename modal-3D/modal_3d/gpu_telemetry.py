from __future__ import annotations

import os
import subprocess
import threading
import time
from contextlib import contextmanager


def _percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    if lo == hi:
        return ordered[lo]
    frac = pos - lo
    return ordered[lo] * (1.0 - frac) + ordered[hi] * frac


def _summary(samples: list[dict]) -> dict:
    def values(key: str) -> list[float]:
        return [float(sample[key]) for sample in samples if sample.get(key) is not None]

    gpu = values("gpu_util_pct")
    memory = values("memory_util_pct")
    vram = values("vram_mib")
    power = values("power_w")
    clocks = values("sm_clock_mhz")
    return {
        "samples": len(samples),
        "gpu_util_avg_pct": round(sum(gpu) / len(gpu), 2) if gpu else None,
        "gpu_util_p50_pct": round(_percentile(gpu, 0.50), 2) if gpu else None,
        "gpu_util_p95_pct": round(_percentile(gpu, 0.95), 2) if gpu else None,
        "gpu_util_max_pct": round(max(gpu), 2) if gpu else None,
        "memory_util_avg_pct": round(sum(memory) / len(memory), 2) if memory else None,
        "peak_vram_gb": round(max(vram) / 1024, 3) if vram else None,
        "power_avg_w": round(sum(power) / len(power), 2) if power else None,
        "power_max_w": round(max(power), 2) if power else None,
        "sm_clock_avg_mhz": round(sum(clocks) / len(clocks), 2) if clocks else None,
    }


def _gib(value: int) -> float:
    return round(value / (1024**3), 3)


class GpuStageProfiler:
    """Stage timings, PyTorch allocator stats, and board-level NVIDIA telemetry.

    PIXAL3D_PROFILE=1 enables nvidia-smi sampling. Timings and allocator
    snapshots remain available even when sampling is disabled. CUDA
    synchronization is done only at stage boundaries so timings reflect actual
    GPU completion rather than enqueue latency.
    """

    FIELDS = (
        "utilization.gpu",
        "utilization.memory",
        "memory.used",
        "power.draw",
        "clocks.sm",
    )

    def __init__(self, torch_module, *, env_prefix: str = "PIXAL3D"):
        self.torch = torch_module
        self.enabled = os.environ.get(f"{env_prefix}_PROFILE", "0") == "1"
        try:
            interval = float(os.environ.get(f"{env_prefix}_TELEMETRY_INTERVAL_S", "0.5"))
        except ValueError:
            interval = 0.5
        self.interval_s = max(0.25, interval)
        self.timings: dict[str, float] = {}
        self.stage_cuda_memory: dict[str, dict[str, float]] = {}
        self.samples: list[dict] = []
        self.stage_name = "idle"
        self.stop_event = threading.Event()
        self.started_at = 0.0
        self.thread: threading.Thread | None = None

    @staticmethod
    def _float(value: str) -> float | None:
        try:
            return float(value.strip())
        except ValueError:
            return None

    def start(self):
        if not self.enabled:
            return self
        self.started_at = time.perf_counter()

        def loop():
            query = ",".join(self.FIELDS)
            while not self.stop_event.is_set():
                sample_t = time.perf_counter()
                try:
                    out = subprocess.check_output(
                        [
                            "nvidia-smi",
                            f"--query-gpu={query}",
                            "--format=csv,noheader,nounits",
                        ],
                        text=True,
                        stderr=subprocess.DEVNULL,
                        timeout=2,
                    )
                    parts = [part.strip() for part in out.splitlines()[0].split(",")]
                    if len(parts) == len(self.FIELDS):
                        parsed = [self._float(part) for part in parts]
                        self.samples.append(
                            {
                                "t_s": round(sample_t - self.started_at, 3),
                                "stage": self.stage_name,
                                "gpu_util_pct": parsed[0],
                                "memory_util_pct": parsed[1],
                                "vram_mib": parsed[2],
                                "power_w": parsed[3],
                                "sm_clock_mhz": parsed[4],
                            }
                        )
                except (subprocess.SubprocessError, ValueError, IndexError):
                    pass
                elapsed = time.perf_counter() - sample_t
                self.stop_event.wait(max(0.0, self.interval_s - elapsed))

        self.thread = threading.Thread(target=loop, daemon=True)
        self.thread.start()
        return self

    @contextmanager
    def stage(self, name: str, *, cuda_sync: bool = True):
        self.stage_name = name
        cuda = self.torch.cuda
        cuda_available = cuda.is_available()
        if cuda_sync and cuda_available:
            cuda.synchronize()
        if cuda_available:
            allocated_before = cuda.memory_allocated()
            reserved_before = cuda.memory_reserved()
            cuda.reset_peak_memory_stats()
        else:
            allocated_before = reserved_before = 0
        t0 = time.perf_counter()
        try:
            yield
        finally:
            if cuda_sync and cuda_available:
                cuda.synchronize()
            self.timings[f"{name}_s"] = time.perf_counter() - t0
            if cuda_available:
                self.stage_cuda_memory[name] = {
                    "allocated_before_gb": _gib(allocated_before),
                    "allocated_after_gb": _gib(cuda.memory_allocated()),
                    "peak_allocated_gb": _gib(cuda.max_memory_allocated()),
                    "reserved_before_gb": _gib(reserved_before),
                    "reserved_after_gb": _gib(cuda.memory_reserved()),
                    "peak_reserved_gb": _gib(cuda.max_memory_reserved()),
                }

    def stop(self) -> dict:
        if self.enabled:
            self.stop_event.set()
            if self.thread is not None:
                self.thread.join(timeout=2)
        result = _summary(self.samples)
        stages: dict[str, list[dict]] = {}
        for sample in self.samples:
            stages.setdefault(str(sample["stage"]), []).append(sample)
        result.update(
            {
                "enabled": self.enabled,
                "interval_s": self.interval_s,
                "stages": {name: _summary(items) for name, items in stages.items()},
                "stage_cuda_memory": self.stage_cuda_memory,
            }
        )
        return result
