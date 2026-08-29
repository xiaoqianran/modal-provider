#!/usr/bin/env bash
set -euo pipefail

uv run modal deploy -m modal_2d.app
uv run modal deploy -m modal_2d.workers.sana_sprint
uv run modal deploy -m modal_2d.workers.qwen_image_2512
uv run modal deploy -m modal_2d.workers.z_image_turbo
uv run modal deploy -m modal_2d.workers.hidream_o1
