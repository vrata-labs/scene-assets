#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
blender_bin="${BLENDER_BIN:-blender}"
extra_args=()

if [[ "${SKIP_RENDER:-0}" == "1" ]]; then
  extra_args+=(--skip-render)
fi

if ! command -v "$blender_bin" >/dev/null 2>&1 && [[ ! -x "$blender_bin" ]]; then
  echo "blender_not_found: set BLENDER_BIN to Blender 4.5.12 LTS" >&2
  exit 1
fi

PYTHONHASHSEED=0 "$blender_bin" --background --factory-startup --threads 1 \
  --python "$repo_root/scripts/build_review_scenes.py" -- \
  --repo-root "$repo_root" "${extra_args[@]}"

node "$repo_root/scripts/build-manifest.mjs"
