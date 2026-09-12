"""Explicit partial-observation policy; never patch the upstream checkout."""

import hashlib
import json
from pathlib import Path


def write_background_protocol(root: Path, output: Path, dataset: str, policy: str) -> Path | None:
    if policy not in {"official", "observed_single_image"}:
        raise ValueError(f"unknown background policy: {policy}")
    if policy == "official":
        return None
    if dataset != "single_image":
        raise ValueError("observed_single_image requires the single_image dataset")
    if (output / "reconstruction").exists() or (output / "summary.json").exists():
        raise FileExistsError("background repair requires a fresh output directory")
    source = root / "configs/inference/fire3d_single_image_v1.json"
    source_bytes = source.read_bytes()
    protocol = json.loads(source_bytes)
    protocol["reconstruction"]["background"]["room_box_prior"] = False
    protocol["name"] = "fire3d_single_image_observed_background_v1"
    protocol["status"] = "local_repair"
    protocol["description"] = "Local single-view repair: preserve observed background conditioning."
    protocol["lineage"] = {
        "behavior_source": "fire3d_single_image_v1",
        "behavior_source_sha256": hashlib.sha256(source_bytes).hexdigest(),
        "semantic_contract": "Only reconstruction.background.room_box_prior changes to false.",
    }
    path = output / "protocols" / f"{protocol['name']}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(protocol, indent=2) + "\n", encoding="utf-8")
    return path
