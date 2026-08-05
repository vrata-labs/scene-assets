# Authoring Contract

## DCC

Scene sources are generated and saved with Blender 4.5.12 LTS. One Blender
unit equals one meter. The walkable floor is at Z=0 in Blender and Y=0 after
glTF export.

## Release Tracks

The `0.1.x` line is immutable visual blockout history. The `0.2.x` line is for
art-direction candidates with original embedded PBR textures, detailed props,
and runtime lighting. Neither line is an active product template.

Fresh procedural regeneration may reorder evaluated bevel buffers. Release
reproduction therefore starts from the tracked source blend after modifiers
have been applied. Independent Blender 4.5.12 processes exporting the same
tracked source are byte-identical. `pnpm verify:source-exports` compares those
exports with the candidate GLBs before publication. The published full Git
commit SHA and checked `manifest.json` remain authoritative.

## Rights

The current scenes are entirely procedural original work. No external meshes,
textures, scans, photographs, fonts, HDR files, audio, or private source files
are included. Publication does not grant a general reuse license; all rights
remain with Vrata unless a later repository license says otherwise.

## Publishing

Never replace files under an already published scene/version path. Create a
new version, rebuild `manifest.json`, validate it, and publish the resulting
Git commit. Runtime URLs must reference a full Git commit SHA.
