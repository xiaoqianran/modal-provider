#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

for model in \
  sana-sprint-0.6b \
  sana-sprint-1.6b \
  qwen-image-2512 \
  z-image-turbo \
  hidream-o1-image
do
  uv run modal run -m modal_2d.app::prefetch --model-id "$model"
done

uv run modal deploy -m modal_2d.app
uv run modal deploy -m modal_2d.workers.sana_sprint
uv run modal deploy -m modal_2d.workers.qwen_image_2512
uv run modal deploy -m modal_2d.workers.z_image_turbo
uv run modal deploy -m modal_2d.workers.hidream_o1
