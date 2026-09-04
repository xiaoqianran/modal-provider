from __future__ import annotations

import math
from typing import Any


def _finite_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _finite_vec3(value: object) -> bool:
    return isinstance(value, list) and len(value) == 3 and all(_finite_number(item) for item in value)


def compile_hyworld_semantics(categories_source: object, targets_source: object | None = None) -> dict[str, Any]:
    """Normalize HYWorld category labels and SAM3/depth target evidence for AgentScape.

    Target evidence stays observational: center + scale hints are preserved exactly as
    produced by HYWorld. No AABB, mobility, affordance, or executable capability is inferred.
    """
    if not isinstance(categories_source, list):
        raise TypeError("HYWorld semantic categories must be a list")
    if targets_source is not None and not isinstance(targets_source, list):
        raise TypeError("HYWorld target evidence must be a list when present")

    categories: list[str] = []
    seen_categories: set[str] = set()

    def add_category(value: object) -> str | None:
        if not isinstance(value, str):
            return None
        label = value.strip()
        if not label:
            return None
        key = label.casefold()
        if key not in seen_categories:
            seen_categories.add(key)
            categories.append(label)
        return label

    for item in categories_source:
        add_category(item)

    instances: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for raw in targets_source or []:
        if not isinstance(raw, dict):
            continue
        source_id = raw.get("id")
        if not isinstance(source_id, (str, int)) or isinstance(source_id, bool):
            continue
        label = add_category(raw.get("label"))
        center = raw.get("center_point_3d")
        scale = raw.get("scale_3d")
        score = raw.get("score")
        if not label or not _finite_vec3(center) or not _finite_number(scale) or float(scale) <= 0:
            continue
        if not _finite_number(score) or not 0 <= float(score) <= 1:
            continue
        instance_id = f"hyworld2-target-{source_id}"
        if instance_id in seen_ids:
            continue
        seen_ids.add(instance_id)

        localization: dict[str, Any] = {
            "kind": "point-scale",
            "center": [float(value) for value in center],
            "scale": float(scale),
        }
        left = raw.get("left_point_3d")
        right = raw.get("right_point_3d")
        if _finite_vec3(left):
            localization["leftPoint"] = [float(value) for value in left]
        if _finite_vec3(right):
            localization["rightPoint"] = [float(value) for value in right]

        evidence: dict[str, Any] = {"sourceId": source_id}
        field_map = {
            "mask_area": "maskArea",
            "depth_distance": "depthDistance",
            "bearing_angle": "bearingAngle",
            "edge_center_bearing": "edgeCenterBearing",
            "total_rank": "rank",
        }
        for source_key, target_key in field_map.items():
            value = raw.get(source_key)
            if _finite_number(value):
                evidence[target_key] = float(value) if source_key != "total_rank" else int(value)
        for source_key, target_key in (("direction", "direction"), ("edge_center_direction", "edgeCenterDirection")):
            value = raw.get(source_key)
            if isinstance(value, str) and value.strip():
                evidence[target_key] = value.strip()

        instances.append({
            "id": instance_id,
            "label": label,
            "confidence": float(score),
            "localization": localization,
            "evidence": evidence,
        })

    has_instances = bool(instances)
    return {
        "schemaVersion": 2 if has_instances else 1,
        "granularity": "instance" if has_instances else "category",
        "categories": categories,
        "instances": instances,
        "provenance": {
            "kind": "hyworld2-sam3-depth-targets" if has_instances else "hyworld2-object-labels",
            "categoriesSource": "../objects.json",
            **({"instancesSource": "../camera_trajectory/target_camera.json"} if has_instances else {}),
        },
    }
