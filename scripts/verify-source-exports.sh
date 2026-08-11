#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
blender_bin="${BLENDER_BIN:-blender}"
release_version="${RELEASE_VERSION:?set RELEASE_VERSION to the release being verified}"
output_root="$(mktemp -d)"
trap 'rm -rf "$output_root"' EXIT

source_scene_ids=(personal-workspace-review-v1 meeting-room-review-v1 presentation-room-review-v1)
custom_source_ids=0
if [[ -n "${SOURCE_SCENE_IDS:-}" ]]; then
  IFS=',' read -r -a source_scene_ids <<< "$SOURCE_SCENE_IDS"
  custom_source_ids=1
fi
export_args=()
for scene_id in "${source_scene_ids[@]}"; do
  export_args+=(--scene-id "$scene_id")
done

PYTHONHASHSEED=0 "$blender_bin" --background --factory-startup --threads 1 --python-exit-code 1 \
  --python "$repo_root/scripts/export_sources.py" -- \
  --repo-root "$repo_root" --version "$release_version" --output-root "$output_root" "${export_args[@]}"

release_scene_ids=("${source_scene_ids[@]}")
if [[ "$release_version" == "1.0.0" && "$custom_source_ids" == "0" ]]; then
  release_scene_ids=(personal-workspace-v1 meeting-room-v1 presentation-room-v1)
fi

for index in "${!source_scene_ids[@]}"; do
  source_scene_id="${source_scene_ids[$index]}"
  release_scene_id="${release_scene_ids[$index]}"
  expected="$repo_root/assets/scenes/$release_scene_id/$release_version/scene.glb"
  actual="$output_root/$source_scene_id/scene.glb"
  if ! cmp -s "$expected" "$actual"; then
    sha256sum "$expected" "$actual"
    printf 'source_export_mismatch:%s:%s@%s\n' "$source_scene_id" "$release_scene_id" "$release_version" >&2
    exit 1
  fi
  sha256sum "$actual"
done

printf 'All tracked Blender sources reproduce release %s byte-for-byte.\n' "$release_version"
