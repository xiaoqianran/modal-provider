from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path
import sys

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modal_3d.common import validate_canonical_png
from modal_3d.png import foreground_stats


def _convert_command() -> str:
    command = shutil.which("magick") or shutil.which("convert")
    if command is None:
        raise RuntimeError("ImageMagick is required (magick or convert)")
    return command


def _run(command: str, *args: str) -> None:
    subprocess.run([command, *args], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def build_canonical(source: Path, mask: Path, output: Path) -> dict:
    """Compose source RGB + alpha mask using isolated ImageMagick stages.

    Staging is intentional. A single long ImageMagick command previously lost
    RGB channels while preserving alpha, producing expensive but invalid 3D
    benchmark inputs.
    """
    command = _convert_command()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="modal3d-canonical-") as tmp:
        tmp = Path(tmp)
        composed = tmp / "composed.png"
        resized = tmp / "resized.png"
        _run(command, str(source), str(mask), "-compose", "CopyOpacity", "-composite", str(composed))
        _run(command, str(composed), "-resize", "1024x1024", str(resized))
        _run(
            command,
            str(resized),
            "-gravity",
            "center",
            "-background",
            "none",
            "-extent",
            "1024x1024",
            f"PNG32:{output}",
        )

    contract = validate_canonical_png(output)
    quality = foreground_stats(output.read_bytes(), 1024, 1024)
    return {**contract, **quality}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build one canonical 1024x1024 RGBA benchmark input")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--mask", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-rgb-nonzero-fraction", type=float, default=0.01)
    parser.add_argument("--allow-low-information", action="store_true")
    args = parser.parse_args()

    stats = build_canonical(args.source, args.mask, args.output)
    if (
        not args.allow_low_information
        and stats["foreground_rgb_nonzero_fraction"] < args.min_rgb_nonzero_fraction
    ):
        args.output.unlink(missing_ok=True)
        raise SystemExit(
            "canonical build rejected: foreground RGB contains too little information; "
            "use --allow-low-information only for intentionally black/near-black subjects"
        )
    print(stats)


if __name__ == "__main__":
    main()
