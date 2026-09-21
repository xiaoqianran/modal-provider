"""Isolated Blender 4.2 process for deterministic asset processing.

Invoked with a JSON request by operation_runner; never imports Modal.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

import bpy  # isort: skip
import bmesh  # isort: skip
import numpy as np
import xatlas
from mathutils.bvhtree import BVHTree


def filter_parts(asset_path, manifest_path, labels_path, options, output):
    import trimesh

    mesh = trimesh.load(asset_path, force="mesh", process=False)
    if not isinstance(mesh, trimesh.Trimesh):
        raise ValueError("filter_parts requires one triangle mesh")
    labels_doc = json.loads(Path(labels_path).read_text(encoding="utf-8"))
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    labels = np.asarray(labels_doc.get("labels"), dtype=np.int64)
    if labels_doc.get("schema") != "modal-3d.face-labels.v1" or len(labels) != len(mesh.faces):
        raise ValueError("face labels do not align with mesh faces")
    parts = manifest.get("parts")
    if manifest.get("schema") != "modal-3d.part-set.v1" or not isinstance(parts, list):
        raise ValueError("invalid PartSet manifest")
    ordinals = set(options["part_indices"])
    if any(index >= len(parts) for index in ordinals):
        raise ValueError(f"part index out of range for {len(parts)} parts")
    selected = {int(parts[index]["source_label"]) for index in ordinals}
    available = set(int(x) for x in np.unique(labels) if x >= 0)
    missing = selected - available
    if missing:
        raise ValueError(f"unknown part indices: {sorted(missing)}")
    mask = np.isin(labels, list(selected))
    if options["mode"] == "exclude":
        mask = ~mask
    indices = np.flatnonzero(mask)
    if not len(indices):
        raise ValueError("part selection produced an empty mesh")
    result = mesh.submesh([indices], append=True, repair=False)
    if not isinstance(result, trimesh.Trimesh) or not len(result.faces):
        raise ValueError("part selection produced an invalid mesh")
    result.export(output / "asset.glb")
    report = {
        "schema": "modal-3d.quality-report.v1",
        "operation": "filter_parts",
        "mode": options["mode"],
        "selected_part_indices": sorted(ordinals),
        "selected_source_labels": sorted(selected),
        "source_faces": int(len(mesh.faces)),
        "output_faces": int(len(result.faces)),
        "source_space": "unchanged",
        "face_mapping_source": "modal-3d.face-labels.v1",
    }
    (output / "quality.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output / "runtime.json").write_text(json.dumps({
        "artifacts": [
            {"role": "primary-glb", "file": "asset.glb"},
            {"role": "quality-report", "file": "quality.json"},
        ],
        "metrics": report,
    }), encoding="utf-8")


def activate(obj):
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def load(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=str(path))
    objects = [o for o in bpy.data.objects if o not in before and o.type == "MESH"]
    if not objects:
        raise ValueError("input has no mesh objects")
    for obj in objects:
        if not obj.data.polygons:
            raise ValueError("empty mesh object")
        # Separate instanced meshes so modifying one does not mutate other instances.
        obj.data = obj.data.copy()
    return objects


def stats(objects):
    vertices = faces = triangles = quads = boundary = nonmanifold = degenerate = components = 0
    geometric_vertices = serialized_boundary = serialized_nonmanifold = 0
    coordinates, geometry = [], hashlib.sha256()
    uv_report = []
    for obj in objects:
        mesh = obj.data
        mesh.calc_loop_triangles()
        vertices += len(mesh.vertices)
        faces += len(mesh.polygons)
        triangles += len(mesh.loop_triangles)
        quads += sum(len(p.vertices) == 4 for p in mesh.polygons)
        xyz = np.array([tuple(obj.matrix_world @ v.co) for v in mesh.vertices], dtype=np.float64)
        if not np.isfinite(xyz).all():
            raise ValueError("mesh contains non-finite coordinates")
        coordinates.extend(xyz.tolist())
        geometry.update(xyz.tobytes())
        geometry.update(str([tuple(p.vertices) for p in mesh.polygons]).encode())
        bm = bmesh.new()
        bm.from_mesh(mesh)
        serialized_boundary += sum(e.is_boundary for e in bm.edges)
        serialized_nonmanifold += sum(not e.is_manifold for e in bm.edges)
        extent = max((float(v) for v in obj.dimensions), default=0.0)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=max(extent * 1e-7, 1e-9))
        geometric_vertices += len(bm.verts)
        boundary += sum(e.is_boundary for e in bm.edges)
        nonmanifold += sum(not e.is_manifold for e in bm.edges)
        degenerate += sum(f.calc_area() < 1e-12 for f in bm.faces)
        remaining = set(bm.verts)
        while remaining:
            stack = [remaining.pop()]
            components += 1
            while stack:
                for edge in stack.pop().link_edges:
                    for v in edge.verts:
                        if v in remaining:
                            remaining.remove(v)
                            stack.append(v)
        bm.free()
        if mesh.uv_layers.active:
            uv = np.array([tuple(x.uv) for x in mesh.uv_layers.active.data])
            uv_report.append({"object": obj.name, "finite": bool(np.isfinite(uv).all()),
                              "outside_unit_square": int(np.sum(np.any((uv < -1e-6) | (uv > 1.000001), axis=1)))})
    points = np.array(coordinates)
    return {"vertices": vertices, "geometric_vertices": geometric_vertices,
            "polygons": faces, "triangles": triangles,
            "quads": quads, "quad_ratio": quads / max(1, faces), "components": components,
            "boundary_edges": boundary, "nonmanifold_edges": nonmanifold,
            "serialized_boundary_edges": serialized_boundary,
            "serialized_nonmanifold_edges": serialized_nonmanifold,
            "degenerate_faces": degenerate, "objects": len(objects),
            "bounds": [points.min(axis=0).tolist(), points.max(axis=0).tolist()],
            "geometry_revision": geometry.hexdigest(), "uv": uv_report,
            "materials": sum(len(o.data.materials) for o in objects)}


def clean(obj, options, repair=False):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    distance = options["merge_distance"]
    if distance:
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=distance)
    bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=max(distance, 1e-12))
    if options.get("remove_loose", False):
        loose = [v for v in bm.verts if not v.link_faces]
        bmesh.ops.delete(bm, geom=loose, context="VERTS")
    if repair:
        bmesh.ops.holes_fill(bm, edges=[e for e in bm.edges if e.is_boundary],
                             sides=options["max_hole_edges"])
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    obj.data.update()


def unwrap(obj, options):
    # Triangulate first to make UV and material face correspondence unambiguous.
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    bmesh.ops.triangulate(bm, faces=list(bm.faces))
    bm.to_mesh(obj.data)
    bm.free()
    mesh = obj.data
    vertices = np.array([tuple(v.co) for v in mesh.vertices], dtype=np.float32)
    indices = np.array([tuple(p.vertices) for p in mesh.polygons], dtype=np.uint32)
    atlas = xatlas.Atlas()
    atlas.add_mesh(vertices, indices)
    pack = xatlas.PackOptions()
    pack.resolution = options["resolution"]
    pack.padding = options["padding"]
    if options.get("texels_per_unit"):
        pack.texels_per_unit = options["texels_per_unit"]
    atlas.generate(pack_options=pack)
    mapping, faces, uv = atlas[0]
    if atlas.atlas_count != 1:
        raise ValueError("UV needs multiple atlases; reduce texels_per_unit or increase resolution")
    if not np.isfinite(uv).all():
        raise ValueError("xatlas produced non-finite UVs")
    materials = list(mesh.materials)
    face_material = {tuple(sorted(p.vertices)): p.material_index for p in mesh.polygons}
    result = bpy.data.meshes.new(mesh.name + "_uv")
    result.from_pydata(vertices[mapping].tolist(), [], faces.tolist())
    for material in materials:
        result.materials.append(material)
    layer = result.uv_layers.new(name="UVMap")
    for polygon in result.polygons:
        original = tuple(sorted(int(mapping[v]) for v in polygon.vertices))
        polygon.material_index = face_material[original]
        for loop in polygon.loop_indices:
            layer.data[loop].uv = uv[result.loops[loop].vertex_index]
    obj.data = result
    return {"object": obj.name, "width": atlas.width, "height": atlas.height,
            "utilization": atlas.utilization, "charts": atlas.chart_count,
            "vertex_mapping": mapping.tolist(),
            "note": "UV changed; original texture coordinates must be rebaked"}


def save_assets(objects, output, editable=True):
    bpy.ops.object.select_all(action="DESELECT")
    for obj in objects:
        obj.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(output / "asset.glb"), export_format="GLB",
                              use_selection=True, export_yup=True)
    result = [{"role": "primary-glb", "file": "asset.glb"}]
    if editable:
        bpy.ops.wm.obj_export(filepath=str(output / "editable.obj"), export_selected_objects=True,
                               export_materials=False, export_triangulated_mesh=False)
        result.append({"role": "editable-source", "file": "editable.obj"})
    return result


def set_source_channel(sources, channel):
    """Temporarily route a Principled input to emission for unlit scalar/color baking."""
    restores = []
    materials = {mat for obj in sources for mat in obj.data.materials if mat is not None}
    for mat in materials:
        mat.use_nodes = True
        tree = mat.node_tree
        bsdf = next((n for n in tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        output = next((n for n in tree.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
        if bsdf is None or output is None:
            raise ValueError("rebake requires Principled BSDF source materials")
        old = [(link.from_socket, link.to_socket) for link in output.inputs["Surface"].links]
        emission = tree.nodes.new("ShaderNodeEmission")
        socket = bsdf.inputs[channel]
        if socket.is_linked:
            tree.links.new(socket.links[0].from_socket, emission.inputs["Color"])
        elif socket.type == "RGBA":
            emission.inputs["Color"].default_value = socket.default_value
        else:
            value = socket.default_value
            emission.inputs["Color"].default_value = (value, value, value, 1)
        tree.links.new(emission.outputs[0], output.inputs["Surface"])
        restores.append((tree, emission, old))
    return restores


def bake(sources, targets, options, output):
    scene = bpy.context.scene
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = 1
    scene.render.threads_mode = "FIXED"
    scene.render.threads = 4
    artifacts, manifest = [], []
    for obj in sources:
        if not obj.data.materials:
            mat = bpy.data.materials.new("SourceDefault")
            mat.use_nodes = True
            obj.data.materials.append(mat)
    for i, target in enumerate(targets):
        if not target.data.uv_layers.active:
            raise ValueError("target needs UV; run uv_unwrap first")
        material = bpy.data.materials.new(f"Baked_{i}")
        material.use_nodes = True
        target.data.materials.clear()
        target.data.materials.append(material)
        for poly in target.data.polygons:
            poly.material_index = 0
        tree = material.node_tree
        image_node = tree.nodes.new("ShaderNodeTexImage")
        tree.nodes.active = image_node
        images = {}
        for channel, socket in [("baseColor", "Base Color"), ("roughness", "Roughness"),
                                ("metallic", "Metallic"), ("alpha", "Alpha"), ("normal", None)]:
            im = bpy.data.images.new(f"{i}_{channel}", width=options["resolution"],
                                     height=options["resolution"], alpha=True)
            im.colorspace_settings.name = "sRGB" if channel == "baseColor" else "Non-Color"
            image_node.image = im
            restores = set_source_channel(sources, socket) if socket else []
            try:
                activate(target)
                for src in sources:
                    src.select_set(True)
                bpy.ops.object.bake(type="EMIT" if socket else "NORMAL", use_selected_to_active=True,
                    max_ray_distance=options["ray_distance"], cage_extrusion=options["ray_distance"],
                    use_clear=True, margin=options["padding"], normal_space="TANGENT")
            finally:
                for source_tree, node, old in restores:
                    source_tree.nodes.remove(node)
                    for a, b in old:
                        source_tree.links.new(a, b)
            images[channel] = im
        size = options["resolution"] ** 2 * 4
        color, alpha = np.empty(size, dtype=np.float32), np.empty(size, dtype=np.float32)
        images["baseColor"].pixels.foreach_get(color)
        images["alpha"].pixels.foreach_get(alpha)
        color[3::4] = alpha[0::4]
        images["baseColor"].pixels.foreach_set(color)
        images["baseColor"].update()
        bsdf = tree.nodes.get("Principled BSDF")
        tree.nodes.remove(image_node)
        for channel in ("baseColor", "roughness", "metallic", "normal"):
            im = images[channel]
            filename = f"mesh_{i}_{channel}.png"
            im.filepath_raw = str(output / filename)
            im.file_format = "PNG"
            im.save()
            node = tree.nodes.new("ShaderNodeTexImage")
            node.image = im
            if channel == "normal":
                normal = tree.nodes.new("ShaderNodeNormalMap")
                tree.links.new(node.outputs["Color"], normal.inputs["Color"])
                tree.links.new(normal.outputs["Normal"], bsdf.inputs["Normal"])
            else:
                tree.links.new(node.outputs["Color"], bsdf.inputs[{
                    "baseColor": "Base Color", "roughness": "Roughness", "metallic": "Metallic"}[channel]])
                if channel == "baseColor":
                    tree.links.new(node.outputs["Alpha"], bsdf.inputs["Alpha"])
            artifacts.append({"role": f"texture-{i}-{channel}", "file": filename})
        manifest.append({"object": target.name, "channels": ["baseColor", "roughness", "metallic", "normal"],
                         "alpha": "baseColor.a", "normal_space": "tangent",
                         "ao": "not generated", "emission": "not transferred"})
    return artifacts, manifest


def surface_tree(objects):
    verts, polys = [], []
    for obj in objects:
        offset = len(verts)
        verts.extend(obj.matrix_world @ v.co for v in obj.data.vertices)
        polys.extend(tuple(offset + v for v in p.vertices) for p in obj.data.polygons)
    return BVHTree.FromPolygons(verts, polys)


def main(request):
    bpy.ops.wm.read_factory_settings(use_empty=True)
    output, operation, options = Path(request["output"]), request["operation"], request["options"]
    inputs = request["inputs"]
    if operation == "filter_parts":
        filter_parts(inputs["asset"], inputs["parts_manifest"], inputs["face_labels"], options, output)
        return
    objects = load(inputs.get("asset", inputs.get("target")))
    before = stats(objects)
    original = surface_tree(objects)
    report = {"operation": operation, "before": before, "warnings": [],
              "coordinates": "GLB Y-up preserved through Blender import/export; no normalization",
              "backend": {"blender": bpy.app.version_string, "xatlas": "0.0.9"}}
    extra = []
    if operation in {"mesh_cleanup", "mesh_repair"}:
        for obj in objects:
            clean(obj, options, operation == "mesh_repair")
    elif operation == "decimate":
        if options["target_faces"] >= before["triangles"]:
            # A reduction target above the current triangle count is a semantic
            # no-op. Do not weld seams, apply transforms, or touch topology/UVs.
            report["skipped"] = True
            report["skip_reason"] = "target_not_lower_than_source"
            report["warnings"].append(
                "Decimation skipped because target_faces is not lower than the source triangle count"
            )
        else:
            ratio = options["target_faces"] / before["triangles"]
            for obj in objects:
                # glTF commonly duplicates positions at UV/normal seams. Decimating
                # those split vertices treats one geometric surface as disconnected
                # islands. Weld only coincident geometry, then bake object scale into
                # the mesh so the exported GLB preserves the same world-space shape.
                extent = max(obj.dimensions)
                clean(obj, {"merge_distance": max(extent * 1e-7, 1e-9), "remove_loose": True})
                activate(obj)
                bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
                mod = obj.modifiers.new("Decimate", "DECIMATE")
                mod.ratio = ratio
                mod.use_collapse_triangulate = True
                bpy.ops.object.modifier_apply(modifier=mod.name)
            report["warnings"].append(
                "Decimation welds GLB seam vertices and changes topology; inspect achieved face count and rebake if needed"
            )
    elif operation == "retopology":
        for obj in objects:
            # GLB duplicates vertices at UV/normal seams. QuadriFlow needs the
            # geometric surface welded; this operation already invalidates UVs.
            extent = max(obj.dimensions)
            clean(obj, {"merge_distance": max(extent * 1e-7, 1e-9), "remove_loose": True})
            activate(obj)
            bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            obj.data.calc_loop_triangles()
            target = max(16, round(options["target_faces"] * len(obj.data.loop_triangles) / before["triangles"]))
            result = bpy.ops.object.quadriflow_remesh(target_faces=target, use_mesh_symmetry=False,
                use_preserve_boundary=options["preserve_boundary"], use_preserve_sharp=options["preserve_sharp"],
                seed=options["seed"])
            if "FINISHED" not in result or not any(len(p.vertices) == 4 for p in obj.data.polygons):
                raise ValueError("QuadriFlow failed; repair nonmanifold geometry first")
            obj.data.materials.clear()
        report["warnings"].append("Topology and material parameterization changed; run UV and rebake")
    elif operation == "uv_unwrap":
        maps = [unwrap(obj, options) for obj in objects]
        (output / "uv-map.json").write_text(json.dumps(maps), encoding="utf-8")
        extra.append({"role": "uv-mapping", "file": "uv-map.json"})
        report["uv_atlases"] = [{k: v for k, v in row.items() if k != "vertex_mapping"} for row in maps]
        for obj in objects:
            obj.data.materials.clear()
        report["warnings"].append("UV changed; appearance requires rebake from original asset")
    elif operation == "texture_bake":
        sources = load(inputs["source"])
        extra, report["materials"] = bake(sources, objects, options, output)
        for src in sources:
            bpy.data.objects.remove(src, do_unlink=True)
    elif operation != "inspect_mesh":
        raise ValueError("unsupported operation")
    report["after"] = stats(objects)
    distances = []
    for obj in objects:
        stride = max(1, len(obj.data.vertices) // 2000)
        for v in list(obj.data.vertices)[::stride]:
            hit = original.find_nearest(obj.matrix_world @ v.co)
            if hit[0] is not None:
                distances.append(hit[3])
    report["surface_distance"] = {"direction": "sampled output vertices to input surface",
        "samples": len(distances), "max": max(distances, default=0),
        "mean": sum(distances) / max(1, len(distances)), "units": "asset units"}
    report["topology_changed"] = before["geometry_revision"] != report["after"]["geometry_revision"]
    if operation == "texture_bake" and report["topology_changed"]:
        raise ValueError("baking unexpectedly changed geometry")
    if "target_faces" in options:
        report["target_faces"] = options["target_faces"]
        report["achieved_faces"] = report["after"]["polygons" if operation == "retopology" else "triangles"]
    artifacts = save_assets(objects, output)
    if operation == "decimate" and report.get("skipped"):
        # True no-op: keep the canonical primary GLB byte-for-byte identical.
        # The editable OBJ and quality report are auxiliary evidence only.
        shutil.copyfile(inputs["asset"], output / "asset.glb")
    (output / "quality.json").write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    artifacts.extend(extra)
    artifacts.append({"role": "quality-report", "file": "quality.json"})
    (output / "runtime.json").write_text(json.dumps({"artifacts": artifacts, "metrics": report}), encoding="utf-8")


if __name__ == "__main__":
    main(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    # The standalone bpy 4.2 wheel can fail during interpreter teardown in
    # both Windows and minimal Linux containers after successful exports.
    # All artifacts/JSON are closed above, so bypass only successful teardown.
    import os
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
