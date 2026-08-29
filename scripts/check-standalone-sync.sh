#!/usr/bin/env bash
set -euo pipefail

ROOT=$(git rev-parse --show-toplevel)
TMP=$(mktemp -d)
trap "rm -rf \"$TMP\"" EXIT

all_packages=(
  modal-2D
  modal-2D-client
  modal-3D
  modal-3D-client
  modal-gen-client
  modal-EmbodiedGen
  modal-build
  modal-world
)

repo_url() {
  case "$1" in
    modal-2D) echo "https://github.com/xiaoqianran/modal-2D.git" ;;
    modal-2D-client) echo "https://github.com/xiaoqianran/modal-2D-client.git" ;;
    modal-3D) echo "https://github.com/xiaoqianran/modal-3D.git" ;;
    modal-3D-client) echo "https://github.com/xiaoqianran/modal-3D-client.git" ;;
    modal-gen-client) echo "https://github.com/xiaoqianran/modal-gen-client.git" ;;
    modal-EmbodiedGen) echo "https://github.com/xiaoqianran/modal-EmbodiedGen.git" ;;
    modal-build) echo "https://github.com/xiaoqianran/modal-build.git" ;;
    modal-world) echo "https://github.com/xiaoqianran/modal-world.git" ;;
    *) return 1 ;;
  esac
}

repo_branch() {
  case "$1" in
    modal-2D|modal-2D-client|modal-3D-client|modal-gen-client) echo "main" ;;
    modal-3D|modal-EmbodiedGen|modal-build|modal-world) echo "master" ;;
    *) return 1 ;;
  esac
}

packages=("${all_packages[@]}")
if (($#)); then
  packages=("$@")
fi

result=0
for package in "${packages[@]}"; do
  url=$(repo_url "$package") || {
    echo "UNKNOWN  $package" >&2
    exit 2
  }
  branch=$(repo_branch "$package")
  source_dir="$ROOT/$package"
  target_dir="$TMP/$package"

  if [[ ! -d "$source_dir" ]]; then
    echo "MISSING  $package ($source_dir)" >&2
    result=1
    continue
  fi

  git clone -q --depth 1 --branch "$branch" "$url" "$target_dir"
  sha=$(git -C "$target_dir" rev-parse --short=12 HEAD)

  set +e
  differences=$(diff -qr \
    --exclude=.git \
    --exclude=.github \
    --exclude=.venv \
    --exclude=__pycache__ \
    --exclude=.pytest_cache \
    --exclude=.ruff_cache \
    --exclude="*.egg-info" \
    "$source_dir" "$target_dir" 2>&1)
  code=$?
  set -e

  if ((code == 0)); then
    printf "SYNC    %-20s %-6s %s\n" "$package" "$branch" "$sha"
    continue
  fi

  if ((code == 1)); then
    printf "DRIFT   %-20s %-6s %s\n" "$package" "$branch" "$sha"
    printf "%s\n" "$differences" | sed -n "1,80p"
    result=1
    continue
  fi

  printf "ERROR   %-20s diff failed (%s)\n" "$package" "$code" >&2
  printf "%s\n" "$differences" >&2
  exit "$code"
done

exit "$result"
