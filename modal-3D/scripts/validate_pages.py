from __future__ import annotations

import argparse
import json
import struct
from pathlib import Path, PurePosixPath
from typing import Any

EXPECTED_MODELS = {"fastsam3d", "hunyuan", "hermit", "pixal3d"}
PREVIEW_LIMIT = 15 * 1024 * 1024


def fail(message: str) -> None:
    raise SystemExit(f"pages validation failed: {message}")


def require_number(row: dict[str, Any], key: str, *, positive: bool = True) -> float:
    value = row.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"{row.get('id', '?')}.{key} must be numeric")
    if positive and value <= 0:
        fail(f"{row.get('id', '?')}.{key} must be > 0")
    return float(value)


def resolve_site_path(root: Path, value: str) -> Path:
    rel = PurePosixPath(value.removeprefix("./"))
    if rel.is_absolute() or ".." in rel.parts:
        fail(f"unsafe site path: {value}")
    path = root.joinpath(*rel.parts)
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        fail(f"path escapes site root: {value}")
    return path


def validate_glb(path: Path) -> None:
    with path.open("rb") as handle:
        header = handle.read(12)
    if len(header) != 12:
        fail(f"truncated GLB: {path}")
    magic, version, declared = struct.unpack("<4sII", header)
    if magic != b"glTF" or version != 2:
        fail(f"invalid GLB header: {path}")
    if declared != path.stat().st_size:
        fail(f"GLB byte length mismatch: {path} declares {declared}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", default="site")
    args = parser.parse_args()

    root = Path(args.site)
    data_path = root / "data/results.json"
    if not data_path.is_file():
        fail(f"missing {data_path}")

    data = json.loads(data_path.read_text())
    inputs = data.get("inputs")
    results = data.get("results")
    if not isinstance(inputs, list) or not isinstance(results, dict):
        fail("results.json must contain inputs[] and results{}")
    if not inputs:
        fail("benchmark must contain at least one input")

    seen_inputs: set[str] = set()
    preview_total = 0
    for item in inputs:
        input_id = item.get("id")
        if not isinstance(input_id, str) or not input_id:
            fail("every input needs a non-empty id")
        if input_id in seen_inputs:
            fail(f"duplicate input id: {input_id}")
        seen_inputs.add(input_id)

        image_value = item.get("image")
        if not isinstance(image_value, str):
            fail(f"{input_id}.image is missing")
        image = resolve_site_path(root, image_value)
        if not image.is_file() or image.stat().st_size == 0:
            fail(f"missing input image: {image_value}")
        require_number(item, "width")
        require_number(item, "height")

        rows = results.get(input_id)
        if not isinstance(rows, list):
            fail(f"missing results array for {input_id}")
        ids = [row.get("id") for row in rows]
        if len(ids) != len(set(ids)):
            fail(f"duplicate model ids for {input_id}: {ids}")
        if set(ids) != EXPECTED_MODELS:
            fail(f"{input_id}: expected {sorted(EXPECTED_MODELS)}, got {sorted(ids)}")

        for row in rows:
            model_id = row["id"]
            for key in ("inference_s", "faces", "glb_bytes", "preview_bytes"):
                require_number(row, key)
            preview_value = row.get("preview")
            if not isinstance(preview_value, str):
                fail(f"{input_id}/{model_id}: preview missing")
            preview = resolve_site_path(root, preview_value)
            if not preview.is_file():
                fail(f"{input_id}/{model_id}: preview missing on disk: {preview_value}")
            actual = preview.stat().st_size
            declared = int(row["preview_bytes"])
            if actual != declared:
                fail(
                    f"{input_id}/{model_id}: preview_bytes={declared}, actual={actual}: {preview_value}"
                )
            if actual > PREVIEW_LIMIT:
                fail(f"{input_id}/{model_id}: preview exceeds 15 MiB: {actual}")
            validate_glb(preview)
            preview_total += actual

    if set(results) != seen_inputs:
        fail(f"results keys do not match inputs: {sorted(results)} vs {sorted(seen_inputs)}")

    nojekyll = root / ".nojekyll"
    if not nojekyll.is_file():
        fail(f"missing static asset: {nojekyll}")
    for path in (root / "index.html", root / "app.js", root / "styles.css"):
        if not path.is_file() or path.stat().st_size == 0:
            fail(f"missing static asset: {path}")

    print(
        json.dumps(
            {
                "status": "ok",
                "inputs": len(inputs),
                "models_per_input": len(EXPECTED_MODELS),
                "preview_total_bytes": preview_total,
                "preview_limit_bytes": PREVIEW_LIMIT,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
