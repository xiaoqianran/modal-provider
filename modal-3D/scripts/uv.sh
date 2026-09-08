#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
export UV_PROJECT_ENVIRONMENT="${repo_root}/.venv-linux"
export UV_DEFAULT_INDEX=https://pypi.org/simple
export UV_LINK_MODE=copy
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

cd "${repo_root}"
exec uv "$@"
