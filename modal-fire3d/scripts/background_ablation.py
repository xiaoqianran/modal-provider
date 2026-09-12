"""Execute a background-only rerun and retrieve its evidence."""
import argparse
import json
import time
from pathlib import Path

import modal

parser = argparse.ArgumentParser()
parser.add_argument("--run-id", required=True)
parser.add_argument("--policy", default="no_room_filter")
parser.add_argument("--source-run", default="20260911T204708Z")
parser.add_argument("--optimized", action="store_true")
parser.add_argument("--decode-resolution", type=int, default=512)
parser.add_argument("--detailed-profile", action="store_true")
parser.add_argument("--no-download", action="store_true")
args = parser.parse_args()
target = Path("acceptance") / args.run_id
target.mkdir(parents=True, exist_ok=False)
if args.optimized:
    worker = modal.Cls.from_name("modal-fire3d-background", "BackgroundWorker")()
    call = worker.reconstruct.spawn(
        args.source_run,
        args.run_id,
        args.policy,
        args.decode_resolution,
        args.detailed_profile,
    )
else:
    function = modal.Function.from_name("modal-fire3d-background", "reconstruct_background")
    call = function.spawn(args.source_run, args.run_id, args.policy)
(target / "call.json").write_text(json.dumps({"call_id": call.object_id}))
print(f"Background call {call.object_id}", flush=True)
client_started = time.perf_counter()
result = call.get()
client_wall_s = time.perf_counter() - client_started
(target / "client_timing.json").write_text(
    json.dumps(
        {
            "remote_compute_s": result["elapsed_s"],
            "pipeline_wall_s": result.get("pipeline_wall_seconds"),
            "client_call_wall_s": client_wall_s,
        },
        indent=2,
    )
)
(target / "result.json").write_text(json.dumps(result, indent=2))
if args.no_download:
    print(
        f"Completed {args.run_id}: remote={result['elapsed_s']:.1f}s "
        f"client={client_wall_s:.1f}s (download skipped)",
        flush=True,
    )
    raise SystemExit(0)

download_started = time.perf_counter()
volume = modal.Volume.from_name("fire3d-output")
for item in result["files"]:
    relative = Path(item["path"])
    if relative.suffix not in {".json", ".glb", ".log", ".npz", ".ply"}:
        continue
    destination = target / "output" / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("wb") as handle:
        for chunk in volume.read_file(f"background/{args.run_id}/{relative.as_posix()}"):
            handle.write(chunk)
download_s = time.perf_counter() - download_started
print(
    f"Retrieved {args.run_id}: remote={result['elapsed_s']:.1f}s "
    f"client={client_wall_s:.1f}s download={download_s:.1f}s",
    flush=True,
)
