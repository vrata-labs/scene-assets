#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
blender_bin="${BLENDER_BIN:-blender}"
release_version="${RELEASE_VERSION:?set RELEASE_VERSION to the release being verified}"
output_root="$(mktemp -d)"
trap 'rm -rf "$output_root"' EXIT

PYTHONHASHSEED=0 "$blender_bin" --background --factory-startup --threads 1 --python-exit-code 1 \
  --python "$repo_root/scripts/export_sources.py" -- \
  --repo-root "$repo_root" --version "$release_version" --output-root "$output_root"

for scene_id in personal-workspace-review-v1 meeting-room-review-v1 presentation-room-review-v1; do
  expected="$repo_root/assets/scenes/$scene_id/$release_version/scene.glb"
  actual="$output_root/$scene_id/scene.glb"
  if ! cmp -s "$expected" "$actual"; then
    sha256sum "$expected" "$actual"
    printf 'source_export_mismatch:%s@%s\n' "$scene_id" "$release_version" >&2
    exit 1
  fi
  sha256sum "$actual"
done

printf 'All tracked Blender sources reproduce release %s byte-for-byte.\n' "$release_version"
