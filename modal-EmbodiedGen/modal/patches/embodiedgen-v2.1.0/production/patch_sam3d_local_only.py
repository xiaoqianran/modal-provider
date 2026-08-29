from pathlib import Path

path = Path('/workspace/EmbodiedGen/embodied_gen/models/sam3d.py')
text = path.read_text()
text = text.replace('from modelscope import snapshot_download\n', '')
old = '''        if not os.path.exists(local_dir):\n            snapshot_download("facebook/sam-3d-objects", local_dir=local_dir)\n'''
new = '''        if not os.path.exists(local_dir):\n            raise FileNotFoundError(\n                f"SAM3D weights are missing at {local_dir}; run preload_weights before serving requests"\n            )\n'''
if old not in text:
    raise RuntimeError('SAM3D snapshot_download fallback block not found')
text = text.replace(old, new, 1)
path.write_text(text)
print(f'patched {path} for local-only SAM3D weights')
