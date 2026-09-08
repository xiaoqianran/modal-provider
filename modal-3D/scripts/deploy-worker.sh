#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
    echo "Usage: $0 <worker.py>" >&2
    exit 2
fi

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
worker="$1"
if [[ "$worker" != /* ]]; then
    worker="${repo_root}/${worker}"
fi
worker_path="$(realpath "$worker")"

case "$worker_path" in
    "${repo_root}"/*.py) ;;
    *)
        echo "Worker must be inside the repository: ${worker_path}" >&2
        exit 2
        ;;
esac

if [[ "$worker_path" != *.py ]]; then
    echo "Worker must be a Python file: ${worker_path}" >&2
    exit 2
fi

relative_path="${worker_path#"${repo_root}/"}"
module="${relative_path%.py}"
module="${module//\//.}"

uv_args=(
    run
    --isolated
    --frozen
    --default-index https://pypi.org/simple
)

export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8

cd "$repo_root"
uv "${uv_args[@]}" modal run -e main -m "${module}::sync_weights"
uv "${uv_args[@]}" modal deploy -e main -m "$module"
