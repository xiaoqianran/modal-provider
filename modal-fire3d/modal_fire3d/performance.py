"""Pure helpers for Fire3D performance experiments.

The official protocol remains untouched. These helpers only rewrite a copied
background-only command so optimized Modal workers can be benchmarked against
an existing accepted run.
"""

from __future__ import annotations

import shlex
from pathlib import Path


def validate_run_id(value: str) -> str:
    if not value or not value.isascii() or not all(c.isalnum() or c in "-_" for c in value):
        raise ValueError("invalid run identifier")
    return value


def _set_flag(command: list[str], positive: str, negative: str, enabled: bool) -> None:
    desired = positive if enabled else negative
    opposite = negative if enabled else positive
    if desired in command:
        return
    if opposite in command:
        command[command.index(opposite)] = desired
        return
    command.append(desired)


def _set_option(command: list[str], option: str, value: str) -> None:
    if option in command:
        index = command.index(option)
        if index + 1 >= len(command):
            raise ValueError(f"missing value for {option}")
        command[index + 1] = value
        return
    command.extend([option, value])


def build_background_command(
    source_log: Path,
    *,
    python: str,
    runner: Path,
    source_manifest: Path,
    output_root: Path,
    policy: str,
    decode_resolution: int = 512,
    detailed_profile: bool = False,
    model_cache: bool = True,
) -> list[str]:
    """Rewrite the accepted reconstruction command for one background rerun."""
    if policy not in {"official", "no_room_filter"}:
        raise ValueError("unknown background policy")
    if decode_resolution < 128 or decode_resolution > 512 or decode_resolution % 32:
        raise ValueError("decode_resolution must be a multiple of 32 in [128, 512]")
    first_line = source_log.read_text(encoding="utf-8").splitlines()[0]
    command = shlex.split(first_line)
    if len(command) < 2:
        raise ValueError("source reconstruction command is malformed")
    command[0] = python
    command[1] = str(runner)
    _set_option(command, "--batch-scenes", str(source_manifest))
    _set_option(command, "--output-root", str(output_root))
    _set_option(command, "--object-selection", "background")
    _set_option(command, "--shape-decode-resolution", str(decode_resolution))
    _set_flag(command, "--resume-existing", "--no-resume-existing", False)
    _set_flag(command, "--model-cache", "--no-model-cache", model_cache)
    _set_flag(
        command,
        "--appearance-detailed-profile",
        "--no-appearance-detailed-profile",
        detailed_profile,
    )
    _set_flag(
        command,
        "--background-room-box-prior",
        "--no-background-room-box-prior",
        policy == "official",
    )
    return command
