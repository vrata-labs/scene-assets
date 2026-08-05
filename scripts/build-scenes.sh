#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
blender_bin="${BLENDER_BIN:-blender}"
review_version="${REVIEW_VERSION:?set REVIEW_VERSION to a new 0.1.x release path}"
extra_args=()

if [[ "${SKIP_RENDER:-0}" == "1" ]]; then
  extra_args+=(--skip-render)
fi

if ! command -v "$blender_bin" >/dev/null 2>&1 && [[ ! -x "$blender_bin" ]]; then
  echo "blender_not_found: set BLENDER_BIN to Blender 4.5.12 LTS" >&2
  exit 1
fi

PYTHONHASHSEED=0 "$blender_bin" --background --factory-startup --threads 1 --python-exit-code 1 \
  --python "$repo_root/scripts/build_review_scenes.py" -- \
  --repo-root "$repo_root" --version "$review_version" "${extra_args[@]}"

node "$repo_root/scripts/build-manifest.mjs"
