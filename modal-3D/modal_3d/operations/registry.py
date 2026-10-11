"""Versioned mesh operations; no Blender/Modal import needed for discovery."""
from __future__ import annotations

REVISION = "mesh-operations.v1-bpy420-xatlas009-r5"
P3SAM_REVISION = "p3sam.e96be065-w67717446-sonata-df998974-v1"
XPART_REVISION = "xpart-lite.e96be065-hf67717446-v1"
HUNYUAN_PAINT_REVISION = "hunyuan3d-paint-v2.1-0b946776-l40s-v1"
HUNYUAN2MV_REVISION = "hunyuan3d-2mv-srcf8db6309-hf3a761b53-l40s-v1"
TOKENRIG_REVISION = "skintokens-273b691d-tokenrig-v1"
POSE_REVISION = "blender-pose-v1"
RESULT_CONTRACT = "modal-3d.operation-result.v1"
MAX_BYTES = 512 * 1024 * 1024
MIMES = {".glb": "model/gltf-binary", ".obj": "model/obj", ".blend": "application/x-blender",
         ".json": "application/json", ".png": "image/png"}


def number(default, minimum, maximum, integer=False):
    return {"type": "integer" if integer else "number", "default": default,
            "minimum": minimum, "maximum": maximum}


def enum(default, values):
    return {"type": "string", "default": default, "enum": list(values)}


def integer_array(default, minimum=0, maximum=255, max_items=256):
    return {"type": "array", "default": list(default), "minItems": 1, "maxItems": max_items,
            "items": {"type": "integer", "minimum": minimum, "maximum": maximum}}


UV_OPTIONS = {"resolution": number(1024, 64, 4096, True),
              "padding": number(8, 1, 64, True), "texels_per_unit": number(0, 0, 10000)}
BAKE_OPTIONS = {"resolution": number(1024, 64, 4096, True),
                "padding": number(8, 1, 64, True),
                "ray_distance": number(0.05, 0.000001, 1000)}
SPECS = {
    "mesh_inspect": {"label": "Inspect mesh", "inputs": ["asset"], "options": {}},
    "mesh_cleanup": {"label": "Clean mesh", "inputs": ["asset"], "options": {
        "merge_distance": number(0.00001, 0, 0.1),
        "remove_loose": {"type": "boolean", "default": True}}},
    "mesh_repair": {"label": "Repair mesh", "inputs": ["asset"], "options": {
        "merge_distance": number(0.00001, 0, 0.1),
        "max_hole_edges": number(8, 3, 100, True)}},
    "mesh_decimate": {"label": "Decimate mesh", "inputs": ["asset"], "options": {
        "target_faces": number(20000, 4, 2000000, True)}},
    "mesh_retopologize": {"label": "QuadriFlow retopology", "inputs": ["asset"], "options": {
        "target_faces": number(4000, 16, 100000, True),
        "preserve_boundary": {"type": "boolean", "default": True},
        "preserve_sharp": {"type": "boolean", "default": True},
        "seed": number(0, 0, 2147483647, True)}},
    "uv_unwrap": {"label": "xatlas UV unwrap", "inputs": ["asset"], "options": UV_OPTIONS},
    "texture_bake": {"label": "Rebake PBR", "inputs": ["source", "target"], "options": BAKE_OPTIONS},
    "parts_segment": {
        "label": "P3-SAM part segmentation",
        "inputs": ["asset"],
        "options": {
            "point_num": number(100000, 10000, 200000, True),
            "prompt_num": number(400, 32, 800, True),
            "threshold": number(0.95, 0.0, 1.0),
            "post_process": {"type": "boolean", "default": True},
            "seed": number(42, 0, 2147483647, True),
            "prompt_bs": number(32, 1, 128, True),
        },
        "worker_app": "modal-3d-p3sam",
        "revision": P3SAM_REVISION,
        "resource": "gpu",
        "required_roles": ["primary-glb", "parts-manifest", "face-labels", "quality-report"],
    },
    "parts_complete": {
        "label": "X-Part lite part completion",
        "inputs": ["asset", "parts_manifest", "face_labels"],
        "input_mimes": {
            "asset": MIMES[".glb"],
            "parts_manifest": MIMES[".json"],
            "face_labels": MIMES[".json"],
        },
        "options": {
            "part_index": number(0, 0, 255, True),
            "seed": number(42, 0, 2147483647, True),
            "num_inference_steps": number(50, 1, 100, True),
            "octree_resolution": number(512, 128, 512, True),
        },
        "worker_app": "modal-3d-xpart",
        "revision": XPART_REVISION,
        "resource": "gpu",
        "required_roles": ["primary-glb", "assembly-preview", "quality-report"],
    },
    "parts_filter": {
        "label": "Select / merge / exclude parts",
        "inputs": ["asset", "parts_manifest", "face_labels"],
        "input_mimes": {"asset": MIMES[".glb"], "parts_manifest": MIMES[".json"],
                        "face_labels": MIMES[".json"]},
        "options": {
            "part_indices": integer_array([0]),
            "mode": enum("keep", ["keep", "exclude"]),
        },
        "required_roles": ["primary-glb", "quality-report"],
    },
    "texture_generate": {
        "label": "Hunyuan3D-Paint 2.1 reference texture",
        "inputs": ["asset", "reference_image"],
        "input_mimes": {"asset": MIMES[".glb"], "reference_image": MIMES[".png"]},
        "options": {
            "preserve_geometry": {"type": "boolean", "default": True},
        },
        "worker_app": "modal-3d-hunyuan-paint",
        "revision": HUNYUAN_PAINT_REVISION,
        "resource": "gpu",
        "required_roles": ["primary-glb", "material-report", "quality-report"],
    },
    "model_generate_multiview": {
        "label": "Hunyuan3D-2mv multi-view to 3D",
        "inputs": ["front", "back", "left", "right"],
        "required_inputs": ["front"],
        "input_mimes": {
            "front": MIMES[".png"],
            "back": MIMES[".png"],
            "left": MIMES[".png"],
            "right": MIMES[".png"],
        },
        "options": {
            "seed": number(12345, 0, 2147483647, True),
            "num_inference_steps": number(50, 1, 100, True),
            "guidance_scale": number(5.0, 0.0, 30.0),
            "octree_resolution": number(380, 128, 512, True),
            "num_chunks": number(20000, 1000, 5000000, True),
        },
        "worker_app": "modal-3d-hunyuan2mv",
        "revision": HUNYUAN2MV_REVISION,
        "resource": "gpu",
        "required_roles": ["primary-glb", "quality-report"],
    },
    "rig_generate": {
        "label": "TokenRig automatic rigging",
        "inputs": ["asset"],
        "options": {
            "top_k": number(5, 1, 200, True),
            "top_p": number(0.95, 0.1, 1.0),
            "temperature": number(1.0, 0.1, 2.0),
            "repetition_penalty": number(2.0, 0.5, 3.0),
            "num_beams": number(10, 1, 20, True),
            "preserve_texture_and_scale": {"type": "boolean", "default": True},
            "postprocess_skin": {"type": "boolean", "default": False},
        },
        "worker_app": "modal-3d-tokenrig",
        "revision": TOKENRIG_REVISION,
        "resource": "gpu",
        "required_roles": ["primary-glb", "rig-report", "quality-report"],
    },
    "pose_apply": {
        "label": "Blender rig pose",
        "inputs": ["asset"],
        "options": {
            "preset": enum("t_pose", ["t_pose", "a_pose", "rest"]),
            "skeleton_profile": enum("auto", ["auto", "mixamo", "vroid", "tokenrig"]),
        },
        "worker_app": "modal-3d-pose",
        "revision": POSE_REVISION,
        "resource": "cpu",
        "required_roles": ["primary-glb", "pose-report", "quality-report"],
    },
}

# Reserved operation IDs: discoverable for planning, never executable.
# They deliberately are NOT members of SPECS until an implementation and tests exist.
PLANNED_SPECS = {
    "mesh_optimize": {"label": "Smart mesh optimization", "resource": "cpu", "inputs": ["asset"]},
    "uv_optimize": {"label": "Advanced UV optimization", "resource": "cpu", "inputs": ["asset"]},
    "texture_edit": {"label": "Localized texture editing", "resource": "gpu", "inputs": ["asset", "mask", "reference_image"]},
    "animation_generate": {"label": "Rigged animation generation", "resource": "gpu", "inputs": ["asset"]},
}