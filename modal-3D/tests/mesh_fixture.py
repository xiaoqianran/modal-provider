"""Create a transformed, textured fixture using the same Blender runtime as production."""
import sys
from pathlib import Path

import bpy

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, location=(1.25, -0.5, 0.75))
obj = bpy.context.object
obj.scale = (1.0, 0.7, 1.3)
mat = bpy.data.materials.new("CheckerPBR")
mat.use_nodes = True
shader = mat.node_tree.nodes.get("Principled BSDF")
shader.inputs["Metallic"].default_value = 0.35
shader.inputs["Roughness"].default_value = 0.6
image = bpy.data.images.new("checker", width=16, height=16)
pixels = []
for y in range(16):
    for x in range(16):
        pixels.extend((0.8, 0.1, 0.05, 1) if (x // 4 + y // 4) % 2 else (0.1, 0.5, 0.9, 1))
image.pixels[:] = pixels
image.pack()
node = mat.node_tree.nodes.new("ShaderNodeTexImage")
node.image = image
mat.node_tree.links.new(node.outputs["Color"], shader.inputs["Base Color"])
obj.data.materials.append(mat)
bpy.ops.export_scene.gltf(filepath=str(Path(sys.argv[1]).resolve()), export_format="GLB")
if sys.platform == "win32":
    import os
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)
