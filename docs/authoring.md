# Authoring Contract

## DCC

Scene sources are generated and saved with Blender 4.5.12 LTS. One Blender
unit equals one meter. The walkable floor is at Z=0 in Blender and Y=0 after
glTF export.

## Release Tracks

The `0.1.x` line is immutable visual blockout history. The `0.2.x` line is
immutable art-direction review history with original embedded PBR textures,
detailed props, and runtime lighting. The final `1.0.0` releases use product
scene identities and pass the platform checks for scene identity, required
surface geometry, and seat count.

Fresh procedural regeneration may reorder evaluated bevel buffers. Release
reproduction therefore starts from the tracked source blend after modifiers
have been applied. Independent Blender 4.5.12 processes exporting the same
tracked source are byte-identical. `pnpm verify:source-exports` compares those
exports with the candidate or promoted final GLBs before publication. The
published full Git commit SHA and checked `manifest.json` remain authoritative.

Final releases reuse the accepted tracked sources rather than duplicating
source blends:

| Tracked source ID | Final release ID |
| --- | --- |
| `personal-workspace-review-v1` | `personal-workspace-v1` |
| `meeting-room-review-v1` | `meeting-room-v1` |
| `presentation-room-review-v1` | `presentation-room-v1` |

The final GLB and preview must remain byte-identical to the corresponding
`0.2.2` candidate. Runtime-significant manifest values must also remain equal
after normalizing scene-scoped IDs and release-facing descriptive metadata.

## Rights

The current scenes are entirely procedural original work. No external meshes,
textures, scans, photographs, fonts, HDR files, audio, or private source files
are included. Publication does not grant a general reuse license; all rights
remain with Vrata unless a later repository license says otherwise.

## Publishing

Never replace files under an already published scene/version path. Create a
new version, rebuild `manifest.json`, validate it, and publish the resulting
Git commit. Do not use procedural regeneration to promote an accepted candidate
to `1.0.0`. Runtime URLs must reference a full Git commit SHA.
