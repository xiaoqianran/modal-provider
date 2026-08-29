from pathlib import Path

path = Path("/workspace/EmbodiedGen/thirdparty/sam3d/sam3d_objects/pipeline/inference_pipeline.py")
source = path.read_text()
old = """def set_attention_backend():
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)

    logger.info(f\"GPU name is {gpu_name}\")
"""
new = """def set_attention_backend():
    gpu_name = \"CPU-snapshot\"
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)

    logger.info(f\"GPU name is {gpu_name}\")
"""
if new in source:
    raise SystemExit(0)
if source.count(old) != 1:
    raise RuntimeError(f"unexpected set_attention_backend source in {path}")
path.write_text(source.replace(old, new, 1))
print(f"patched {path} for Modal CPU memory snapshots")
