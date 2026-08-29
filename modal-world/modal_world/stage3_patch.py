from __future__ import annotations

from pathlib import Path

from .worldstereo_patch import patch_worldstereo_wrapper


def patch_stage3_runtime(source_root: str | Path) -> None:
    """Apply pinned WorldStereo/DINO offline fixes at image build time."""
    root = Path(source_root)
    worldgen_root = root / "hyworld2/worldgen"
    patch_worldstereo_wrapper(worldgen_root / "models/worldstereo_wrapper.py")

    retrieval_path = worldgen_root / "src/retrieval_wm.py"
    source = retrieval_path.read_text()
    processor_old = "            self.processor = AutoImageProcessor.from_pretrained(model_path, use_fast=True)\n"
    processor_new = (
        "            self.processor = AutoImageProcessor.from_pretrained(\n"
        "                model_path, use_fast=True, local_files_only=True\n"
        "            )\n"
    )
    model_old = "            self.model = AutoModel.from_pretrained(model_path).to(self.device)\n"
    model_new = (
        "            self.model = AutoModel.from_pretrained(\n"
        "                model_path, local_files_only=True\n"
        "            ).to(self.device)\n"
    )
    if source.count(processor_old) != 1:
        raise RuntimeError("expected pinned DINO processor loader not found")
    if source.count(model_old) != 1:
        raise RuntimeError("expected pinned DINO model loader not found")
    source = source.replace(processor_old, processor_new, 1)
    source = source.replace(model_old, model_new, 1)
    retrieval_path.write_text(source)
